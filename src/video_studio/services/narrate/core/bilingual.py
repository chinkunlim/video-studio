"""Bilingual subtitle translation and TSV persistence helpers."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.common.ollama_client import generate_text, is_ollama_reachable
from video_studio.services.narrate.core.script import parse as parse_script
from video_studio.services.planner import run_agy_prompt

logger = logging.getLogger(__name__)


def build_bilingual_prompt(lines: list[str], target_lang: str = "zh-TW") -> str:
    """Build a numbered-line translation prompt for bilingual subtitles.

    Args:
        lines: Ordered spoken script lines.
        target_lang: Target subtitle language (e.g. 'zh-TW').

    Returns:
        Prompt string requesting `[index] translation` per line.
    """
    numbered = "\n".join(f"[{i + 1}] {txt}" for i, txt in enumerate(lines))
    return (
        f"請將以下每一句影片旁白翻譯成自然簡潔的「{target_lang}」字幕。\n"
        "請嚴格保留 `[編號] 譯文` 格式，一行對應一句，不要合併或省略任何編號：\n\n"
        f"{numbered}"
    )


def parse_bilingual_output(raw: str, lines: list[str]) -> list[tuple[int, str, str]]:
    """Parse numbered LLM translation output into (index, primary, secondary) tuples.

    Args:
        raw: Raw LLM text output.
        lines: Original spoken script lines.

    Returns:
        List of (1-based index, primary text, translated text) tuples.
    """
    parsed: dict[int, str] = {}
    for row in raw.splitlines():
        m = re.match(r"^\s*\[?(\d+)\]?[\.\):：]?\s+(.+)$", row.strip())
        if m:
            parsed[int(m.group(1))] = m.group(2).strip()
    return [(i + 1, txt, parsed.get(i + 1, "")) for i, txt in enumerate(lines)]


def save_bilingual_tsv(tsv_path: Path, rows: list[tuple[int, str, str]]) -> Path:
    """Save bilingual line pairs to a TSV file.

    Args:
        tsv_path: Destination TSV path.
        rows: List of (index, primary, secondary) tuples.

    Returns:
        Saved TSV path.
    """
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["index", "primary", "secondary"])
        for idx, primary, secondary in rows:
            writer.writerow([idx, primary, secondary])
    return tsv_path


def load_bilingual_map(tsv_path: Path) -> dict[str, str]:
    """Load primary -> secondary translation mapping from script_bilingual.tsv.

    Args:
        tsv_path: Path to script_bilingual.tsv.

    Returns:
        Dictionary mapping stripped primary text to translated secondary text.
    """
    if not tsv_path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with open(tsv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            p = (row.get("primary") or "").strip()
            s = (row.get("secondary") or "").strip()
            if p and s:
                mapping[p] = s
    return mapping


def translate_job_script_bilingual(
    job_name: str,
    target_lang: str = "zh-TW",
    model: str = "",
) -> tuple[Path, int]:
    """Translate a job's input/script.md into work/script_bilingual.tsv via agy CLI (or Ollama fallback).

    Args:
        job_name: Target job name.
        target_lang: Target secondary subtitle language.
        model: Optional agy CLI model ID.

    Returns:
        Tuple of (TSV path, number of translated lines).

    Raises:
        RuntimeError: If script.md is missing or both agy and Ollama are unavailable.
    """
    job = J.find(job_name)
    if not job.script or not job.script.exists():
        raise RuntimeError("找不到 input/script.md，請先準備或生成講稿。")
    app_cfg = load_app_config()
    spoken_lines = [ln.raw for ln in parse_script(job.script.read_text(encoding="utf-8"))]
    if not spoken_lines:
        raise RuntimeError("input/script.md 沒有可翻譯的句子。")
    prompt = build_bilingual_prompt(spoken_lines, target_lang)
    raw = run_agy_prompt(prompt, model=model)
    if raw is None:
        if not is_ollama_reachable(app_cfg.ollama_base_url):
            raise RuntimeError(
                f"agy CLI 與本機 Ollama（{app_cfg.ollama_base_url}）皆無法使用，無法翻譯雙語字幕。"
            )
        raw = generate_text(prompt=prompt, base_url=app_cfg.ollama_base_url, model=app_cfg.ollama_model)
    rows = parse_bilingual_output(raw, spoken_lines)
    tsv_path = job.work / "script_bilingual.tsv"
    save_bilingual_tsv(tsv_path, rows)
    logger.info("Saved %d bilingual subtitle rows -> %s", len(rows), tsv_path)
    return tsv_path, len(rows)
