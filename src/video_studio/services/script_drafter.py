"""AI script drafting service: generates structured one-sentence-per-line script.md into review/."""

from __future__ import annotations

import logging
from pathlib import Path

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.common.ollama_client import generate_text, is_ollama_reachable
from video_studio.services.narrate.core.script import split_sentences
from video_studio.services.planner import run_agy_prompt

logger = logging.getLogger(__name__)


def build_script_draft_prompt(
    job_title: str,
    brief_text: str,
    instruction: str,
    language: str = "zh",
    duration_sec: int = 90,
) -> str:
    """Build a prompt for drafting a spoken video script in Markdown format.

    Args:
        job_title: Display title of the video job.
        brief_text: Optional content of input/brief.md.
        instruction: User's script generation instruction.
        language: Spoken language code ('zh', 'en', 'ja', 'ko').
        duration_sec: Target spoken duration in seconds.

    Returns:
        Prompt string instructing the LLM to output clean Markdown script.
    """
    lang_label = {
        "zh": "繁體中文（台灣口語自然表達）",
        "en": "English (clear, natural spoken presentation style)",
        "ja": "日本語（自然なプレゼン話し言葉）",
        "ko": "한국어 (자연스러운 발표 구어체)",
    }.get(language, language)
    approx_lines = max(4, min(40, round(duration_sec / 6)))
    return "\n".join(
        [
            f"你是一位專業影片編劇，請為影片「{job_title}」撰寫口播講稿。",
            f"目標語言：{lang_label}",
            f"目標長度：約 {duration_sec} 秒（大約 {approx_lines} 句，一句獨立一行）。",
            "",
            "【工作規劃說明 (brief.md)】",
            brief_text.strip() or "（無額外 brief.md）",
            "",
            "【使用者指令】",
            instruction.strip() or "請依主題撰寫結構清晰、有開場、重點與結尾的影片講稿。",
            "",
            "【嚴格輸出格式】",
            "1. 第一行寫 `# 講稿：{標題}`。",
            "2. 用 `## 投影片 1`、`## 投影片 2` ... 分段。",
            "3. 每段底下只放口播句子，**一句一行**，不要加項目符號、不要加括號舞台指示、不要多餘前言或解釋。",
        ]
    )


def draft_script_to_review(
    job_name: str,
    instruction: str,
    language: str = "zh",
    duration_sec: int = 90,
    model: str | None = None,
) -> tuple[Path, str]:
    """Generate a script draft using local Ollama and save it to review/script.md.

    Args:
        job_name: Target job name.
        instruction: User's instruction describing what the script should cover.
        language: Spoken language code ('zh', 'en', 'ja', 'ko').
        duration_sec: Approximate target duration in seconds.
        model: Optional Ollama model override.

    Returns:
        Tuple of (path to review/script.md, formatted script content).

    Raises:
        RuntimeError: If local Ollama is unreachable.
    """
    app_cfg = load_app_config()
    job = J.find(job_name)
    brief_path = job.input / "brief.md"
    brief_text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    prompt = build_script_draft_prompt(job.title, brief_text, instruction, language, duration_sec)
    raw = run_agy_prompt(prompt, model=model or "")
    if raw is None:
        if not is_ollama_reachable(app_cfg.ollama_base_url):
            raise RuntimeError(
                f"agy CLI 與本機 Ollama（{app_cfg.ollama_base_url}）皆無法使用，無法生成講稿。"
            )
        raw = generate_text(
            prompt=prompt,
            base_url=app_cfg.ollama_base_url,
            model=app_cfg.ollama_model,
        )
    formatted = split_sentences(raw)
    job.review.mkdir(parents=True, exist_ok=True)
    out_path = job.review / "script.md"
    out_path.write_text(formatted.rstrip() + "\n", encoding="utf-8")
    orig_path = job.review / "script.original.md"
    if not orig_path.exists():
        orig_path.write_text(formatted.rstrip() + "\n", encoding="utf-8")
    logger.info("Drafted review script for %s -> %s", job.name, out_path)
    return out_path, formatted
