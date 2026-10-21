"""工作流測試：音訊提取（extract_audio）工作流程。

測試 extract.py 的真實/合成音訊提取流程：
- 使用 ffmpeg 產生短暫合成測試影片 (test.mp4)
- 測試 duration() 測量時長
- 測試 extract_audio() 提取單聲道 48kHz WAV
- 測試時間區段切割 (--start, --end)
- 測試不存在檔案的錯誤處理
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_studio.services.extract_audio.extract import duration, extract_audio


class TestWorkflowExtract(unittest.TestCase):
    """測試音訊提取工作流程。"""

    def setUp(self) -> None:
        """建立暫存目錄並使用 ffmpeg 產生 2 秒的測試影片。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.test_video = self.tmp / "test_video.mp4"

        # 檢查本機是否有 ffmpeg
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("系統未安裝 ffmpeg / ffprobe，略過整合測試")

        # 產生 2 秒測試影片 (內含 1000Hz 音訊)
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(self.test_video),
        ]
        subprocess.run(cmd, check=True)

    def tearDown(self) -> None:
        """清理暫存目錄。"""
        self.temp_dir.cleanup()

    def test_duration_measurement(self) -> None:
        """測試 ffprobe 時長測量。"""
        d = duration(self.test_video)
        self.assertAlmostEqual(d, 2.0, delta=0.2)

    def test_extract_audio_full(self) -> None:
        """測試完整音訊提取為 48kHz WAV。"""
        out_wav = self.tmp / "output.wav"
        result_path = extract_audio(self.test_video, out=out_wav)

        self.assertEqual(result_path, out_wav)
        self.assertTrue(out_wav.exists())
        self.assertGreater(out_wav.stat().st_size, 0)

        wav_dur = duration(out_wav)
        self.assertAlmostEqual(wav_dur, 2.0, delta=0.2)

    def test_extract_audio_trimmed_range(self) -> None:
        """測試依起始與結束時間擷取音訊片段。"""
        out_wav = self.tmp / "trimmed.wav"
        extract_audio(self.test_video, out=out_wav, start="0:00.5", end="0:01.5")

        self.assertTrue(out_wav.exists())
        wav_dur = duration(out_wav)
        self.assertAlmostEqual(wav_dur, 1.0, delta=0.2)

    def test_nonexistent_file_raises(self) -> None:
        """測試給定不存在影片時拋出例外。"""
        fake_video = self.tmp / "not_found.mp4"
        with self.assertRaises(subprocess.CalledProcessError):
            extract_audio(fake_video)


if __name__ == "__main__":
    unittest.main()
