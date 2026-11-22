"""Web Studio HTTP router aggregator (re-exports modular sub-routers and schemas)."""

from __future__ import annotations

from fastapi import APIRouter

from video_studio.config.env_store import ALLOWED_ENV_KEYS
from video_studio.entrypoints.routes import ai_media, jobs, settings_logs
from video_studio.entrypoints.routes.schemas import (
    SAFE_NAME_RE,
    AvatarApplyRequest,
    BilingualRequest,
    EnvUpdateRequest,
    JobConfigUpdate,
    PlanRequest,
    ProsodyPreviewRequest,
    ScriptDraftRequest,
    SnapshotCreateRequest,
    TextContentUpdate,
    VoiceSamplePrewarmRequest,
)

router = APIRouter(tags=["studio"])
router.include_router(jobs.router)
router.include_router(ai_media.router)
router.include_router(settings_logs.router)

__all__ = [
    "ALLOWED_ENV_KEYS",
    "AvatarApplyRequest",
    "BilingualRequest",
    "EnvUpdateRequest",
    "JobConfigUpdate",
    "PlanRequest",
    "ProsodyPreviewRequest",
    "SAFE_NAME_RE",
    "ScriptDraftRequest",
    "SnapshotCreateRequest",
    "TextContentUpdate",
    "VoiceSamplePrewarmRequest",
    "router",
]
