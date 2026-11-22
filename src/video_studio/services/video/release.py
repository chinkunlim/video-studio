"""定稿發布服務：將選定的版本成品硬連結至 output/<job>/releases/<vN>/，並自動退回舊定稿。"""

from __future__ import annotations

import errno
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from video_studio.services.common import job as J

logger = logging.getLogger(__name__)

SUBTITLE_DELIVERABLES: tuple[str, ...] = ("subtitles_youtube.srt", "subtitles_vlc.srt")


def _resolve_version_dir(job: J.Job, version: str | None) -> Path:
    """Resolve the target rendered version folder inside ``job.output``.

    Args:
        job: Target Job instance.
        version: Optional version name (e.g. ``v2``); defaults to latest ``vN``.

    Returns:
        Path to the resolved version directory.

    Raises:
        FileNotFoundError: If the requested or latest version directory does not exist.
    """
    if version:
        v = job.output / version
        if not v.is_dir():
            raise FileNotFoundError(f"找不到版本資料夾：{v}")
        return v
    latest = job.latest_output()
    if latest is None:
        raise FileNotFoundError(f"{job.output} 裡還沒有任何渲染版本（v1, v2, ...）。")
    return latest


def _collect_deliverables(version_dir: Path) -> list[Path]:
    """Collect final video (.mp4) and subtitle deliverables from a version directory.

    Args:
        version_dir: Rendered version folder (e.g. ``output/<job>/v2``).

    Returns:
        Sorted list of deliverable file paths.

    Raises:
        FileNotFoundError: If no ``.mp4`` video files exist in ``version_dir``.
    """
    videos = sorted(p for p in version_dir.glob("*.mp4") if p.is_file())
    if not videos:
        raise FileNotFoundError(f"{version_dir} 內沒有可發布的 .mp4 影片檔，請先完成渲染。")
    subs = [version_dir / name for name in SUBTITLE_DELIVERABLES if (version_dir / name).is_file()]
    return [*videos, *subs]


def _link_or_copy(src: Path, dst: Path) -> str:
    """Create a hardlink at ``dst`` pointing to ``src``, falling back to copy across filesystems.

    Args:
        src: Source deliverable file path.
        dst: Destination path inside ``releases/<vN>/``.

    Returns:
        ``"hardlink"`` or ``"copy"`` indicating how the file was placed.
    """
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EACCES):
            raise
        shutil.copy2(src, dst)
        return "copy"


def _clear_previous_releases(releases_dir: Path) -> list[str]:
    """Remove any previously published version folders from ``releases_dir``.

    Args:
        releases_dir: Job's ``releases/`` directory.

    Returns:
        List of previously published version names that were demoted.
    """
    if not releases_dir.exists():
        return []
    demoted: list[str] = []
    for entry in sorted(releases_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
            demoted.append(entry.name)
        elif entry.is_file() or entry.is_symlink():
            entry.unlink()
            demoted.append(entry.name)
    return demoted


def get_published_release(job_name: str, ws: Path | None = None) -> dict[str, Any] | None:
    """Return metadata for the currently published release of a job, if any.

    Args:
        job_name: Target job name.
        ws: Optional data root override.

    Returns:
        Dict with ``version``, ``release_dir``, and ``files``, or ``None`` if unpublished.
    """
    job = J.find(job_name, ws)
    if not job.releases.exists():
        return None
    dirs = sorted(
        (d for d in job.releases.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda d: d.name,
        reverse=True,
    )
    if not dirs:
        return None
    active = dirs[0]
    files = sorted(p.name for p in active.iterdir() if p.is_file())
    return {
        "version": active.name,
        "release_dir": str(active),
        "files": files,
    }


def publish_release(
    job_name: str,
    version: str | None = None,
    ws: Path | None = None,
) -> dict[str, Any]:
    """Publish a rendered version as the single active release in ``output/<job>/releases/<vN>/``.

    Previously published versions under ``releases/`` are unlinked (demoted back to
    unpublished status in ``output/<job>/<old_vN>/`` without deleting original files).

    Args:
        job_name: Target job name.
        version: Version name (e.g. ``v2``); defaults to latest rendered version.
        ws: Optional data root override.

    Returns:
        Dictionary with ``version``, ``release_dir``, ``demoted``, ``files``, ``mode``, and ``message``.
    """
    job = J.find(job_name, ws)
    v = _resolve_version_dir(job, version)
    deliverables = _collect_deliverables(v)
    job.releases.mkdir(parents=True, exist_ok=True)
    demoted = _clear_previous_releases(job.releases)
    target_dir = job.releases / v.name
    target_dir.mkdir(parents=True, exist_ok=True)

    modes = {_link_or_copy(src, target_dir / src.name) for src in deliverables}
    placed = [src.name for src in deliverables]
    mode_label = "hardlink" if modes == {"hardlink"} else "copy"
    logger.info(
        "已發布 %s 定稿 %s 至 %s（方式：%s，退回舊版：%s）",
        job.name,
        v.name,
        target_dir,
        mode_label,
        demoted or "無",
    )
    demoted_msg = f"（已將舊定稿 {', '.join(demoted)} 退回未發布狀態）" if demoted else ""
    msg = f"已發布定稿 {v.name} 至 {target_dir}{demoted_msg}\n檔案：{', '.join(placed)}"
    return {
        "version": v.name,
        "release_dir": str(target_dir),
        "demoted": demoted,
        "files": placed,
        "mode": mode_label,
        "message": msg,
    }
