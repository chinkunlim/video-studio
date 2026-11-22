"""Studio HTTP routes for AI planning, voice prewarming, drafting, bilingual subtitles, and avatars."""

from __future__ import annotations

import csv
import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from video_studio.entrypoints.routes.schemas import (
    SAFE_NAME_RE,
    AvatarApplyRequest,
    BilingualRequest,
    PlanRequest,
    ProsodyPreviewRequest,
    ScriptDraftRequest,
    VoiceSamplePrewarmRequest,
)
from video_studio.services import planner, script_drafter
from video_studio.services.common import job as J
from video_studio.services.narrate import narrate as narrate_svc
from video_studio.services.narrate.core import bilingual
from video_studio.services.video import avatar_overlay

logger = logging.getLogger(__name__)
router = APIRouter(tags=["studio"])

_SAMPLE_INFLIGHT: set[str] = set()
_SAMPLE_LOCK = threading.Lock()


def _run_voice_prewarm(voice: str, language: str, engine: str, rate: str) -> None:
    """Synthesize cached 10s voice samples in a background thread and clear inflight flag.

    Args:
        voice: Edge-TTS voice ID or Voicebox profile name.
        language: Language code.
        engine: TTS engine ('edge-tts' or 'voicebox').
        rate: Speech rate string.
    """
    try:
        narrate_svc.ensure_voice_samples(voice, language, engine, rate)
    except Exception as exc:
        logger.warning("Prewarm voice sample failed (%s): %s", voice, exc)
    finally:
        with _SAMPLE_LOCK:
            _SAMPLE_INFLIGHT.discard(voice)


@router.post("/api/jobs/{job_name}/plan")
def start_plan(job_name: str, req: PlanRequest) -> dict[str, Any]:
    """Start a background Antigravity (agy CLI) planning run.

    Args:
        job_name: Target job name.
        req: Planning instruction and target mode.

    Returns:
        Run handle with run_id and initial status.
    """
    return planner.start_agy_plan(
        job_name,
        req.instruction,
        req.mode,
        req.model,
        req.follow_poster_design,
        thread_mode=req.thread_mode,
        history=req.history,
    )


@router.get("/api/jobs/{job_name}/plan/active")
def get_active_plan_route(job_name: str) -> dict[str, Any]:
    """Return the active background agy CLI planning run for a job, if any.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with active flag and run status details.
    """
    return planner.get_active_plan(job_name)


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


@router.get("/api/agy/models")
def get_agy_models() -> dict[str, Any]:
    """List available Antigravity (agy CLI) models.

    Returns:
        Dictionary with models list of {id, label}.
    """
    return {"models": planner.list_agy_models()}


@router.get("/api/voice/samples")
def get_voice_samples(voice: str) -> dict[str, Any]:
    """Check whether pre-cached 10s normal/energetic/calm samples exist for a voice.

    Args:
        voice: Edge-TTS voice ID or Voicebox profile name.

    Returns:
        Dictionary with ready flag and URLs per prosody preset.
    """
    files = narrate_svc.get_cached_voice_samples(voice)
    urls = {k: f"/api/voice/samples/file/{v}" for k, v in files.items()}
    return {"ready": bool(files), "voice": voice, "files": urls}


@router.post("/api/voice/samples/prewarm")
def prewarm_voice_samples(req: VoiceSamplePrewarmRequest) -> dict[str, Any]:
    """Start background pre-caching of 10s normal/energetic/calm samples for a voice.

    Args:
        req: Voice, language, engine, and rate settings.

    Returns:
        Status dictionary with ready flag and cached URLs if already available.
    """
    files = narrate_svc.get_cached_voice_samples(req.voice)
    if files:
        return {
            "ready": True,
            "voice": req.voice,
            "files": {k: f"/api/voice/samples/file/{v}" for k, v in files.items()},
        }
    with _SAMPLE_LOCK:
        if req.voice not in _SAMPLE_INFLIGHT:
            _SAMPLE_INFLIGHT.add(req.voice)
            threading.Thread(
                target=_run_voice_prewarm,
                args=(req.voice, req.language, req.engine, req.rate),
                daemon=True,
            ).start()
    return {"ready": False, "voice": req.voice, "files": {}}


@router.get("/api/voice/samples/file/{filename}")
def get_voice_sample_file(filename: str) -> FileResponse:
    """Serve a cached 10s voice sample WAV from DATA_DIR/cache/voice_samples.

    Args:
        filename: Sample WAV filename.

    Returns:
        FileResponse for in-browser audio playback.
    """
    if not SAFE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = narrate_svc.voice_sample_cache_dir() / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Sample not found")
    return FileResponse(path)


@router.post("/api/jobs/{job_name}/script/draft")
def draft_script_route(job_name: str, req: ScriptDraftRequest) -> dict[str, Any]:
    """Generate a structured script.md draft into needs_review/<job>/script.md via agy CLI or Ollama.

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


@router.post("/api/jobs/{job_name}/subtitles/bilingual")
def generate_bilingual_route(job_name: str, req: BilingualRequest) -> dict[str, Any]:
    """Translate input/script.md into work/<job>/script_bilingual.tsv for dual-language subtitles.

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


@router.get("/api/jobs/{job_name}/subtitles/bilingual")
def get_bilingual_route(job_name: str) -> dict[str, Any]:
    """Return translated bilingual subtitle pairs from work/<job>/script_bilingual.tsv.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with exists flag and list of {index, primary, secondary} rows.
    """
    try:
        tsv_path = J.find(job_name).work / "script_bilingual.tsv"
    except J.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not tsv_path.is_file():
        return {"exists": False, "rows": []}
    with open(tsv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return {"exists": True, "rows": rows}


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
    """Generate 10-second normal/energetic/calm prosody audio previews into needs_review/<job>/.

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
