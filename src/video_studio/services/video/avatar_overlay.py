"""Service for generating and compositing Avatar presenter overlays onto rendered videos."""

from __future__ import annotations

import logging
from pathlib import Path

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.video.engine.avatar_engine import (
    AvatarResult,
    avatar_environment_status,
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
    avatar_clip = job.work / f"avatar_{engine}.mp4"
    if engine == "sadtalker":
        assert app_cfg.sadtalker_dir is not None
        render_sadtalker_avatar(portrait, audio_path, avatar_clip, app_cfg.sadtalker_dir)
    else:
        render_lightweight_avatar(portrait, audio_path, avatar_clip)

    composited = out_v / "video_avatar.mp4"
    overlay_avatar_pip(main_video, avatar_clip, composited, position=position)
    # Replace video.mp4 and re-burn subtitles if video_subtitled.mp4 exists
    composited.replace(main_video)
    ass_path = out_v / "subtitles_vlc.ass"
    if ass_path.is_file():
        burn_subtitles(
            main_video,
            ass_path,
            out_v / "video_subtitled.mp4",
            SubtitleBurnOptions(cfg=job.cfg, work=job.work),
        )
    logger.info("Applied %s avatar overlay to %s", engine, main_video)
    return AvatarResult(engine=engine, avatar_video=avatar_clip, composited_video=main_video)
