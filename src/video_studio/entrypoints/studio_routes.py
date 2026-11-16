"""Web Studio HTTP routes: job config/script/brief editors, uploads, media preview, and agy planner."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from video_studio.config.settings import PROJECT_ROOT, load_config
from video_studio.services import planner
from video_studio.services.common import job as J
from video_studio.services.narrate.core import script as script_mod

logger = logging.getLogger(__name__)
router = APIRouter(tags=["studio"])

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ALLOWED_ENV_KEYS = ("VOICEBOX_URL", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "LOG_LEVEL")


class JobConfigUpdate(BaseModel):
    """Editable fields of job.toml exposed in the Web UI."""

    title: str = Field(default="", description="Display title")
    visual_mode: str = Field(default="auto", description="auto | poster | pptx-export | html | none")
    voice_engine: str = Field(default="voicebox", description="voicebox | edge-tts")
    voice_profile: str = Field(default="My Voice", description="Voicebox profile name")
    edge_voice: str = Field(default="zh-TW-HsiaoChenNeural", description="edge-tts voice name")
    edge_rate: str = Field(default="+0%", description="edge-tts speaking rate")
    subtitles_formats: list[str] = Field(default_factory=lambda: ["youtube", "powerpoint", "vlc"])
    burn_in: bool = Field(default=True, description="Burn subtitles into video_subtitled.mp4")
    loudness: float = Field(default=-16.0, description="Target LUFS (-30 to -8)")
    backup_dir: str = Field(default="", description="Optional backup output directory")
    inputs: dict[str, str] = Field(default_factory=dict, description="Input filename mappings")


class TextContentUpdate(BaseModel):
    """Request payload for saving script.md or brief.md."""

    content: str = Field(description="Markdown file content")
    auto_format: bool = Field(default=False, description="Auto-split sentences when saving script.md")


class PlanRequest(BaseModel):
    """Request payload for starting an Antigravity agy CLI planning run."""

    instruction: str = Field(default="", description="User planning instruction or follow-up")
    mode: str = Field(default="html", description="html | poster")


class EnvUpdateRequest(BaseModel):
    """Editable non-secret environment settings."""

    values: dict[str, str] = Field(description="Allowed .env key/value pairs")


def _toml_str(val: str) -> str:
    """Escape a string as a TOML basic string.

    Args:
        val: Raw string value.

    Returns:
        Quoted and escaped TOML string.
    """
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _serialize_job_toml(job_type: str, req: JobConfigUpdate) -> str:
    """Render a clean job.toml string from structured web form fields.

    Args:
        job_type: Fixed job type ('extract', 'dub', 'generate').
        req: Validated JobConfigUpdate payload.

    Returns:
        Formatted job.toml text.
    """
    fmts = ", ".join(_toml_str(f) for f in req.subtitles_formats)
    lines = [
        "[job]",
        f"type = {_toml_str(job_type)}",
        f"title = {_toml_str(req.title)}",
        "",
        "[inputs]",
        *(f"{k} = {_toml_str(v)}" for k, v in req.inputs.items()),
        "",
        "[visual]",
        f"mode = {_toml_str(req.visual_mode)}",
        "",
        "[voice]",
        f"engine = {_toml_str(req.voice_engine)}",
        f"profile = {_toml_str(req.voice_profile)}",
        f"edge_voice = {_toml_str(req.edge_voice)}",
        f"edge_rate = {_toml_str(req.edge_rate)}",
        "",
        "[subtitles]",
        f"formats = [{fmts}]",
        f"burn_in = {'true' if req.burn_in else 'false'}",
        "",
        "[output]",
        f"loudness = {req.loudness}",
        f"backup_dir = {_toml_str(req.backup_dir)}",
        "",
    ]
    return "\n".join(lines)


@router.get("/api/jobs/{job_name}/detail")
def get_job_detail(job_name: str) -> dict[str, Any]:
    """Return full job.toml, script.md, brief.md, input/review/output files.

    Args:
        job_name: Target job name.

    Returns:
        Structured job detail dictionary for the Web UI.
    """
    job = J.find(job_name)
    script_text = job.script.read_text(encoding="utf-8") if job.script and job.script.exists() else ""
    brief_path = job.input / "brief.md"
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    in_files = sorted(p.name for p in job.input.iterdir() if p.is_file()) if job.input.exists() else []
    rev_files = sorted(p.name for p in job.review.iterdir() if p.is_file()) if job.review.exists() else []
    versions = (
        sorted((p.name for p in job.output.iterdir() if p.is_dir()), reverse=True)
        if job.output.exists()
        else []
    )
    latest = job.latest_output()
    out_files = sorted(p.name for p in latest.iterdir() if p.is_file()) if latest else []
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
        "latest_version": latest.name if latest else None,
        "latest_files": out_files,
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
    job = J.find(job_name)
    content = _serialize_job_toml(job.type, req)
    (job.dir / "job.toml").write_text(content, encoding="utf-8")
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
    job = J.find(job_name)
    text = script_mod.split_sentences(req.content) if req.auto_format else req.content
    target = job.script or (job.input / "script.md")
    target.parent.mkdir(parents=True, exist_ok=True)
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
    job = J.find(job_name)
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
    job = J.find(job_name)
    fname = Path(file.filename or "upload.bin").name
    if not SAFE_NAME_RE.fullmatch(fname):
        raise HTTPException(status_code=400, detail="檔名僅允許英數字、點、底線與連字號")
    dest = job.input / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    return {"ok": True, "filename": fname, "output": f"已上傳至 input/{fname}"}


@router.post("/api/jobs/{job_name}/plan")
def start_plan(job_name: str, req: PlanRequest) -> dict[str, Any]:
    """Start a background Antigravity (agy CLI) planning run.

    Args:
        job_name: Target job name.
        req: Planning instruction and target mode.

    Returns:
        Run handle with run_id and initial status.
    """
    return planner.start_agy_plan(job_name, req.instruction, req.mode)


@router.get("/api/plan/{run_id}")
def poll_plan(run_id: str) -> dict[str, Any]:
    """Poll status and streamed output of a background agy CLI planning run.

    Args:
        run_id: Planning run identifier.

    Returns:
        Current run status and output text.
    """
    try:
        return planner.get_plan_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/jobs/{job_name}/review/{filename}")
def get_review_file(job_name: str, filename: str) -> FileResponse:
    """Serve a file from review/ for browser preview.

    Args:
        job_name: Target job name.
        filename: File inside review/.

    Returns:
        FileResponse for previewing HTML or preview images.
    """
    if not SAFE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = J.find(job_name).review / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@router.get("/api/jobs/{job_name}/output/{version}/{filename}")
def get_output_file(job_name: str, version: str, filename: str) -> FileResponse:
    """Serve a rendered output artifact (MP4, WAV, contact sheet) for playback.

    Args:
        job_name: Target job name.
        version: Output version folder (e.g. v1).
        filename: File inside output/<version>/.

    Returns:
        FileResponse for in-browser playback or inspection.
    """
    if not SAFE_NAME_RE.fullmatch(version) or not SAFE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid path")
    path = J.find(job_name).output / version / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@router.get("/api/settings/env")
def get_env_settings() -> dict[str, str]:
    """Return non-secret editable environment settings.

    Returns:
        Dictionary of allowed settings from AppConfig.
    """
    cfg = load_config()
    return {
        "VOICEBOX_URL": cfg.voicebox_url,
        "OLLAMA_BASE_URL": cfg.ollama_base_url,
        "OLLAMA_MODEL": "qwen2.5",
        "LOG_LEVEL": cfg.log_level,
    }


@router.put("/api/settings/env")
def update_env_settings(req: EnvUpdateRequest) -> dict[str, Any]:
    """Update allowed non-secret keys in the project .env file.

    Args:
        req: Key-value mapping of allowed settings.

    Returns:
        Confirmation dictionary.
    """
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updates = {k: v for k, v in req.values.items() if k in ALLOWED_ENV_KEYS}
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = line.partition("=")[0].strip() if "=" in line and not line.strip().startswith("#") else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"ok": True, "output": "已更新 .env 全域設定"}
