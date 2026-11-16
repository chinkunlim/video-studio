"""Antigravity (agy CLI) background planner service for video-studio."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_studio.config.settings import PROJECT_ROOT
from video_studio.services.common import job as J

logger = logging.getLogger(__name__)


@dataclass
class PlanRun:
    """In-memory state of a background Antigravity planning run."""

    run_id: str
    job_name: str
    prompt: str
    model: str = ""
    status: str = "running"
    lines: list[str] = field(default_factory=list)
    error: str | None = None
    returncode: int | None = None


_RUNS: dict[str, PlanRun] = {}
_LOCK = threading.Lock()


def build_plan_prompt(job_name: str, user_instruction: str = "", mode: str = "html") -> str:
    """Assemble a complete planning prompt from the job's brief, script, and timing.

    Args:
        job_name: Target job name.
        user_instruction: Additional instruction from the web UI chat box.
        mode: Target planning mode ('html' or 'poster').

    Returns:
        Self-contained prompt string for Antigravity / agy CLI.
    """
    job = J.find(job_name)
    brief_path = job.input / "brief.md"
    brief_text = brief_path.read_text(encoding="utf-8").strip() if brief_path.exists() else ""
    out_v = job.latest_output()
    timing_path = (out_v / "slide_timing.tsv") if out_v else None
    timing_text = (
        timing_path.read_text(encoding="utf-8").strip()
        if timing_path and timing_path.exists()
        else "（尚未產出時間軸，請先執行 narrate build）"
    )
    target_file = f"{job.review / 'index.html'}" if mode == "html" else f"{job.review / 'scenes.toml'}"
    return "\n".join(
        [
            f"請為 video-studio 工作 `{job.type}/{job.name}`（標題：{job.title}）規劃分鏡草稿。",
            f"工作目錄：{job.dir}",
            f"輸出目標檔案（寫入 review/，勿直接改 input/）：{target_file}",
            "",
            "【使用者規劃說明 (brief.md)】",
            brief_text or "（無額外 brief.md）",
            "",
            "【本次補充要求】",
            user_instruction.strip() or "請依講稿與先聲後影時間軸規劃清晰、可重現的分鏡與動畫。",
            "",
            "【先聲後影時間軸 (slide_timing.tsv)】",
            timing_text,
            "",
            "【規範提醒】",
            "1. 若輸出 index.html，請使用確定性動畫（禁用 Math.random() 與 Date.now()），"
            "字型用系統本機字型（PingFang TC / Microsoft JhengHei）。",
            "2. 完成後請簡要回覆你規劃的每一幕重點，讓使用者在網頁審閱並點選核可。",
        ]
    )


def _run_agy_worker(run: PlanRun, agy_bin: str) -> None:
    """Execute agy -p in a background thread and stream output lines.

    Args:
        run: PlanRun state object to update.
        agy_bin: Resolved path to agy executable.
    """
    try:
        cmd = [agy_bin, "-p", run.prompt, "--mode", "accept-edits"]
        if run.model.strip():
            cmd.extend(["--model", run.model.strip()])
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.stdout:
            for line in proc.stdout:
                with _LOCK:
                    run.lines.append(line.rstrip("\n"))
        rc = proc.wait()
        with _LOCK:
            run.returncode = rc
            run.status = "done" if rc == 0 else "error"
            if rc != 0:
                run.error = f"agy exited with code {rc}"
    except Exception as exc:
        logger.exception("agy planner failed")
        with _LOCK:
            run.status = "error"
            run.error = str(exc)


def _resolve_agy_bin() -> str | None:
    """Locate the agy CLI executable on PATH or ~/.local/bin/agy.

    Returns:
        Path string to agy executable, or None if unavailable.
    """
    local_agy = Path.home() / ".local/bin/agy"
    return shutil.which("agy") or (str(local_agy) if local_agy.exists() else None)


def list_agy_models() -> list[dict[str, str]]:
    """Query available models from `agy models`.

    Returns:
        List of {'id': ..., 'label': ...} dictionaries.
    """
    agy_bin = _resolve_agy_bin()
    if not agy_bin:
        return []
    try:
        proc = subprocess.run([agy_bin, "models"], capture_output=True, text=True, timeout=10, check=False)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    models: list[dict[str, str]] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or "Fetching available models" in line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and "-" in parts[0]:
            models.append({"id": parts[0].strip(), "label": parts[1].strip()})
    return models


def start_agy_plan(
    job_name: str,
    user_instruction: str = "",
    mode: str = "html",
    model: str = "",
) -> dict[str, Any]:
    """Start a background agy CLI planning run for a job.

    Args:
        job_name: Target job name.
        user_instruction: Optional user instruction or follow-up message.
        mode: Target output mode ('html' or 'poster').
        model: Optional agy model ID.

    Returns:
        Dictionary containing run_id, status, available flag, and prompt.
    """
    prompt = build_plan_prompt(job_name, user_instruction, mode)
    agy_bin = _resolve_agy_bin()
    run_id = uuid.uuid4().hex[:12]
    if not agy_bin:
        return {
            "run_id": run_id,
            "status": "unavailable",
            "available": False,
            "prompt": prompt,
            "error": "找不到 agy CLI，請複製提示詞到 Antigravity App 執行。",
        }
    run = PlanRun(run_id=run_id, job_name=job_name, prompt=prompt, model=model)
    with _LOCK:
        _RUNS[run_id] = run
    threading.Thread(target=_run_agy_worker, args=(run, agy_bin), daemon=True).start()
    return {"run_id": run_id, "status": "running", "available": True, "prompt": prompt}


def get_plan_status(run_id: str) -> dict[str, Any]:
    """Return current status and accumulated output of a planning run.

    Args:
        run_id: Planning run identifier.

    Returns:
        Status dictionary with status, output text, and error if any.

    Raises:
        KeyError: When run_id is unknown.
    """
    with _LOCK:
        run = _RUNS.get(run_id)
        if not run:
            raise KeyError(f"Unknown plan run: {run_id}")
        return {
            "run_id": run.run_id,
            "job_name": run.job_name,
            "status": run.status,
            "output": "\n".join(run.lines),
            "error": run.error,
            "returncode": run.returncode,
        }
