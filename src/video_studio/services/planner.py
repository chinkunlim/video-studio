"""Antigravity (agy CLI) background planner service for video-studio."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_studio.config.settings import PROJECT_ROOT
from video_studio.services import review_history
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
    if posters:
        rules.append(
            "3. 講解聚焦 Highlight 與動態運鏡（必做）："
            "講解海報不同段落時，當前講到的區塊必須有明顯的高亮聚焦效果（發光外框／微幅放大／重點標記動畫），"
            "非當前區塊適度降暗（opacity 降至 ~0.45）；搭配 GSAP 平滑推拉運鏡（pan/zoom）、"
            "圖表或關鍵詞依講稿節奏逐一進場，並於畫面加入章節進度條，讓觀眾清楚跟上目前進度且畫面生動不單調。"
        )
    return rules


def _format_history_block(thread_mode: str, history: list[dict[str, str]] | None) -> list[str]:
    """Build prompt section for continuing or starting a fresh planning thread.

    Args:
        thread_mode: 'continue' or 'new'.
        history: Optional prior chat turns.

    Returns:
        List of prompt lines for the thread context section.
    """
    if thread_mode == "continue" and history:
        turns = [
            f"- {t.get('role', 'user')}: {str(t.get('text', '')).strip()[:320]}"
            for t in history[-6:]
            if str(t.get("text", "")).strip()
        ]
        if turns:
            return ["", "【前幾輪對話紀錄（延續修改）】", *turns]
    elif thread_mode == "new":
        return ["", "【對話模式】已開啟新對話串：請保留並延續磁碟上現有的草稿檔案進行修正。"]
    return []


def build_plan_prompt(
    job_name: str,
    user_instruction: str = "",
    mode: str = "html",
    follow_poster_design: bool = True,
    thread_mode: str = "continue",
    history: list[dict[str, str]] | None = None,
) -> str:
    """Assemble a complete planning prompt from the job's brief, script, and timing.

    Args:
        job_name: Target job name.
        user_instruction: Additional instruction from the web UI chat box.
        mode: Target planning mode ('html' or 'poster').
        follow_poster_design: Whether to preserve uploaded poster/PPTX design.
        thread_mode: 'continue' to include recent turns or 'new' for fresh context keeping disk draft.
        history: Optional list of {'role': ..., 'text': ...} prior chat turns.

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
    out_cfg = job.cfg.get("output", {})
    out_w = int(out_cfg.get("width", 1920))
    out_h = int(out_cfg.get("height", 1080))
    burn_in = bool(job.cfg.get("subtitles", {}).get("burn_in", True))
    sub_mode_note = (
        "字幕模式：有字幕（渲染時會在畫面最下方自動預留 96px 專用字幕帶，不會遮擋內容；"
        "請避免在 HTML 底部重複製作字幕條）"
        if burn_in
        else "字幕模式：無字幕（可使用 100% 滿版高度進行版面設計）"
    )
    history_block = _format_history_block(thread_mode, history)
    return "\n".join(
        [
            f"請為 video-studio 工作 `{job.type}/{job.name}`（標題：{job.title}）規劃分鏡草稿。",
            f"工作目錄：{job.dir}",
            f"輸出目標檔案（寫入 review/，勿直接改 input/）：{target_file}",
            (
                f"目標影片解析度：{out_w}x{out_h}（若輸出 index.html，請於 <html> 設定 "
                f'data-width="{out_w}" data-height="{out_h}" 且內容完全配合此尺寸不超出、不裁切）'
            ),
            sub_mode_note,
            "",
            "【使用者規劃說明 (brief.md)】",
            brief_text or "（無額外 brief.md）",
            "",
            "【海報設計與語言對齊規則】",
            *poster_rules,
            *history_block,
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


def parse_agy_stream_line(raw: str) -> dict[str, Any]:
    """Parse one NDJSON line emitted by `agy -p --output-format stream-json`.

    Args:
        raw: Single line from agy stdout.

    Returns:
        Normalized event dictionary with 'kind' ('init', 'delta', 'step', 'result', or 'text').
    """
    text = raw.strip()
    if not text:
        return {"kind": "empty"}
    try:
        ev = json.loads(text)
    except ValueError:
        return {"kind": "text", "text": text}
    etype = ev.get("event")
    if etype == "init":
        return {"kind": "init", "model": str(ev.get("init", {}).get("model", ""))}
    if etype == "step_update":
        su = ev.get("step_update", {})
        return {
            "kind": "step",
            "step_type": str(su.get("step_type", "")),
            "state": str(su.get("state", "")),
            "delta": str(su.get("text_delta", "")),
        }
    if etype == "result":
        res = ev.get("result", {})
        return {
            "kind": "result",
            "status": str(res.get("status", "")),
            "response": str(res.get("response", "")).strip(),
            "duration": float(res.get("duration_seconds", 0.0) or 0.0),
        }
    return {"kind": "empty"}


def _handle_stream_event(ev: dict[str, Any], run: PlanRun, buf: list[str]) -> None:
    """Update PlanRun state and app.log from a parsed stream-json event.

    Args:
        ev: Parsed event from parse_agy_stream_line.
        run: Active PlanRun instance.
        buf: Accumulator for streamed text_delta chunks.
    """
    kind = ev.get("kind")
    if kind == "init":
        logger.info("[agy] 啟動模型：%s (job=%s)", ev.get("model") or "default", run.job_name)
    elif kind == "step":
        delta = ev.get("delta", "")
        if delta:
            buf.append(delta)
            with _LOCK:
                run.lines = "".join(buf).splitlines()
        elif ev.get("step_type") not in ("", "user_input"):
            logger.info("[agy] 步驟 %s (%s)", ev.get("step_type"), ev.get("state"))
    elif kind == "result":
        logger.info("[agy] 完成狀態：%s（耗時 %.1fs）", ev.get("status"), ev.get("duration", 0.0))
        resp = ev.get("response", "")
        if resp:
            with _LOCK:
                run.lines = resp.splitlines()
    elif kind == "text":
        with _LOCK:
            run.lines.append(str(ev.get("text", "")))


def _run_agy_worker(run: PlanRun, agy_bin: str) -> None:
    """Execute agy -p --output-format stream-json in a background thread and log progress.

    Args:
        run: PlanRun state object to update.
        agy_bin: Resolved path to agy executable.
    """
    try:
        cmd = [
            agy_bin,
            "-p",
            run.prompt,
            "--mode",
            "accept-edits",
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]
        if run.job_dir:
            cmd.extend(["--add-dir", str(run.job_dir)])
        if run.model.strip():
            cmd.extend(["--model", run.model.strip()])
        logger.info("[agy] 開始分鏡規劃 (model=%s, job=%s)", run.model or "default", run.job_name)
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        buf: list[str] = []
        if proc.stdout:
            for line in proc.stdout:
                _handle_stream_event(parse_agy_stream_line(line), run, buf)
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
    """Run a synchronous one-shot `agy -p --output-format stream-json` prompt and log progress.

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
    cmd = [agy_bin, "-p", prompt, "--output-format", "stream-json", "--dangerously-skip-permissions"]
    if add_dir:
        cmd.extend(["--add-dir", str(add_dir)])
    if model.strip():
        cmd.extend(["--model", model.strip()])
    logger.info("[agy] 執行單次任務 (model=%s)", model or "default")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        final_resp = ""
        deltas: list[str] = []
        if proc.stdout:
            for raw in proc.stdout:
                ev = parse_agy_stream_line(raw)
                if ev.get("kind") == "init":
                    logger.info("[agy] 確認模型：%s", ev.get("model") or "default")
                elif ev.get("kind") == "step":
                    if ev.get("delta"):
                        deltas.append(str(ev["delta"]))
                    elif ev.get("step_type") not in ("", "user_input"):
                        logger.info("[agy] 步驟 %s (%s)", ev.get("step_type"), ev.get("state"))
                elif ev.get("kind") == "result":
                    logger.info("[agy] 完成 (%s, %.1fs)", ev.get("status"), ev.get("duration", 0.0))
                    final_resp = str(ev.get("response", "")).strip()
        rc = proc.wait(timeout=timeout)
    except Exception as exc:
        logger.warning("agy -p failed, will allow Ollama fallback: %s", exc)
        return None
    out_text = final_resp or "".join(deltas).strip()
    if rc != 0 or not out_text:
        logger.warning("agy -p exited %s (empty output)", rc)
        return None
    return out_text


def start_agy_plan(
    job_name: str,
    user_instruction: str = "",
    mode: str = "html",
    model: str = "",
    follow_poster_design: bool = True,
    thread_mode: str = "continue",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Start a background agy CLI planning run for a job.

    Args:
        job_name: Target job name.
        user_instruction: Optional user instruction or follow-up message.
        mode: Target output mode ('html' or 'poster').
        model: Optional agy model ID.
        follow_poster_design: Whether to preserve uploaded poster/PPTX design.
        thread_mode: 'continue' or 'new'.
        history: Optional prior chat turns.

    Returns:
        Dictionary containing run_id, status, available flag, and prompt.
    """
    prompt = build_plan_prompt(
        job_name, user_instruction, mode, follow_poster_design, thread_mode=thread_mode, history=history
    )
    review_history.create_snapshot(job_name, note=f"agy {mode} 規劃前自動備份")
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


def get_active_plan(job_name: str) -> dict[str, Any]:
    """Return the most recent active (running) agy planning run for a job, if any.

    Args:
        job_name: Target job name.

    Returns:
        Dictionary with ``active=True`` and run details when running, or ``active=False``.
    """
    with _LOCK:
        for run in reversed(list(_RUNS.values())):
            if run.job_name == job_name and run.status == "running":
                return {
                    "active": True,
                    "run_id": run.run_id,
                    "job_name": run.job_name,
                    "status": run.status,
                    "output": "\n".join(run.lines),
                    "error": run.error,
                    "returncode": run.returncode,
                }
    return {"active": False, "job_name": job_name}
