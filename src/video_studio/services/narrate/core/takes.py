"""takes.json：每句选用的音档。以「念法文字」的指纹当索引，所以：
- 讲稿或词汇表改了哪一句的念法，只有那一句会重做；
- 你挑选并锁定（locked）的版本，不会被重做掉。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def key(tts_text: str) -> str:
    """根据发音文字计算 SHA1 前缀指纹 key。

    Args:
        tts_text: 发音文字。

    Returns:
        12 码 16 进位哈希值。
    """
    return hashlib.sha1(tts_text.encode("utf-8")).hexdigest()[:12]


class Takes:
    """管理工作已生成的单句配音 take 记录。"""

    def __init__(self, base_dir: Path | str, path: Path | str | None = None) -> None:
        """初始化 Takes 管理器。

        Args:
            base_dir: 音档路径的起点（工作资料夹）。
            path: takes.json 的位置（预设 work/takes.json）。
        """
        self.dir = Path(base_dir)
        self.path = Path(path) if path else self.dir / "work" / "takes.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, dict[str, Any]] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        )

    def get(self, tts_text: str) -> dict[str, Any] | None:
        """查询某发音文字是否已有对应录音档。

        Args:
            tts_text: 念法文字。

        Returns:
            take 资料字典或 None。
        """
        t = self.data.get(key(tts_text))
        if t and (self.dir / str(t.get("clip", ""))).exists():
            return t
        return None

    def put(
        self,
        tts_text: str,
        clip: Path | str,
        words: list[dict[str, Any]],
        source: str,
        sim: float | None = None,
        locked: bool = False,
    ) -> None:
        """记录单一发音文字的选用音档。

        Args:
            tts_text: 念法文字。
            clip: 音档路径。
            words: 逐字时间戳清单。
            source: 来源描述。
            sim: Whisper 比对相似度。
            locked: 是否锁定。
        """
        rel = Path(clip).resolve().relative_to(self.dir.resolve())
        self.data[key(tts_text)] = {
            "tts": tts_text,
            "clip": str(rel),
            "words": words,
            "source": source,
            "sim": sim,
            "locked": locked,
        }
        self.save()

    def lock(self, tts_text: str, locked: bool = True) -> None:
        """锁定或解锁特定发音句子。

        Args:
            tts_text: 念法文字。
            locked: 目标锁定状态。
        """
        k = key(tts_text)
        if k in self.data:
            self.data[k]["locked"] = locked
            self.save()

    def save(self) -> None:
        """将 takes 记录写回磁碟。"""
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
