"""Configuration layer: the ONLY layer allowed to read environment variables.

Loads settings once at startup into an immutable `AppConfig` so every other layer
receives plain values instead of touching `os.environ`.

Data lives OUTSIDE the project folder: `DATA_DIR` (default `../../projects-data/video-studio`) holds
input/, output/, needs_review/, state/, db/ and logs/. The project folder only holds code,
docs and small test fixtures. A relative `DATA_DIR` is resolved from the project folder (never
from the current working directory), so the project and its data can be moved together.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "../../projects-data/video-studio"


def resolve_data_dir(raw: str) -> Path:
    """Turn a `DATA_DIR` value into an absolute path.

    Args:
        raw: Value from `.env`; relative paths are relative to the project folder, `~` is expanded.

    Returns:
        The absolute data folder.
    """
    path = Path(raw.strip()).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


# Keys whose project `.env` value beats an inherited environment variable. `DATA_DIR` is a common
# name (e.g. Open WebUI's `export DATA_DIR=...` in ~/.zshrc) and must never point a project elsewhere.
PROJECT_FILE_WINS = ("DATA_DIR",)


def load_dotenv_file(path: Path) -> None:
    """Load `KEY=value` lines from a `.env` file.

    Variables that are already set win (so `LOG_LEVEL=DEBUG uv run ...` works), except the keys in
    `PROJECT_FILE_WINS`, where the project's own `.env` always wins.

    Args:
        path: The `.env` file (missing files are ignored).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("\"'")
            if key in PROJECT_FILE_WINS and value:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


@dataclass(frozen=True)
class AppConfig:
    """Immutable application settings.

    Attributes:
        app_env: Deployment environment name, e.g. `development` or `production`.
        log_level: Logging level name, e.g. `INFO` or `DEBUG`.
        log_to_file: Also write `<data_dir>/logs/app.log` and `errors.log` (default on; tests turn it off).
        timeout_seconds: Timeout for outgoing API calls.
        ollama_base_url: Local Ollama endpoint (always 127.0.0.1, never localhost / 0.0.0.0).
        http_allowed_origins: Explicit HTTP origins allowed for CORS and mutating requests.
        http_allowed_host_suffixes: Allowed host/origin domain suffixes (e.g. `.ts.net`).
        data_dir: Root folder for all data, outside the project folder.
    """

    app_env: str = "development"
    log_level: str = "INFO"
    log_to_file: bool = True
    timeout_seconds: int = 15
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:latest"
    voicebox_url: str = "http://127.0.0.1:17493"
    sadtalker_dir: Path | None = None
    http_host: str = "127.0.0.1"
    http_port: int = 8772
    http_allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8772", "http://127.0.0.1:8080")
    http_allowed_host_suffixes: tuple[str, ...] = (".ts.net",)
    workspace_dir: Path | None = None
    data_dir: Path = resolve_data_dir(DEFAULT_DATA_DIR)

    def process_env(self) -> dict[str, str]:
        """Produce an environment variable dictionary for subprocesses.

        Returns:
            Dictionary containing current system environment variables with overrides.
        """
        env = dict(os.environ)
        if self.workspace_dir:
            env["SPLIT_VOICE_WORKSPACE"] = str(self.workspace_dir)
        return env

    @property
    def input_dir(self) -> Path:
        """Folder with per-job read-only input files (`<data_dir>/input/<job>`).

        Returns:
            `<data_dir>/input`.
        """
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """Folder for per-job rendered versions and releases (`<data_dir>/output/<job>`).

        Returns:
            `<data_dir>/output`.
        """
        return self.data_dir / "output"

    @property
    def needs_review_dir(self) -> Path:
        """Folder for per-job AI drafts, prosody previews, and review history.

        Returns:
            `<data_dir>/needs_review`.
        """
        return self.data_dir / "needs_review"

    @property
    def work_dir(self) -> Path:
        """Folder for per-job intermediate working files (takes, gen, temp renders).

        Returns:
            `<data_dir>/work`.
        """
        return self.data_dir / "work"

    @property
    def shared_dir(self) -> Path:
        """Folder for cross-job shared vocabulary and voice reference samples.

        Returns:
            `<data_dir>/shared`.
        """
        return self.data_dir / "shared"

    @property
    def state_dir(self) -> Path:
        """Folder for per-job configuration (`state/<job>/job.toml`) and state.

        Returns:
            `<data_dir>/state`.
        """
        return self.data_dir / "state"

    @property
    def logs_dir(self) -> Path:
        """Folder for log files.

        Returns:
            `<data_dir>/logs`.
        """
        return self.data_dir / "logs"


def _csv(value: str) -> tuple[str, ...]:
    """Split a comma-separated setting.

    Args:
        value: Raw text such as `a, b`.

    Returns:
        The non-empty, stripped items.
    """
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _host_suffixes(value: str) -> tuple[str, ...]:
    """Normalize comma-separated host suffixes with leading dots and lowercase.

    Args:
        value: Raw comma-separated domain suffix string (e.g. `.ts.net`).

    Returns:
        Normalized suffix tuple.
    """
    items: list[str] = []
    for raw in _csv(value):
        s = raw.lower()
        items.append(s if s.startswith(".") else f".{s}")
    return tuple(items)


def _flag(value: str) -> bool:
    """Interpret an environment flag.

    Args:
        value: Raw text such as `1`, `true`, `yes`.

    Returns:
        True for 1 / true / yes / on (case-insensitive).
    """
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> AppConfig:
    """Read and validate configuration from `.env` and environment variables.

    Returns:
        A populated `AppConfig`.

    Raises:
        ValueError: When a numeric setting is not an integer.
    """
    load_dotenv_file(PROJECT_ROOT / ".env")
    data_dir = resolve_data_dir(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR))
    ws_env = os.environ.get("SPLIT_VOICE_WORKSPACE", "").strip()
    workspace_dir = Path(ws_env).expanduser() if ws_env else None
    sad_env = os.environ.get("SADTALKER_DIR", "").strip()
    sadtalker_dir = Path(sad_env).expanduser() if sad_env else (data_dir / "models" / "SadTalker")
    return AppConfig(
        app_env=os.environ.get("APP_ENV", "development").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        log_to_file=_flag(os.environ.get("LOG_TO_FILE", "true")),
        timeout_seconds=int(os.environ.get("API_TIMEOUT_SECONDS", "15")),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5:latest").strip(),
        voicebox_url=os.environ.get("VOICEBOX_URL", "http://127.0.0.1:17493").strip().rstrip("/"),
        sadtalker_dir=sadtalker_dir,
        http_host=os.environ.get("HTTP_HOST", "127.0.0.1").strip(),
        http_port=int(os.environ.get("HTTP_PORT", "8772")),
        http_allowed_origins=_csv(
            os.environ.get("HTTP_ALLOWED_ORIGINS", "http://127.0.0.1:8772,http://127.0.0.1:8080")
        ),
        http_allowed_host_suffixes=_host_suffixes(os.environ.get("HTTP_ALLOWED_HOST_SUFFIXES", ".ts.net")),
        workspace_dir=workspace_dir,
        data_dir=data_dir,
    )
