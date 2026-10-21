"""词汇表（vocabulary.tsv）：特殊词的「字幕显示」和「Voicebox 念法」分开定义。

讲稿里写 {{key}}，产生字幕时换成 subtitle 栏，送给 Voicebox 时换成 tts 栏。
以后要换念法，只改表格，所有讲稿都会跟着变。
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARKER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
FIELDS: list[str] = ["key", "type", "subtitle", "tts", "tts_lang", "tested", "note"]


def load(path: Path | str) -> dict[str, dict[str, str]]:
    """载入 TSV 词汇表。

    Args:
        path: 词汇表档案路径。

    Returns:
        以 key 为键的词汇字典。
    """
    rows: dict[str, dict[str, str]] = {}
    p = Path(path)
    if not p.exists():
        return rows
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            k = (r.get("key") or "").strip()
            if k and not k.startswith("#"):
                rows[k] = {col: (r.get(col) or "").strip() for col in FIELDS}
    return rows


def expand(raw: str, vocab: dict[str, dict[str, str]], field: str) -> str:
    """把 {{key}} 换成 subtitle 或 tts 栏。

    Args:
        raw: 包含 {{key}} 的原始讲稿句子。
        vocab: 词汇表字典。
        field: 取用的栏位名称（'subtitle' 或 'tts'）。

    Returns:
        替换后的文字。

    Raises:
        KeyError: 当找不到 key 时。
    """

    def sub(m: re.Match[str]) -> str:
        """依匹配到的 key 替换为对应栏位的词汇文字。

        Args:
            m: 正则匹配物件。

        Returns:
            替换后的文字字串。
        """
        key = m.group(1).strip()
        if key not in vocab:
            raise KeyError(f"词汇表里没有「{key}」：请在 vocabulary.tsv 加上这一行")
        return vocab[key].get(field) or vocab[key].get("subtitle", "")

    return MARKER.sub(sub, raw)


def used_keys(raw: str) -> list[str]:
    """取出句子中所有被引用的词汇 key。

    Args:
        raw: 原始句子字串。

    Returns:
        引用的 key 列表。
    """
    return [k.strip() for k in MARKER.findall(raw)]


def unmarked_english(raw: str) -> list[str]:
    """找出没有放进 {{}} 的英文词（可能漏标）。

    Args:
        raw: 原始句子字串。

    Returns:
        未标示的英文词列表。
    """
    cleaned = MARKER.sub("", raw)
    return re.findall(r"[A-Za-z][A-Za-z.\-']*", cleaned)


def save(path: Path | str, rows: dict[str, dict[str, str]] | dict[str, Any]) -> None:
    """将词汇字典写回 TSV 档案。

    Args:
        path: 目标 TSV 路径。
        rows: 词汇资料字典。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows.values():
            filtered = {col: str(r.get(col, "") or "") for col in FIELDS}
            w.writerow(filtered)
