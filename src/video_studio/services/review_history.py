"""草稿版本快照與退回服務：為每個工作的 review/ 目錄提供類似 Git 的自動備份與一鍵還原。"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from video_studio.services.common import job as J

logger = logging.getLogger(__name__)

TRACKED_FILES = ("index.html", "scenes.toml", "script.md")


def _history_dir(job: J.Job) -> Path:
    """Return the per-job review_history directory inside DATA_DIR.

    Args:
        job: Loaded Job instance.

    Returns:
        Path to the job's review_history directory.
    """
    return job.dir / "review_history"


def _meta_path(job: J.Job) -> Path:
    """Return path to the snapshot index JSON file.

    Args:
        job: Loaded Job instance.

    Returns:
        Path to history.json.
    """
    return _history_dir(job) / "history.json"


def _load_index(job: J.Job) -> list[dict[str, Any]]:
    """Load snapshot metadata list from history.json.

    Args:
        job: Loaded Job instance.

    Returns:
        List of snapshot metadata dictionaries, oldest to newest.
    """
    mp = _meta_path(job)
    if not mp.is_file():
        return []
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("Failed to read %s: %s", mp, exc)
        return []


def _save_index(job: J.Job, items: list[dict[str, Any]]) -> None:
    """Persist snapshot metadata list to history.json.

    Args:
        job: Loaded Job instance.
        items: List of snapshot metadata dictionaries.
    """
    hdir = _history_dir(job)
    hdir.mkdir(parents=True, exist_ok=True)
    _meta_path(job).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def create_snapshot(job_name: str, note: str = "手動備份") -> dict[str, Any] | None:
    """Snapshot tracked files in review/ into review_history/<snap_id>/.

    Args:
        job_name: Target job name.
        note: Human-readable reason or commit-style message for the snapshot.

    Returns:
        Created snapshot metadata dict, or None if review/ has no tracked files.
    """
    job = J.find(job_name)
    existing = [f for f in TRACKED_FILES if (job.review / f).is_file()]
    if not existing:
        return None
    now = datetime.now()
    items = _load_index(job)
    snap_id = f"v{len(items) + 1:03d}_{now.strftime('%Y%m%d_%H%M%S')}"
    snap_dir = _history_dir(job) / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    for fname in existing:
        shutil.copy2(job.review / fname, snap_dir / fname)
    entry: dict[str, Any] = {
        "id": snap_id,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "note": note.strip() or "手動備份",
        "files": existing,
    }
    items.append(entry)
    _save_index(job, items)
    logger.info("已建立草稿快照 %s/%s (%s): %s", job.name, snap_id, entry["note"], ", ".join(existing))
    return entry


def list_snapshots(job_name: str) -> list[dict[str, Any]]:
    """List saved review/ snapshots for a job, newest first.

    Args:
        job_name: Target job name.

    Returns:
        List of snapshot metadata dicts ordered newest first.
    """
    job = J.find(job_name)
    return list(reversed(_load_index(job)))


def restore_snapshot(job_name: str, snap_id: str) -> dict[str, Any]:
    """Restore a saved snapshot back into review/, backing up current state first.

    Args:
        job_name: Target job name.
        snap_id: Snapshot identifier to restore.

    Returns:
        Dictionary with restored snapshot metadata and optional pre-restore backup id.

    Raises:
        FileNotFoundError: When snap_id does not exist.
    """
    job = J.find(job_name)
    items = _load_index(job)
    match = next((it for it in items if it.get("id") == snap_id), None)
    snap_dir = _history_dir(job) / snap_id
    if not match or not snap_dir.is_dir():
        raise FileNotFoundError(f"找不到草稿快照：{snap_id}")

    pre_backup = create_snapshot(job_name, note=f"退回 {snap_id} 前自動備份")
    job.review.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    for fname in TRACKED_FILES:
        src = snap_dir / fname
        if src.is_file():
            shutil.copy2(src, job.review / fname)
            restored.append(fname)
    logger.info("已將 %s/review 退回至快照 %s (%s)", job.name, snap_id, ", ".join(restored))
    return {
        "ok": True,
        "restored_id": snap_id,
        "restored_files": restored,
        "backup_id": pre_backup["id"] if pre_backup else None,
        "output": f"已退回草稿版本 {snap_id}（{', '.join(restored)}）",
    }
