"""edge-tts 客戶端：提供免啟動 Voicebox、預設台灣中文聲線的雲端 TTS 選項。"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_EDGE_VOICE = "zh-TW-HsiaoChenNeural"
_VOICE_TAG_RE = re.compile(r"\[voice=([A-Za-z0-9-]+)\](.*?)\[/voice\]", re.DOTALL)


def split_voice_segments(text: str, default_voice: str) -> list[tuple[str, str]]:
    """Split text with optional `[voice=ID]...[/voice]` tags into (voice, text) segments.

    Args:
        text: Input speech text possibly containing `[voice=...]` tags.
        default_voice: Default edge-tts voice ID for untagged segments.

    Returns:
        Ordered list of non-empty (voice_id, segment_text) pairs.
    """
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in _VOICE_TAG_RE.finditer(text):
        before = text[pos : m.start()].strip()
        if before:
            segments.append((default_voice, before))
        inner = m.group(2).strip()
        if inner:
            segments.append((m.group(1).strip(), inner))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        segments.append((default_voice, tail))
    return segments or [(default_voice, text)]


class EdgeTTSClient:
    """實作與 Voicebox 相同的 check_ready/generate 介面之 edge-tts 包裝類別。"""

    no_wrap: bool = True

    def __init__(self, cfg: dict[str, Any]) -> None:
        """初始化 edge-tts 客戶端。

        Args:
            cfg: edge_tts 設定字典，支援 voice 與 rate。
        """
        self.voice: str = str(cfg.get("edge_voice") or DEFAULT_EDGE_VOICE)
        self.rate: str = str(cfg.get("edge_rate") or "+0%")

    def check_ready(self) -> None:
        """驗證 edge-tts 模組可用。"""
        logger.info("使用 edge-tts 聲線：%s", self.voice)

    async def _synthesize_mp3(
        self, text: str, mp3_path: Path, voice: str | None = None, rate: str | None = None
    ) -> None:
        """非同步呼叫 edge-tts 產生 MP3 音檔。

        Args:
            text: 要朗讀的文字。
            mp3_path: 暫存輸出 MP3 路徑。
            voice: 選填覆蓋聲線 ID。
            rate: 選填覆蓋語速字串。
        """
        comm = edge_tts.Communicate(text, voice=voice or self.voice, rate=rate or self.rate)
        await comm.save(str(mp3_path))

    def _to_wav(self, mp3_path: Path, wav_path: Path) -> None:
        """Convert an MP3 clip to 24kHz mono PCM WAV.

        Args:
            mp3_path: Source MP3 file path.
            wav_path: Destination WAV file path.
        """
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(mp3_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            check=True,
        )

    def generate(self, text: str, language: str | None = None) -> bytes:
        """將文字轉為 24kHz 單聲道 PCM WAV 位元組（支援 `[voice=...]` 多語切換）。

        Args:
            text: 要朗讀的文字。
            language: 保留參數（相容 Voicebox 介面）。

        Returns:
            WAV 音訊位元組資料。
        """
        _ = language
        segments = split_voice_segments(text, self.voice)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            wavs: list[Path] = []
            for idx, (seg_voice, seg_text) in enumerate(segments):
                mp3_p = tmp / f"seg_{idx}.mp3"
                wav_p = tmp / f"seg_{idx}.wav"
                if seg_voice == self.voice:
                    asyncio.run(self._synthesize_mp3(seg_text, mp3_p))
                else:
                    asyncio.run(self._synthesize_mp3(seg_text, mp3_p, seg_voice, "+0%"))
                self._to_wav(mp3_p, wav_p)
                wavs.append(wav_p)
            if len(wavs) == 1:
                return wavs[0].read_bytes()
            lst = tmp / "concat.txt"
            lst.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs), encoding="utf-8")
            merged = tmp / "merged.wav"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), str(merged)],
                check=True,
            )
            return merged.read_bytes()
