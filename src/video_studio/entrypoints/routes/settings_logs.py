"""Studio HTTP routes for editable non-secret environment settings and live log tailing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from video_studio.config import env_store
from video_studio.config.settings import load_config
from video_studio.entrypoints.routes.schemas import EnvUpdateRequest

router = APIRouter(tags=["studio"])


@router.get("/api/settings/env")
def get_env_settings() -> dict[str, str]:
    """Return non-secret editable environment settings.

    Returns:
        Dictionary of allowed settings from AppConfig.
    """
    return env_store.read_editable_env(load_config())


@router.put("/api/settings/env")
def update_env_settings(req: EnvUpdateRequest) -> dict[str, Any]:
    """Update allowed non-secret keys in the project .env file.

    Args:
        req: Key-value mapping of allowed settings.

    Returns:
        Confirmation dictionary.

    Raises:
        HTTPException: 400 if any setting contains newline characters.
    """
    try:
        env_store.update_editable_env(req.values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "output": "已更新 .env 全域設定"}


@router.get("/api/logs/tail")
def tail_app_logs(lines: int = 50) -> dict[str, Any]:
    """Return the latest lines from DATA_DIR/logs/app.log for the Web UI live terminal.

    Args:
        lines: Maximum number of trailing lines to return.

    Returns:
        Dictionary with log lines list and log file path.
    """
    log_file = load_config().logs_dir / "app.log"
    if not log_file.is_file():
        return {"lines": [], "path": str(log_file)}
    raw_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    n = max(1, min(200, lines))
    return {"lines": raw_lines[-n:], "path": str(log_file)}
