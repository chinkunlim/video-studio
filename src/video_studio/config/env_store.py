"""Helpers for reading and safely updating editable non-secret .env settings."""

from __future__ import annotations

from pathlib import Path

from video_studio.config.settings import PROJECT_ROOT, AppConfig

ALLOWED_ENV_KEYS = (
    "VOICEBOX_URL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "SADTALKER_DIR",
    "LOG_LEVEL",
)


def read_editable_env(cfg: AppConfig) -> dict[str, str]:
    """Extract editable non-secret environment settings from AppConfig.

    Args:
        cfg: Loaded application configuration.

    Returns:
        Mapping of allowed environment variable names to string values.
    """
    return {
        "VOICEBOX_URL": cfg.voicebox_url,
        "OLLAMA_BASE_URL": cfg.ollama_base_url,
        "OLLAMA_MODEL": cfg.ollama_model,
        "SADTALKER_DIR": str(cfg.sadtalker_dir or ""),
        "LOG_LEVEL": cfg.log_level,
    }


def _validate_single_line_updates(values: dict[str, str]) -> dict[str, str]:
    """Filter editable keys and reject newline characters to prevent .env injection.

    Args:
        values: Raw key-value mapping supplied by caller.

    Returns:
        Sanitized mapping restricted to ALLOWED_ENV_KEYS.

    Raises:
        ValueError: When any value contains CR or LF characters.
    """
    updates: dict[str, str] = {}
    for key, val in values.items():
        if key not in ALLOWED_ENV_KEYS:
            continue
        if "\n" in val or "\r" in val:
            raise ValueError(f"設定值不可包含換行字元：{key}")
        updates[key] = val
    return updates


def update_editable_env(
    values: dict[str, str],
    env_path: Path | None = None,
) -> dict[str, str]:
    """Persist validated non-secret settings into a .env file while preserving comments.

    Args:
        values: Mapping of allowed environment keys to single-line values.
        env_path: Optional override path to the .env file (defaults to project .env).

    Returns:
        Dictionary of keys and values written to the .env file.

    Raises:
        ValueError: When any value contains newline characters.
    """
    target = env_path or (PROJECT_ROOT / ".env")
    updates = _validate_single_line_updates(values)
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = line.partition("=")[0].strip() if "=" in line and not stripped.startswith("#") else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={val}")
    target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updates
