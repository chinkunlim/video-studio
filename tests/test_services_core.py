"""單元測試：核心 Services 層（Job, Script, Vocab, Numbers, Subtitles, Check）。

此檔案驗證從 legacy 遷移至 services 層的純邏輯模組：
- video_studio.services.common.job
- video_studio.services.common.check
- video_studio.services.narrate.core.numbers
- video_studio.services.narrate.core.vocab
- video_studio.services.narrate.core.script
- video_studio.services.narrate.core.subtitles
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from video_studio.services.common import check, job
from video_studio.services.narrate.core import numbers, script, subtitles, vocab


class TestJobManagement(unittest.TestCase):
    """測試工作區與工作目錄管理。"""

    def setUp(self) -> None:
        """建立暫存工作區目錄。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        """清理暫存工作區目錄。"""
        self.temp_dir.cleanup()

    def test_job_not_found(self) -> None:
        """測試尋找不存在的工作時拋出 JobError。"""
        with self.assertRaises(job.JobError):
            job.find("nonexistent_job", ws=self.workspace)

    def test_job_properties_and_structure(self) -> None:
        """測試 Job 屬性路徑解析與目錄結構。"""
        job_dir = (self.workspace / "generate" / "test-job").resolve()
        job_dir.mkdir(parents=True)
        (job_dir / "job.toml").write_text('[job]\ntype = "generate"\ntitle = "測試工作"\n', encoding="utf-8")

        j = job.Job(job_dir)
        self.assertEqual(j.name, "test-job")
        self.assertEqual(j.type, "generate")
        self.assertEqual(j.title, "測試工作")
        self.assertEqual(j.input, job_dir / "input")
        self.assertEqual(j.review, job_dir / "review")
        self.assertEqual(j.work, job_dir / "work")

        found = job.find("test-job", ws=self.workspace.resolve())
        self.assertEqual(found.dir, job_dir)

    def test_next_output_version(self) -> None:
        """測試輸出版本號遞增邏輯。"""
        job_dir = self.workspace / "generate" / "test-job"
        job_dir.mkdir(parents=True)
        (job_dir / "job.toml").write_text('title = "測試工作"\n', encoding="utf-8")

        j = job.Job(job_dir)
        out1 = j.next_output()
        self.assertEqual(out1.name, "v1")
        out1.mkdir(parents=True)

        out2 = j.next_output()
        self.assertEqual(out2.name, "v2")


class TestVocab(unittest.TestCase):
    """測試詞彙表載入與展開。"""

    def test_vocab_load_and_expand(self) -> None:
        """測試載入 TSV 格式詞彙並正確替換。"""
        tsv_content = (
            "key\tsubtitle\ttts\ttested\tcategory\tnote\n"
            "AI\t人工智慧\tㄟㄞ\t1\ttech\t常見縮寫\n"
            "Lejuez\tLejuez\t樂爵斯\t1\tperson\t學者名\n"
        )
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".tsv", delete=False) as f:
            f.write(tsv_content)
            temp_path = Path(f.name)

        try:
            v = vocab.load(temp_path)
            self.assertIn("AI", v)
            self.assertEqual(v["AI"]["subtitle"], "人工智慧")
            self.assertEqual(v["AI"]["tts"], "ㄟㄞ")

            text = "這是一個關於 {{AI}} 與 {{Lejuez}} 的研究。"
            expanded_sub = vocab.expand(text, v, "subtitle")
            self.assertEqual(expanded_sub, "這是一個關於 人工智慧 與 Lejuez 的研究。")

            expanded_tts = vocab.expand(text, v, "tts")
            self.assertEqual(expanded_tts, "這是一個關於 ㄟㄞ 與 樂爵斯 的研究。")

            keys = vocab.used_keys(text)
            self.assertEqual(keys, ["AI", "Lejuez"])
        finally:
            temp_path.unlink()


class TestNumbers(unittest.TestCase):
    """測試數字正規化與朗讀轉換。"""

    def test_integer_pronunciation(self) -> None:
        """測試整數中文化。"""
        self.assertEqual(numbers.integer(86), "八十六")
        self.assertEqual(numbers.integer(0), "零")
        self.assertEqual(numbers.integer(1005), "一千零五")

    def test_numbers_normalize(self) -> None:
        """測試數字、年份、小數與百分比的常規化替換。"""
        # 年份
        text_year = "2002年"
        self.assertEqual(numbers.normalize(text_year), "二零零二年")

        # 百分比
        text_pct = "25%"
        self.assertEqual(numbers.normalize(text_pct), "百分之二十五")

        # 小數
        text_dec = "3.14"
        self.assertEqual(numbers.normalize(text_dec), "三点一四")


class TestScript(unittest.TestCase):
    """測試講稿 markdown 解析與斷句。"""

    def test_script_parse(self) -> None:
        """測試講稿結構解析、投影片分頁與 [click] 偵測。"""
        content = """## 投影片 1
大家好，我是錦坤。
今天要來介紹研究。

## 投影片 2
[click] 首先看這張圖表。
這是一個重要結論。
"""
        lines = script.parse(content)
        self.assertEqual(len(lines), 4)

        # 第一行
        self.assertEqual(lines[0].no, 1)
        self.assertEqual(lines[0].slide, 1)
        self.assertEqual(lines[0].raw, "大家好，我是錦坤。")
        self.assertFalse(lines[0].click)

        # 第三行（投影片 2 開頭，含 [click]）
        self.assertEqual(lines[2].no, 3)
        self.assertEqual(lines[2].slide, 2)
        self.assertEqual(lines[2].raw, "首先看這張圖表。")
        self.assertTrue(lines[2].click)


class TestSubtitles(unittest.TestCase):
    """測試字幕時間軸切割與匯出。"""

    def test_build_cues_and_formats(self) -> None:
        """測試字幕區間生成與各格式 (SRT, VTT, ASS) 寫入。"""
        cues_input = [
            (0.0, 2.5, "大家好，我是講者。"),
            (3.0, 5.0, "歡迎收看本次影片。"),
        ]
        cfg = {
            "subtitle": {
                "font": "PingFang TC",
                "font_size": 28,
            }
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            files = subtitles.write_all(cues_input, out_dir, cfg, title="測試影片")

            self.assertIn("subtitles_youtube.srt", files)
            self.assertIn("subtitles_powerpoint.vtt", files)
            self.assertIn("subtitles_vlc.ass", files)

            # 檢查 SRT 內容
            srt_text = (out_dir / "subtitles_youtube.srt").read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:02,500", srt_text)
            self.assertIn("大家好，我是講者。", srt_text)

            # 檢查 VTT 內容
            vtt_text = (out_dir / "subtitles_powerpoint.vtt").read_text(encoding="utf-8")
            self.assertTrue(vtt_text.startswith("WEBVTT"))


class TestCheck(unittest.TestCase):
    """測試工作設定與檢查報告機制。"""

    def test_report_collection(self) -> None:
        """測試檢查報告的錯誤與警告收集。"""
        rep = check.Report()
        rep.err("file1.txt", "找不到檔案")
        rep.warn("file2.txt", "格式建議調整")

        self.assertEqual(len(rep.errors), 1)
        self.assertEqual(len(rep.warnings), 1)
        self.assertIn("file1.txt", rep.errors[0])
        self.assertIn("file2.txt", rep.warnings[0])


if __name__ == "__main__":
    unittest.main()
