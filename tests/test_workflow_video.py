"""工作流測試：影片合成與渲染（video）工作流程。

測試 video 模組的完整端到端流程：
1. calc_timing：解析講稿與 timeline.json，計算投影片起訖時間並輸出 slide_timing.tsv
2. draft_scenes：依海報圖片與講稿幕數，自動起草 scenes.toml 與 scenes_preview.jpg
3. mux_external_video：外部影片與配音音訊合成，並燒錄繁體字幕
4. check_video：驗收影片規格、音訊時長與產生縮圖接觸表
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video_studio.services.common import job as J
from video_studio.services.sv import approve_file, init_job
from video_studio.services.video import video


class TestWorkflowVideo(unittest.TestCase):
    """測試影片合成與渲染工作流程。"""

    def setUp(self) -> None:
        """建立測試工作區與基本素材。"""
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("系統未安裝 ffmpeg / ffprobe，略過測試")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()

        # 切換共用工作區
        self.patcher = patch("video_studio.services.common.job.workspace", return_value=self.workspace)
        self.patcher.start()

        init_job("generate", "video-e2e", title="影片合成端到端測試", ws=self.workspace)
        self.job = J.find("video-e2e", ws=self.workspace)

        # 寫入講稿 input/script.md
        script_text = "## 投影片 1\n第一幕簡介。\n\n## 投影片 2\n[click] 第二幕重點。\n"
        (self.job.input / "script.md").write_text(script_text, encoding="utf-8")

        # 寫入成品的配音與字幕到 output/v1/
        v1 = self.job.output / "v1"
        v1.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.job.input / "script.md", v1 / "script.md")

        timeline = [
            {"no": 1, "start": 0.0, "end": 1.5, "trim_start": 0.0},
            {"no": 2, "start": 2.0, "end": 3.5, "trim_start": 0.0},
        ]
        (v1 / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")

        # 產生 4.5 秒的配音 WAV
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4.5:sample_rate=48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(v1 / "narration.wav"),
        ]
        subprocess.run(cmd, check=True)

        # 產生字幕
        srt_content = (
            "1\n00:00:00,000 --> 00:00:01,500\n第一幕簡介。\n\n"
            "2\n00:00:02,000 --> 00:00:03,500\n第二幕重點。\n"
        )
        (v1 / "subtitles_vlc.srt").write_text(srt_content, encoding="utf-8")

        # 產生海報圖片
        img = Image.new("RGB", (1200, 1600), color=(255, 255, 255))
        img.save(self.job.input / "poster.png")

        # 更新 job.toml 中的 inputs
        job_toml_text = (
            "[job]\n"
            'type = "generate"\n'
            'title = "影片合成端到端測試"\n\n'
            "[inputs]\n"
            'script = "script.md"\n'
            'poster = "poster.png"\n'
            'scenes = "scenes.toml"\n'
        )
        (self.job.dir / "job.toml").write_text(job_toml_text, encoding="utf-8")

    def tearDown(self) -> None:
        """清理暫存目錄。"""
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_calc_timing_workflow(self) -> None:
        """測試 calc_timing 正確計算投影片時間軸並輸出 TSV。"""
        summary = video.calc_timing("video-e2e", version="v1")
        self.assertIn("slide_timing.tsv", summary)

        tsv_path = self.job.output / "v1" / "slide_timing.tsv"
        self.assertTrue(tsv_path.exists())
        content = tsv_path.read_text(encoding="utf-8")
        self.assertIn("slide\tstart\tend\tduration", content)
        self.assertIn("1\t0.00\t2.00\t2.00", content)

    def test_draft_scenes_workflow(self) -> None:
        """測試 draft_scenes 自動依海報與講稿產生分鏡。"""
        msg = video.draft_scenes("video-e2e", source="even")
        self.assertIn("已起草", msg)
        self.assertTrue((self.job.review / "scenes.toml").exists())
        self.assertTrue((self.job.review / "scenes_preview.jpg").exists())

        # 核准分鏡檔
        app_msg = approve_file("video-e2e", "scenes.toml", ws=self.workspace)
        self.assertIn("已确认", app_msg)
        self.assertTrue((self.job.input / "scenes.toml").exists())

    def test_mux_and_check_video_workflow(self) -> None:
        """測試外部畫面合成與驗收流程。"""
        # 產生 5 秒的測試靜態影片畫面
        raw_video = self.job.work / "source_video.mp4"
        raw_video.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1920x1080:d=5:r=30",
            "-c:v",
            "libx264",
            str(raw_video),
        ]
        subprocess.run(cmd, check=True)

        # 執行 mux
        mux_msg = video.mux_external_video("video-e2e", raw_video, version="v1")
        self.assertIn("已合成", mux_msg)

        v1 = self.job.output / "v1"
        self.assertTrue((v1 / "video.mp4").exists())
        self.assertTrue((v1 / "video_subtitled.mp4").exists())
        self.assertTrue((v1 / "video_contact_sheet.jpg").exists())

        # 執行 check
        check_report = video.check_video("video-e2e", version="v1")
        self.assertIn("video.mp4", check_report)
        self.assertTrue((v1 / "video_check.txt").exists())


if __name__ == "__main__":
    unittest.main()
