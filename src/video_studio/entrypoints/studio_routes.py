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
from video_studio.services import planner, script_drafter
from video_studio.services.common import job as J
from video_studio.services.narrate import narrate as narrate_svc
from video_studio.services.narrate.core import bilingual
from video_studio.services.narrate.core import script as script_mod
from video_studio.services.video import avatar_overlay

logger = logging.getLogger(__name__)
router = APIRouter(tags=["studio"])

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ALLOWED_ENV_KEYS = ("VOICEBOX_URL", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "SADTALKER_DIR", "LOG_LEVEL")


class JobConfigUpdate(BaseModel):
    """Editable fields of job.toml exposed in the Web UI."""

    title: str = Field(default="", description="Display title")
    visual_mode: str = Field(default="auto", description="auto | poster | pptx-export | html | none")
    voice_engine: str = Field(default="voicebox", description="voicebox | edge-tts")
    voice_language: str = Field(default="zh", description="Voice/TTS language code (zh, en, ja, etc.)")
    voice_profile: str = Field(default="My Voice", description="Voicebox profile name")
    edge_voice: str = Field(default="zh-TW-HsiaoChenNeural", description="edge-tts voice name")
    edge_rate: str = Field(default="+0%", description="edge-tts speaking rate")
    prosody_preset: str = Field(default="normal", description="normal | energetic | calm")
    whisper_model: str = Field(default="small", description="Whisper model (tiny, base, small, medium)")
    opencc_mode: str = Field(default="s2tw", description="OpenCC conversion (s2tw, s2t, none)")
    subtitles_formats: list[str] = Field(default_factory=lambda: ["youtube", "powerpoint", "vlc"])
    burn_in: bool = Field(default=True, description="Burn subtitles into video_subtitled.mp4")
    bilingual_subtitles: bool = Field(default=False, description="Enable dual-language subtitles")
    subtitle_secondary_lang: str = Field(default="zh-TW", description="Secondary subtitle language")
    subtitle_font_size: int = Field(default=22, description="Burn-in subtitle font size")
    avatar_engine: str = Field(default="none", description="none | lightweight | sadtalker")
    avatar_image: str = Field(default="", description="Portrait image filename inside input/")
    avatar_position: str = Field(default="bottom-right", description="Avatar PiP corner position")
    fps: int = Field(default=30, description="Output video FPS")
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
    model: str = Field(default="", description="Optional agy CLI model ID")
    follow_poster_design: bool = Field(default=True, description="Preserve uploaded poster design")


class EnvUpdateRequest(BaseModel):
    """Editable non-secret environment settings."""

    values: dict[str, str] = Field(description="Allowed .env key/value pairs")


class ScriptDraftRequest(BaseModel):
    """Request payload for AI script generation into review/script.md."""

    instruction: str = Field(default="", description="Topic or prompt for the script")
    language: str = Field(default="zh", description="Spoken language code")
    duration_sec: int = Field(default=90, description="Target duration in seconds")
    model: str = Field(default="", description="Optional agy CLI model ID")


class BilingualRequest(BaseModel):
    """Request payload for translating script.md into bilingual subtitles."""

    target_lang: str = Field(default="zh-TW", description="Target secondary subtitle language")
    model: str = Field(default="", description="Optional agy CLI model ID")


class AvatarApplyRequest(BaseModel):
    """Request payload for compositing an avatar presenter onto the rendered video."""

    engine: str = Field(default="lightweight", description="lightweight | sadtalker")
    position: str = Field(default="bottom-right", description="Corner placement")
    image_name: str = Field(default="", description="Optional portrait image filename inside input/")


class ProsodyPreviewRequest(BaseModel):
    """Request payload for generating 10-second prosody A/B/C previews."""

    sample_text: str = Field(default="", description="Optional sample text with [loud]/[fast] tags")


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
        f"language = {_toml_str(req.voice_language)}",
        f"profile = {_toml_str(req.voice_profile)}",
        f"edge_voice = {_toml_str(req.edge_voice)}",
        f"edge_rate = {_toml_str(req.edge_rate)}",
        f"prosody_preset = {_toml_str(req.prosody_preset)}",
        "",
        "[whisper]",
        f"model = {_toml_str(req.whisper_model)}",
        f"opencc_mode = {_toml_str(req.opencc_mode)}",
        "",
        "[subtitles]",
        f"formats = [{fmts}]",
        f"burn_in = {'true' if req.burn_in else 'false'}",
        f"bilingual = {'true' if req.bilingual_subtitles else 'false'}",
        f"secondary_lang = {_toml_str(req.subtitle_secondary_lang)}",
        f"font_size = {req.subtitle_font_size}",
        "",
        "[avatar]",
        f"engine = {_toml_str(req.avatar_engine)}",
        f"image = {_toml_str(req.avatar_image)}",
        f"position = {_toml_str(req.avatar_position)}",
        "",
        "[output]",
        f"fps = {req.fps}",
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
    try:
        job = J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        job = J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        job = J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        job = J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        job = J.find(job_name)
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    return planner.start_agy_plan(job_name, req.instruction, req.mode, req.model, req.follow_poster_design)


@router.get("/api/agy/models")
def get_agy_models() -> dict[str, Any]:
    """List available Antigravity (agy CLI) models.

    Returns:
        Dictionary with models list of {id, label}.
    """
    return {"models": planner.list_agy_models()}


@router.get("/api/jobs/{job_name}/original-script")
def get_original_script(job_name: str) -> dict[str, Any]:
    """Return the preserved immutable original script draft (review/script.original.md).

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with exists flag and content string.
    """
    orig = J.find(job_name).review / "script.original.md"
    if not orig.is_file():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": orig.read_text(encoding="utf-8")}


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
        "OLLAMA_MODEL": cfg.ollama_model,
        "SADTALKER_DIR": str(cfg.sadtalker_dir or ""),
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


@router.post("/api/jobs/{job_name}/script/draft")
def draft_script_route(job_name: str, req: ScriptDraftRequest) -> dict[str, Any]:
    """Generate a structured script.md draft into review/script.md via local Ollama.

    Args:
        job_name: Target job name.
        req: ScriptDraftRequest payload.

    Returns:
        Path and generated script content.
    """
    try:
        path, content = script_drafter.draft_script_to_review(
            job_name=job_name,
            instruction=req.instruction,
            language=req.language,
            duration_sec=req.duration_sec,
            model=req.model or None,
        )
        return {"ok": True, "path": str(path), "content": content, "output": f"已生成講稿草稿至 {path.name}"}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/jobs/{job_name}/review-script")
def get_review_script(job_name: str) -> dict[str, Any]:
    """Return review/script.md content if present for editing/approval.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with exists flag and content string.
    """
    path = J.find(job_name).review / "script.md"
    if not path.is_file():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": path.read_text(encoding="utf-8")}


@router.post("/api/jobs/{job_name}/subtitles/bilingual")
def generate_bilingual_route(job_name: str, req: BilingualRequest) -> dict[str, Any]:
    """Translate input/script.md into work/script_bilingual.tsv for dual-language subtitles.

    Args:
        job_name: Target job name.
        req: BilingualRequest specifying target secondary language.

    Returns:
        Summary dictionary with TSV path and line count.
    """
    try:
        tsv_path, count = bilingual.translate_job_script_bilingual(job_name, req.target_lang, req.model)
        return {"ok": True, "path": str(tsv_path), "count": count, "output": f"已完成 {count} 句雙語字幕翻譯"}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/avatar/status")
def get_avatar_status_route() -> dict[str, Any]:
    """Return availability status of Route B (lightweight) and Route A (SadTalker).

    Returns:
        Engine readiness dictionary.
    """
    return avatar_overlay.get_avatar_status()


@router.post("/api/jobs/{job_name}/video/avatar")
def apply_avatar_route(job_name: str, req: AvatarApplyRequest) -> dict[str, Any]:
    """Generate and overlay an Avatar presenter onto the latest rendered job video.

    Args:
        job_name: Target job name.
        req: AvatarApplyRequest specifying engine, corner position, and image name.

    Returns:
        Result dictionary with generated clip and composited video paths.
    """
    try:
        res = avatar_overlay.apply_avatar_to_job(
            job_name=job_name,
            engine=req.engine,
            position=req.position,
            image_name=req.image_name,
        )
        return {
            "ok": True,
            "engine": res.engine,
            "avatar_video": str(res.avatar_video),
            "composited_video": str(res.composited_video or ""),
            "output": f"已完成 {res.engine} Avatar 合成：{res.composited_video}",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/jobs/{job_name}/narrate/prosody-preview")
def preview_prosody_route(job_name: str, req: ProsodyPreviewRequest) -> dict[str, Any]:
    """Generate 10-second normal/energetic/calm prosody audio previews into review/.

    Args:
        job_name: Target job name.
        req: ProsodyPreviewRequest with optional sample text.

    Returns:
        Dictionary mapping preset names to review audio URLs.
    """
    try:
        files = narrate_svc.preview_prosody_10s(J.find(job_name), req.sample_text)
        return {"ok": True, "files": files, "output": "已產生 10 秒韻律風格試聽（標準 / 活力 / 沉穩）"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/jobs/{job_name}/video/avatar-preview")
def preview_avatar_ab_route(job_name: str, req: AvatarApplyRequest) -> dict[str, Any]:
    """Generate 10-second Route B and Route A avatar previews for side-by-side comparison.

    Args:
        job_name: Target job name.
        req: AvatarApplyRequest specifying optional image filename.

    Returns:
        Dictionary with route_b_file, route_a_file, and route_a_error.
    """
    try:
        res = avatar_overlay.preview_avatar_ab_10s(job_name, req.image_name)
        return {"ok": True, **res, "output": "已產生 10 秒 Avatar 路線 A/B 對比預覽"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
