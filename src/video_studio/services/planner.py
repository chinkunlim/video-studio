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
    job_dir: Path | None = None
    status: str = "running"
    lines: list[str] = field(default_factory=list)
    error: str | None = None
    returncode: int | None = None


_RUNS: dict[str, PlanRun] = {}
_LOCK = threading.Lock()


def _poster_and_lang_rules(job: J.Job, follow_poster_design: bool) -> list[str]:
    """Build prompt instructions for poster design reuse and cross-language translation.

    Args:
        job: Loaded Job instance.
        follow_poster_design: Whether to preserve uploaded poster/PPTX layout and colors.

    Returns:
        List of instruction lines for the planning prompt.
    """
    in_files = sorted(p.name for p in job.input.iterdir() if p.is_file()) if job.input.is_dir() else []
    posters = [
        f for f in in_files if f.lower().endswith((".pptx", ".pdf", ".png", ".jpg")) and "script" not in f
    ]
    voice_lang = str(job.cfg.get("voice", {}).get("language", "zh")).strip().lower()
    rules = [f"已上傳素材目錄（{job.input}）：{', '.join(in_files) if in_files else '無'}"]
    if posters and follow_poster_design:
        rules.append(
            f"1. 沿用海報設計：請先檢視 {', '.join(posters)} 的版面結構、配色與視覺層級，"
            "在 HTML/GSAP 中保留並重構使用者的原海報設計風格。"
        )
    elif posters:
        rules.append(f"1. 參考 {', '.join(posters)} 的核心資訊，但可重新設計更適合影片動態節奏的版面。")
    if posters and voice_lang != "zh":
        rules.append(
            f"2. 跨語系海報翻譯：目前語音語言為 `{voice_lang}`，請自動將海報上所有中文標題、"
            f"內文、圖表標籤翻譯為自然流暢的 `{voice_lang}` 呈現於畫面中。"
        )
    return rules


def build_plan_prompt(
    job_name: str,
    user_instruction: str = "",
    mode: str = "html",
    follow_poster_design: bool = True,
) -> str:
    """Assemble a complete planning prompt from the job's brief, script, and timing.

    Args:
        job_name: Target job name.
        user_instruction: Additional instruction from the web UI chat box.
        mode: Target planning mode ('html' or 'poster').
        follow_poster_design: Whether to preserve uploaded poster/PPTX design.

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
    poster_rules = _poster_and_lang_rules(job, follow_poster_design)
    return "\n".join(
        [
            f"請為 video-studio 工作 `{job.type}/{job.name}`（標題：{job.title}）規劃分鏡草稿。",
            f"工作目錄：{job.dir}",
            f"輸出目標檔案（寫入 review/，勿直接改 input/）：{target_file}",
            "",
            "【使用者規劃說明 (brief.md)】",
            brief_text or "（無額外 brief.md）",
            "",
            "【海報設計與語言對齊規則】",
            *poster_rules,
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
        cmd = [agy_bin, "-p", run.prompt, "--mode", "accept-edits", "--dangerously-skip-permissions"]
        if run.job_dir:
            cmd.extend(["--add-dir", str(run.job_dir)])
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


def run_agy_prompt(
    prompt: str,
    model: str = "",
    timeout: int = 180,
    add_dir: Path | None = None,
) -> str | None:
    """Run a synchronous one-shot `agy -p` prompt as the primary AI brain.

    Args:
        prompt: Prompt text for agy CLI.
        model: Optional agy model ID.
        timeout: Subprocess timeout in seconds.
        add_dir: Optional external directory to grant agy read/write access.

    Returns:
        Response text if agy succeeded, or None if agy is unavailable or failed.
    """
    agy_bin = _resolve_agy_bin()
    if not agy_bin:
        return None
    cmd = [agy_bin, "-p", prompt, "--dangerously-skip-permissions"]
    if add_dir:
        cmd.extend(["--add-dir", str(add_dir)])
    if model.strip():
        cmd.extend(["--model", model.strip()])
    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout, check=False
        )
    except Exception as exc:
        logger.warning("agy -p failed, will allow Ollama fallback: %s", exc)
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        logger.warning("agy -p exited %s: %s", proc.returncode, proc.stderr.strip())
        return None
    return proc.stdout.strip()


def start_agy_plan(
    job_name: str,
    user_instruction: str = "",
    mode: str = "html",
    model: str = "",
    follow_poster_design: bool = True,
) -> dict[str, Any]:
    """Start a background agy CLI planning run for a job.

    Args:
        job_name: Target job name.
        user_instruction: Optional user instruction or follow-up message.
        mode: Target output mode ('html' or 'poster').
        model: Optional agy model ID.
        follow_poster_design: Whether to preserve uploaded poster/PPTX design.

    Returns:
        Dictionary containing run_id, status, available flag, and prompt.
    """
    prompt = build_plan_prompt(job_name, user_instruction, mode, follow_poster_design)
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
    run = PlanRun(run_id=run_id, job_name=job_name, prompt=prompt, model=model, job_dir=J.find(job_name).dir)
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
