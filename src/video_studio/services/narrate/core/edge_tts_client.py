"""edge-tts 客戶端：提供免啟動 Voicebox、預設台灣中文聲線的雲端 TTS 選項。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_EDGE_VOICE = "zh-TW-HsiaoChenNeural"


class EdgeTTSClient:
    """實作與 Voicebox 相同的 check_ready/generate 介面之 edge-tts 包裝類別。"""

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

    async def _synthesize_mp3(self, text: str, mp3_path: Path) -> None:
        """非同步呼叫 edge-tts 產生 MP3 音檔。

        Args:
            text: 要朗讀的文字。
            mp3_path: 暫存輸出 MP3 路徑。
        """
        comm = edge_tts.Communicate(text, voice=self.voice, rate=self.rate)
        await comm.save(str(mp3_path))

    def generate(self, text: str, language: str | None = None) -> bytes:
        """將文字轉為 24kHz 單聲道 PCM WAV 位元組。

        Args:
            text: 要朗讀的文字。
            language: 保留參數（相容 Voicebox 介面）。

        Returns:
            WAV 音訊位元組資料。
        """
        _ = language
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            mp3_path = tmp / "speech.mp3"
            wav_path = tmp / "speech.wav"
            asyncio.run(self._synthesize_mp3(text, mp3_path))
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
            return wav_path.read_bytes()
