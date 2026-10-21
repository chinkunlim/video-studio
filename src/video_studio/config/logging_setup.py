"""Logging setup shared by every entrypoint, built for tracing one run or one request.

Every line looks like
    2026-10-20 09:15:02,481 INFO    [3f9a1c2e] app.services.greeting:create_greeting:24 - greeting user='Ann'
so you can see when, how serious, which run / request, and exactly which function and line.

- Run id: one short id per process run (`setup_logging()` creates it); inside an HTTP request
  the request id (`X-Request-ID`) replaces it. Trace one run: `grep 3f9a1c2e app.log`.
- Files (with `LOG_TO_FILE=true`, outside the project in `<DATA_DIR>/logs/`):
    `app.log`    : everything at `LOG_LEVEL` and above (5 MB x 5 rotated files)
    `errors.log` : WARNING and above only, for a quick look at what went wrong
- Console output goes to stderr, so a CLI's real output on stdout stays clean.
- Uncaught exceptions and Python warnings are written to the log with their traceback.
"""

from __future__ import annotations

import contextvars
import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


def new_run_id() -> str:
    """Create a short random id for a run or a request.

    Returns:
        Eight hexadecimal characters.
    """
    return uuid.uuid4().hex[:8]


def set_run_id(value: str) -> contextvars.Token[str]:
    """Use `value` as the id on every log line of the current context (e.g. one HTTP request).

    Args:
        value: Run or request id.

    Returns:
        Token for `reset_run_id()`.
    """
    return _RUN_ID.set(value)


def reset_run_id(token: contextvars.Token[str]) -> None:
    """Restore the id that was active before `set_run_id()`.

    Args:
        token: Token returned by `set_run_id()`.
    """
    _RUN_ID.reset(token)


class RunIdFilter(logging.Filter):
    """Attach the current run / request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add `record.run_id`.

        Args:
            record: Log record being emitted.

        Returns:
            Always True (nothing is filtered out).
        """
        record.run_id = _RUN_ID.get()
        return True


def _log_uncaught(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Write an uncaught exception with its traceback to the log (Ctrl-C is left alone).

    Args:
        exc_type: Exception class.
        exc: Exception instance.
        tb: Traceback.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("uncaught").critical("uncaught exception", exc_info=(exc_type, exc, tb))


def _rotating(path: Path, max_mb: int, backups: int) -> RotatingFileHandler:
    """Create a size-limited UTF-8 log file handler.

    Args:
        path: Log file path.
        max_mb: Size in MB before the file is rotated.
        backups: Number of old files to keep (`app.log.1` ...).

    Returns:
        The file handler.
    """
    return RotatingFileHandler(path, maxBytes=max_mb * 1_000_000, backupCount=backups, encoding="utf-8")


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> str:
    """Configure the root logger once per process and start a new run id.

    Args:
        level: Logging level name such as `DEBUG`, `INFO` or `WARNING`; unknown names fall back to `INFO`.
        log_dir: When given, also write `app.log` and `errors.log` there (outside the project).

    Returns:
        The run id written on every line of this run.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        errors = _rotating(log_dir / "errors.log", max_mb=2, backups=3)
        errors.setLevel(logging.WARNING)
        handlers += [_rotating(log_dir / "app.log", max_mb=5, backups=5), errors]
    formatter = logging.Formatter(LOG_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RunIdFilter())
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), handlers=handlers, force=True)
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    run_id = new_run_id()
    _RUN_ID.set(run_id)
    python = sys.version.split()[0]
    logging.getLogger(__name__).info("run started pid=%s python=%s log_dir=%s", os.getpid(), python, log_dir)
    return run_id
