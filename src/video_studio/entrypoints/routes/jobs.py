"""Studio HTTP routes for job detail, editing, uploads, review snapshots, and media outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from video_studio.entrypoints.routes.schemas import (
    SAFE_NAME_RE,
    JobConfigUpdate,
    SnapshotCreateRequest,
    TextContentUpdate,
    serialize_job_toml,
)
from video_studio.services import review_history
from video_studio.services.common import job as J
from video_studio.services.narrate.core import script as script_mod
from video_studio.services.video import release as release_mod

router = APIRouter(tags=["studio"])


def _find_job_or_404(job_name: str) -> J.Job:
    """Resolve a job workspace or translate JobError to HTTP 404.

    Args:
        job_name: Target job name.

    Returns:
        Loaded Job instance.

    Raises:
        HTTPException: 404 when the job does not exist.
    """
    try:
        return J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _list_output_versions(job: J.Job) -> tuple[list[str], str | None, list[str]]:
    """Collect sorted output version folders and latest version files.

    Args:
        job: Loaded Job instance.

    Returns:
        Tuple of (descending version names, latest version name, latest file list).
    """
    if not job.output.exists():
        return [], None, []
    ver_names = [
        p.name for p in job.output.iterdir() if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
    ]
    versions = sorted(ver_names, key=lambda n: int(n[1:]), reverse=True)
    latest = job.latest_output()
    out_files = sorted(p.name for p in latest.iterdir() if p.is_file()) if latest else []
    return versions, (latest.name if latest else None), out_files


@router.get("/api/jobs/{job_name}/detail")
def get_job_detail(job_name: str) -> dict[str, Any]:
    """Return full job.toml, script.md, brief.md, input/review/output files.

    Args:
        job_name: Target job name.

    Returns:
        Structured job detail dictionary for the Web UI.
    """
    job = _find_job_or_404(job_name)
    script_text = job.script.read_text(encoding="utf-8") if job.script and job.script.exists() else ""
    brief_path = job.input / "brief.md"
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    in_files = sorted(p.name for p in job.input.iterdir() if p.is_file()) if job.input.exists() else []
    rev_files = sorted(p.name for p in job.review.iterdir() if p.is_file()) if job.review.exists() else []
    versions, latest_version, out_files = _list_output_versions(job)
    return {
        "name": job.name,
        "type": job.type,
        "title": job.title,
        "config": job.cfg,
        "script": script_text,
        "brief": brief_text,
        "input_files": in_files,
        "review_files": rev_files,
        "output_versions": versions,
        "latest_version": latest_version,
        "latest_files": out_files,
        "published_release": release_mod.get_published_release(job.name),
    }


@router.put("/api/jobs/{job_name}/config")
def update_job_config(job_name: str, req: JobConfigUpdate) -> dict[str, Any]:
    """Persist Web UI job configuration changes back to job.toml.

    Args:
        job_name: Target job name.
        req: Updated configuration fields.

    Returns:
        Confirmation dictionary.
    """
    job = _find_job_or_404(job_name)
    content = serialize_job_toml(job.type, req)
    job.config_path.write_text(content, encoding="utf-8")
    return {"ok": True, "output": f"已儲存 {job.name}/job.toml"}


@router.put("/api/jobs/{job_name}/script")
def update_job_script(job_name: str, req: TextContentUpdate) -> dict[str, Any]:
    """Save or format input/script.md from the Web UI editor.

    Args:
        job_name: Target job name.
        req: Script content and auto_format flag.

    Returns:
        Saved content and status message.
    """
    job = _find_job_or_404(job_name)
    text = script_mod.split_sentences(req.content) if req.auto_format else req.content
    target = job.script or (job.input / "script.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    orig = job.review / "script.original.md"
    if not orig.exists() and req.content.strip():
        job.review.mkdir(parents=True, exist_ok=True)
        orig.write_text(target.read_text(encoding="utf-8") if target.is_file() else text, encoding="utf-8")
    target.write_text(text, encoding="utf-8")
    return {"ok": True, "content": text, "output": f"已儲存 {target.name}"}


@router.put("/api/jobs/{job_name}/brief")
def update_job_brief(job_name: str, req: TextContentUpdate) -> dict[str, Any]:
    """Save input/brief.md planning instructions from the Web UI.

    Args:
        job_name: Target job name.
        req: Brief markdown text.

    Returns:
        Confirmation dictionary.
    """
    job = _find_job_or_404(job_name)
    job.input.mkdir(parents=True, exist_ok=True)
    (job.input / "brief.md").write_text(req.content, encoding="utf-8")
    return {"ok": True, "output": f"已儲存 {job.name}/input/brief.md"}


@router.post("/api/jobs/{job_name}/upload")
async def upload_job_asset(job_name: str, file: Annotated[UploadFile, File(...)]) -> dict[str, Any]:
    """Upload a material file (.pptx, .pdf, .png, .mp4, .wav) into input/.

    Args:
        job_name: Target job name.
        file: Uploaded multipart file.

    Returns:
        Saved filename confirmation.
    """
    job = _find_job_or_404(job_name)
    fname = Path(file.filename or "upload.bin").name
    if not SAFE_NAME_RE.fullmatch(fname):
        raise HTTPException(status_code=400, detail="檔名僅允許英數字、點、底線與連字號")
    dest = job.input / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    return {"ok": True, "filename": fname, "output": f"已上傳至 input/{fname}"}


@router.get("/api/jobs/{job_name}/original-script")
def get_original_script(job_name: str) -> dict[str, Any]:
    """Return the preserved immutable original script draft (needs_review/<job>/script.original.md).

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with exists flag and content string.
    """
    orig = _find_job_or_404(job_name).review / "script.original.md"
    if not orig.is_file():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": orig.read_text(encoding="utf-8")}


@router.get("/api/jobs/{job_name}/review-script")
def get_review_script(job_name: str) -> dict[str, Any]:
    """Return needs_review/<job>/script.md content if present for editing/approval.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with exists flag and content string.
    """
    path = _find_job_or_404(job_name).review / "script.md"
    if not path.is_file():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": path.read_text(encoding="utf-8")}


@router.get("/api/jobs/{job_name}/review/snapshots")
def list_review_snapshots(job_name: str) -> dict[str, Any]:
    """List saved needs_review/<job>/ draft snapshots for rollback.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with snapshots list ordered newest first.
    """
    try:
        return {"snapshots": review_history.list_snapshots(job_name)}
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/jobs/{job_name}/review/snapshots")
def create_review_snapshot(job_name: str, req: SnapshotCreateRequest) -> dict[str, Any]:
    """Manually save a snapshot of current needs_review/<job>/ drafts before editing.

    Args:
        job_name: Target job name.
        req: Snapshot note payload.

    Returns:
        Created snapshot metadata or status message.
    """
    try:
        entry = review_history.create_snapshot(job_name, note=req.note)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not entry:
        raise HTTPException(status_code=400, detail="needs_review/ 目前沒有可備份的草稿檔案")
    return {"ok": True, "snapshot": entry, "output": f"已儲存草稿快照 {entry['id']}"}


@router.post("/api/jobs/{job_name}/review/snapshots/{snap_id}/restore")
def restore_review_snapshot(job_name: str, snap_id: str) -> dict[str, Any]:
    """Restore a saved snapshot back into needs_review/<job>/ after backing up current drafts.

    Args:
        job_name: Target job name.
        snap_id: Snapshot identifier to restore.

    Returns:
        Restore confirmation dictionary.
    """
    try:
        return review_history.restore_snapshot(job_name, snap_id)
    except (FileNotFoundError, J.JobError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/jobs/{job_name}/review/{filename}")
def get_review_file(job_name: str, filename: str) -> FileResponse:
    """Serve a file from needs_review/<job>/ for browser preview.

    Args:
        job_name: Target job name.
        filename: File inside needs_review/<job>/.

    Returns:
        FileResponse for previewing HTML or preview images.
    """
    if not SAFE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = _find_job_or_404(job_name).review / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@router.get("/api/jobs/{job_name}/output/{version}/{filename}")
def get_output_file(job_name: str, version: str, filename: str) -> FileResponse:
    """Serve a rendered output artifact (MP4, WAV, contact sheet) for playback.

    Args:
        job_name: Target job name.
        version: Output version folder (e.g. v1).
        filename: File inside output/<job>/<version>/.

    Returns:
        FileResponse for in-browser playback or inspection.
    """
    if not SAFE_NAME_RE.fullmatch(version) or not SAFE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid path")
    path = _find_job_or_404(job_name).output / version / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
