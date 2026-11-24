"""Service for generating and compositing Avatar presenter overlays onto rendered videos."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.video.engine.avatar_engine import (
    AvatarResult,
    avatar_environment_status,
    has_alpha_channel,
    overlay_avatar_pip,
    render_lightweight_avatar,
    render_sadtalker_avatar,
)
from video_studio.services.video.engine.media import SubtitleBurnOptions, burn_subtitles

logger = logging.getLogger(__name__)


def get_avatar_status() -> dict[str, object]:
    """Return availability status of Route A (SadTalker) and Route B (FFmpeg lightweight).

    Returns:
        Dictionary describing readiness of both avatar engines.
    """
    return avatar_environment_status(load_app_config().sadtalker_dir)


def find_avatar_image(job: J.Job, image_name: str = "") -> Path:
    """Locate the portrait image in job.input/ for avatar rendering.

    Args:
        job: Loaded Job instance.
        image_name: Optional explicit filename inside input/.

    Returns:
        Path to the portrait image.

    Raises:
        FileNotFoundError: If no suitable portrait image is found.
    """
    candidates: list[str] = []
    if image_name.strip():
        candidates.append(image_name.strip())
    cfg_img = str(job.cfg.get("avatar", {}).get("image", "")).strip()
    if cfg_img:
        candidates.append(cfg_img)
    for name in candidates:
        p = job.input / name
        if p.is_file():
            return p
    for pattern in ("avatar.*", "portrait.*", "*.png", "*.jpg", "*.jpeg", "*.webp"):
        matches = sorted(job.input.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"在 {job.input} 找不到頭像圖片（請上傳 avatar.png / portrait.jpg 或於設定指定檔名）。"
    )


def apply_avatar_to_job(
    job_name: str,
    engine: str = "lightweight",
    position: str = "bottom-right",
    image_name: str = "",
) -> AvatarResult:
    """Generate an avatar clip (Route A SadTalker or Route B lightweight) and overlay onto latest video.

    Args:
        job_name: Target job name.
        engine: 'lightweight' (Route B) or 'sadtalker' (Route A).
        position: Corner placement ('bottom-right', 'bottom-left', 'top-right', 'top-left').
        image_name: Optional avatar image filename inside input/.

    Returns:
        AvatarResult with generated clip and composited video paths.

    Raises:
        FileNotFoundError: If required narration.wav, video.mp4, or avatar image is missing.
    """
    job = J.find(job_name)
    out_v = job.latest_output()
    if not out_v:
        raise FileNotFoundError("找不到 output/vN/，請先完成配音與影片渲染。")
    audio_path = out_v / "narration.wav"
    main_video = out_v / "video.mp4"
    if not audio_path.is_file() or not main_video.is_file():
        raise FileNotFoundError(f"{out_v} 缺少 narration.wav 或 video.mp4，請先執行配音與影片渲染。")

    portrait = find_avatar_image(job, image_name)
    app_cfg = load_app_config()
    ext = ".mov" if (engine != "sadtalker" and has_alpha_channel(portrait)) else ".mp4"
    avatar_clip = job.work / f"avatar_{engine}{ext}"
    if engine == "sadtalker":
        assert app_cfg.sadtalker_dir is not None
        render_sadtalker_avatar(portrait, audio_path, avatar_clip, app_cfg.sadtalker_dir)
    else:
        render_lightweight_avatar(portrait, audio_path, avatar_clip)

    scale = float(job.cfg.get("avatar", {}).get("scale", 0.22) or 0.22)
    composited = out_v / "video_avatar.mp4"
    overlay_avatar_pip(main_video, avatar_clip, composited, position=position, scale=scale)
    # Replace video.mp4 and re-burn subtitles if video_subtitled.mp4 exists
    composited.replace(main_video)
    srt_path = out_v / "subtitles_youtube.srt"
    if not srt_path.is_file():
        srt_path = out_v / "subtitles_vlc.srt"
    if srt_path.is_file():
        burn_subtitles(
            main_video,
            srt_path,
            out_v / "video_subtitled.mp4",
            SubtitleBurnOptions(cfg=job.cfg, work=job.work),
        )
    logger.info("Applied %s avatar overlay to %s", engine, main_video)
    return AvatarResult(engine=engine, avatar_video=avatar_clip, composited_video=main_video)


def _find_preview_audio(job: J.Job) -> Path:
    """Find an audio file for 10s avatar preview (output narration, prosody preview, or first take).

    Args:
        job: Loaded Job instance.

    Returns:
        Path to an existing WAV file.

    Raises:
        FileNotFoundError: If no WAV file exists yet for this job.
    """
    out_v = job.latest_output()
    if out_v and (out_v / "narration.wav").is_file():
        return out_v / "narration.wav"
    if (job.review / "prosody_normal.wav").is_file():
        return job.review / "prosody_normal.wav"
    takes = sorted(job.takes_dir.glob("*.wav")) if job.takes_dir.is_dir() else []
    if takes:
        return takes[0]
    raise FileNotFoundError("找不到音檔：請先執行「10 秒韻律試聽」或「生成配音 (narrate build)」。")


def preview_avatar_ab_10s(job_name: str, image_name: str = "") -> dict[str, object]:
    """Generate 10-second Route B (lightweight) and Route A (SadTalker) previews into review/.

    Args:
        job_name: Target job name.
        image_name: Optional portrait image filename inside input/.

    Returns:
        Dictionary with route_b_file, route_a_file (if ready), and route_a_error (if unavailable).
    """
    job = J.find(job_name)
    portrait = find_avatar_image(job, image_name)
    src_audio = _find_preview_audio(job)
    job.work.mkdir(parents=True, exist_ok=True)
    job.review.mkdir(parents=True, exist_ok=True)

    audio_10s = job.work / "avatar_preview_10s.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src_audio), "-t", "10", str(audio_10s)],
        check=True,
        capture_output=True,
    )
    out_b = job.review / "avatar_preview_b.mp4"
    render_lightweight_avatar(portrait, audio_10s, out_b)

    app_cfg = load_app_config()
    sad_status = avatar_environment_status(app_cfg.sadtalker_dir)["sadtalker"]
    route_a_file = ""
    route_a_error = ""
    if sad_status["ready"] and app_cfg.sadtalker_dir is not None:
        try:
            out_a = job.review / "avatar_preview_a.mp4"
            render_sadtalker_avatar(portrait, audio_10s, out_a, app_cfg.sadtalker_dir)
            route_a_file = out_a.name
        except Exception as exc:
            route_a_error = str(exc)
    else:
        route_a_error = "SadTalker 權重尚未備齊或模型載入中"

    return {
        "route_b_file": out_b.name,
        "route_a_file": route_a_file,
        "route_a_error": route_a_error,
    }
