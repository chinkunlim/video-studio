"""Dual-engine Avatar presenter adapter: Route B (FFmpeg lightweight) & Route A (SadTalker lip-sync)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from video_studio.config.settings import load_config

logger = logging.getLogger(__name__)
DEFAULT_PORTRAIT_BG_RGB = (245, 242, 235)


@dataclass(frozen=True)
class AvatarResult:
    """Result metadata from generating or compositing an avatar presenter clip.

    Attributes:
        engine: Engine used ('lightweight' or 'sadtalker').
        avatar_video: Path to the standalone talking-head clip.
        composited_video: Path to the final video with PiP overlay, if composited.
    """

    engine: str
    avatar_video: Path
    composited_video: Path | None = None


def avatar_environment_status(sadtalker_dir: Path | None) -> dict[str, Any]:
    """Inspect readiness of Route B (ffmpeg) and Route A (SadTalker under DATA_DIR).

    Args:
        sadtalker_dir: Configured SadTalker installation directory.

    Returns:
        Dictionary describing availability of both avatar engines.
    """
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    sad_exists = bool(sadtalker_dir and sadtalker_dir.is_dir())
    venv_py = (sadtalker_dir / ".venv" / "bin" / "python") if sadtalker_dir else None
    ckpt_dir = (sadtalker_dir / "checkpoints") if sadtalker_dir else None
    checkpoints = (
        sorted(p.name for p in ckpt_dir.glob("*.safetensors"))
        + sorted(p.name for p in ckpt_dir.glob("*.pth*"))
        if ckpt_dir and ckpt_dir.is_dir()
        else []
    )
    return {
        "lightweight": {"ready": ffmpeg_ok, "note": "Route B: FFmpeg animated presenter PiP"},
        "sadtalker": {
            "ready": bool(sad_exists and venv_py and venv_py.exists() and checkpoints),
            "dir": str(sadtalker_dir) if sadtalker_dir else "",
            "dir_exists": sad_exists,
            "venv_ready": bool(venv_py and venv_py.exists()),
            "checkpoints": checkpoints,
        },
    }


def ensure_opaque_portrait(
    image_path: Path,
    work_dir: Path,
    bg_rgb: tuple[int, int, int] = DEFAULT_PORTRAIT_BG_RGB,
) -> Path:
    """Composite transparent RGBA portrait images onto an opaque cream background.

    Args:
        image_path: Source portrait image path.
        work_dir: Working directory where the flattened PNG is written if needed.
        bg_rgb: Solid RGB background color used behind alpha transparency.

    Returns:
        Original path when already opaque, or path to flattened RGB PNG.
    """
    with Image.open(image_path) as raw:
        if "A" not in raw.getbands():
            return image_path
        min_alpha = raw.getchannel("A").getextrema()[0]
        if isinstance(min_alpha, int) and min_alpha == 255:
            return image_path
        rgba = raw.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (*bg_rgb, 255))
        work_dir.mkdir(parents=True, exist_ok=True)
        out_path = work_dir / f"{image_path.stem}_opaque.png"
        Image.alpha_composite(bg, rgba).convert("RGB").save(out_path)
    logger.info("Composited transparent portrait onto opaque background: %s", out_path)
    return out_path


def _sadtalker_env() -> dict[str, str]:
    """Build subprocess environment for SadTalker with PyTorch 2.6+ and Apple MPS flags.

    Returns:
        Environment dictionary inheriting AppConfig process settings.
    """
    env = load_config().process_env()
    env.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    return env


def _probe_duration(media_path: Path) -> float:
    """Measure media duration in seconds using ffprobe.

    Args:
        media_path: Path to audio or video file.

    Returns:
        Duration in seconds.

    Raises:
        ProviderError: If ffprobe fails.
    """
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {media_path}: {proc.stderr.strip()}")
    return max(1.0, float(proc.stdout.strip() or "1.0"))


def render_lightweight_avatar(
    image_path: Path,
    audio_path: Path,
    out_mp4: Path,
    fps: int = 30,
) -> Path:
    """Render Route B lightweight animated portrait clip synced to narration audio duration.

    Args:
        image_path: Source portrait image (e.g. Einstein PNG/JPG).
        audio_path: Narration audio track.
        out_mp4: Output MP4 path for the avatar clip.
        fps: Frames per second.

    Returns:
        Path to generated avatar MP4.

    Raises:
        ProviderError: If ffmpeg exits non-zero.
    """
    duration = _probe_duration(audio_path)
    frames = max(1, int(round(duration * fps)))
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    src_img = ensure_opaque_portrait(image_path, out_mp4.parent)
    vf = (
        "scale=512:512:force_original_aspect_ratio=increase,"
        "crop=512:512,"
        f"zoompan=z='1.0+0.025*sin(2*PI*on/{fps}/4)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=512x512:fps={fps},"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(src_img),
        "-i",
        str(audio_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(out_mp4),
    ]
    logger.info("Rendering Route B lightweight avatar: %s", out_mp4)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg lightweight avatar failed: {proc.stderr[-400:]}")
    return out_mp4


def render_sadtalker_avatar(
    image_path: Path,
    audio_path: Path,
    out_mp4: Path,
    sadtalker_dir: Path,
) -> Path:
    """Render Route A lip-synced talking-head video via isolated SadTalker installation.

    Args:
        image_path: Source portrait image.
        audio_path: Narration audio track.
        out_mp4: Destination MP4 path.
        sadtalker_dir: Path to isolated SadTalker repo with .venv and checkpoints/.

    Returns:
        Path to generated SadTalker MP4.

    Raises:
        ProviderError: If SadTalker is not ready or inference fails.
    """
    status = avatar_environment_status(sadtalker_dir)["sadtalker"]
    if not status["ready"]:
        raise RuntimeError(
            f"SadTalker 尚未完成安裝或缺少 checkpoints（dir={sadtalker_dir}, "
            f"venv={status['venv_ready']}, checkpoints={len(status['checkpoints'])}）。"
            "請先補齊 SadTalker 模型權重，或改用 Route B (lightweight)。"
        )
    venv_py = sadtalker_dir / ".venv" / "bin" / "python"
    result_dir = out_mp4.parent / "sadtalker_raw"
    result_dir.mkdir(parents=True, exist_ok=True)
    src_img = ensure_opaque_portrait(image_path, result_dir)
    cmd = [
        str(venv_py),
        str(sadtalker_dir / "inference.py"),
        "--driven_audio",
        str(audio_path),
        "--source_image",
        str(src_img),
        "--result_dir",
        str(result_dir),
        "--preprocess",
        "full",
        "--still",
    ]
    logger.info("Running Route A SadTalker inference in %s", sadtalker_dir)
    proc = subprocess.run(
        cmd, cwd=str(sadtalker_dir), env=_sadtalker_env(), capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"SadTalker inference failed: {proc.stderr[-500:]}")
    mp4s = sorted(result_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        raise RuntimeError("SadTalker finished but produced no .mp4 file")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4s[0], out_mp4)
    return out_mp4


def overlay_avatar_pip(
    main_video: Path,
    avatar_video: Path,
    out_video: Path,
    position: str = "bottom-right",
    scale: float = 0.22,
) -> Path:
    """Composite an avatar talking-head video as a corner PiP overlay onto main_video.

    Args:
        main_video: Base video with audio track.
        avatar_video: Talking-head avatar video.
        out_video: Output composited video path.
        position: Corner placement ('bottom-right', 'bottom-left', 'top-right', 'top-left').
        scale: Relative width ratio of avatar overlay vs main video width.

    Returns:
        Path to composited output video.

    Raises:
        ProviderError: If ffmpeg fails during overlay compositing.
    """
    coords = {
        "bottom-right": "W-w-36:H-h-36",
        "bottom-left": "36:H-h-36",
        "top-right": "W-w-36:36",
        "top-left": "36:36",
    }.get(position, "W-w-36:H-h-36")
    filter_complex = (
        f"[1:v][0:v]scale2ref=w=iw*{scale}:h=ow/mdar[pip][base];"
        f"[pip]drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=4[pip_framed];"
        f"[base][pip_framed]overlay={coords}:shortest=1[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(main_video),
        "-i",
        str(avatar_video),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        str(out_video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg avatar PiP overlay failed: {proc.stderr[-400:]}")
    return out_video
