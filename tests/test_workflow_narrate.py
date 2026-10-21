"""工作流測試：講稿配音與字幕生成（narrate）工作流程。

測試 narrate 模組的完整端到端流程：
1. check_script：講稿格式、詞彙標記與英文單字檢查
2. build_narration：
   - 準備各行音訊切片
   - 透過 concat.build 使用 ffmpeg 進行真實拼接與響度調整
   - 產生字幕檔（SRT、VTT、ASS）與 timeline.json
3. audition_line 與 pick_take：
   - 模擬 Voicebox 試聽候選音檔產生
   - 選定版本並鎖定至 takes
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from video_studio.services.common import job as J
from video_studio.services.narrate import narrate
from video_studio.services.sv import init_job


class TestWorkflowNarrate(unittest.TestCase):
    """測試配音與字幕生成工作流程。"""

    def setUp(self) -> None:
        """建立工作區與測試工作。"""
        if not shutil.which("ffmpeg"):
            self.skipTest("系統未安裝 ffmpeg，略過測試")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()

        init_job("generate", "narrate-e2e", title="配音端到端測試", ws=self.workspace)
        self.job = J.find("narrate-e2e", ws=self.workspace)

        # 寫入測試講稿
        script_text = "## 投影片 1\n歡迎收看本期簡報。\n\n## 投影片 2\n[click] 這是重點內容。\n"
        (self.job.input / "script.md").write_text(script_text, encoding="utf-8")

        # 建立共用詞彙表
        voc_text = "key\tsubtitle\ttts\ttested\tcategory\tnote\n"
        (self.workspace / "shared" / "vocabulary.tsv").write_text(voc_text, encoding="utf-8")

    def tearDown(self) -> None:
        """清理暫存目錄。"""
        self.temp_dir.cleanup()

    def _create_wav(self, path: Path, duration_sec: float = 1.0) -> None:
        """使用 ffmpeg 建立標準 48kHz 單聲道正弦波測試音檔。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_sec}:sample_rate=48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
        subprocess.run(cmd, check=True)

    def test_check_script_workflow(self) -> None:
        """測試講稿格式檢查與行清單輸出。"""
        scan_report = narrate.scan_vocab(self.job)
        self.assertIn("没有问题", scan_report)

        lines_report = narrate.list_lines(self.job)
        self.assertIn("[ 1]", lines_report)
        self.assertIn("歡迎收看本期簡報。", lines_report)

    def test_build_narration_with_existing_takes(self) -> None:
        """測試當每行音檔皆備妥時，build_narration 執行拼接與字幕產出。"""
        lines, _ = narrate.load_lines(self.job)
        takes = narrate.takes_of(self.job)

        # 為每一行建立合成音檔並登錄進 takes
        for ln in lines:
            tts_text = getattr(ln, "tts", "")
            clip_path = self.job.takes_dir / f"clip_{ln.no}.wav"
            self._create_wav(clip_path, duration_sec=1.2)
            takes.put(
                tts_text=tts_text,
                clip=clip_path,
                words=[[tts_text, 0.0, 1.2]],
                source="test-fixture",
                sim=0.95,
                locked=True,
            )

        # 執行 build_narration
        summary = narrate.build_narration(self.job)
        self.assertIn("完成：", summary)
        self.assertIn("narration.wav", summary)

        # 驗證 output/v1 產出檔案
        v1 = self.job.output / "v1"
        self.assertTrue(v1.exists())
        self.assertTrue((v1 / "narration.wav").exists())
        self.assertTrue((v1 / "timeline.json").exists())
        self.assertTrue((v1 / "subtitles_youtube.srt").exists())
        self.assertTrue((v1 / "subtitles_powerpoint.vtt").exists())
        self.assertTrue((v1 / "subtitles_vlc.ass").exists())
        self.assertTrue((v1 / "tts_vs_subtitle.tsv").exists())

        # 驗證 timeline 格式與長度
        timeline = json.loads((v1 / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[0]["no"], 1)
        self.assertEqual(timeline[1]["no"], 2)

    def test_audition_and_pick_workflow(self) -> None:
        """測試單行試聽生成與版本選定流程。"""
        # Mock Voicebox 生成器
        fake_take_result = [
            {
                "take": 1,
                "file": "work/gen/sample1.wav",
                "words": [["歡迎收看本期簡報。", 0.0, 1.0]],
                "sim": 0.92,
                "wrap": "none",
                "hyp": "歡迎收看本期簡報。",
            }
        ]

        def fake_take(*args: object, **kwargs: object) -> list[dict[str, object]]:
            # 建立假音檔
            target_path = self.job.work / "gen" / "sample1.wav"
            self._create_wav(target_path, 1.0)
            return fake_take_result

        with (
            patch("video_studio.services.narrate.narrate.Voicebox") as mock_vb_cls,
            patch("video_studio.services.narrate.narrate.generate.take", side_effect=fake_take),
            patch("video_studio.services.narrate.narrate.generate.store") as mock_store,
        ):
            mock_vb = MagicMock()
            mock_vb_cls.return_value = mock_vb

            def mock_store_fn(res: dict[str, object], dest: Path) -> Path:
                self._create_wav(dest, 1.0)
                return dest

            mock_store.side_effect = mock_store_fn

            # 執行 audition_line
            msg = narrate.audition_line(self.job, line_no=1, takes_count=1)
            self.assertIn("[1]", msg)
            self.assertTrue((self.job.review / "audition" / "line001" / "takes.json").exists())

            # 執行 pick_take
            pick_msg = narrate.pick_take(self.job, line_no=1, take_no=1)
            self.assertIn("并锁定", pick_msg)

            # 驗證 takes 已寫入該行
            lines, _ = narrate.load_lines(self.job)
            takes = narrate.takes_of(self.job)
            self.assertIsNotNone(takes.get(getattr(lines[0], "tts", "")))


if __name__ == "__main__":
    unittest.main()
