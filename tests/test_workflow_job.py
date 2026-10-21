"""工作流測試：Job / Workspace 管理工作流程。

測試 sv.py 與 common.job 的完整工作流程：
- init_job：extract / dub / generate 各類別初始化與範本複製
- 參數驗證：無效類型、非正規命名、重複建立例外處理
- list_jobs：空目錄與多工作清單輸出
- approve_file：review/ 檔案移至 input/，既有檔案備份至 .previous/
- check_job_status：針對初始化後與設定齊全的工作進行檢查
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from video_studio.services.common import job as J
from video_studio.services.sv import approve_file, check_job_status, init_job, list_jobs


class TestWorkflowJob(unittest.TestCase):
    """測試工作管理端到端流程。"""

    def setUp(self) -> None:
        """建立暫存工作區目錄。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        """清理暫存工作區目錄。"""
        self.temp_dir.cleanup()

    def test_init_all_job_types(self) -> None:
        """測試 extract, dub, generate 三種工作初始化。"""
        for j_type in ("extract", "dub", "generate"):
            name = f"test-{j_type}-sample"
            msg = init_job(j_type, name, title=f"測試 {j_type}", ws=self.workspace)
            self.assertIn(f"已建立 {j_type}/{name}", msg)

            j_dir = self.workspace / j_type / name
            self.assertTrue(j_dir.exists())
            self.assertTrue((j_dir / "job.toml").exists())
            self.assertTrue((j_dir / "input").exists())
            self.assertTrue((j_dir / "review").exists())
            self.assertTrue((j_dir / "work").exists())
            self.assertTrue((j_dir / "output").exists())

            # 檢查共用目錄與詞彙表是否自動建立
            self.assertTrue((self.workspace / "shared" / "vocabulary.tsv").exists())
            self.assertTrue((self.workspace / "shared" / "voice" / "samples").exists())

    def test_init_validation_errors(self) -> None:
        """測試錯誤參數拋出明確例外。"""
        # 無效類型
        with self.assertRaises(RuntimeError) as ctx:
            init_job("invalid_type", "demo", ws=self.workspace)
        self.assertIn("类型要是", str(ctx.exception))

        # 非小寫英文連字號命名
        with self.assertRaises(RuntimeError) as ctx:
            init_job("generate", "Test_Invalid_Name!", ws=self.workspace)
        self.assertIn("不合格", str(ctx.exception))

        # 重複建立
        init_job("generate", "dup-job", ws=self.workspace)
        with self.assertRaises(RuntimeError) as ctx:
            init_job("generate", "dup-job", ws=self.workspace)
        self.assertIn("已经存在", str(ctx.exception))

    def test_list_jobs_formatting(self) -> None:
        """測試 list_jobs 列出多個工作。"""
        init_job("generate", "job-a", title="工作甲", ws=self.workspace)
        init_job("extract", "job-b", title="工作乙", ws=self.workspace)

        output = list_jobs(self.workspace)
        self.assertIn("job-a", output)
        self.assertIn("工作甲", output)
        self.assertIn("job-b", output)
        self.assertIn("工作乙", output)

    def test_approve_file_workflow(self) -> None:
        """測試 approve_file 搬移與備份機制。"""
        init_job("generate", "approve-test", ws=self.workspace)
        j = J.find("approve-test", ws=self.workspace)

        # 審查不存在檔案拋錯
        with self.assertRaises(RuntimeError) as ctx:
            approve_file("approve-test", "scenes.toml", ws=self.workspace)
        self.assertIn("review/ 里没有 scenes.toml", str(ctx.exception))

        # 建立草稿檔案於 review/
        draft_content_v1 = 'title = "Version 1"\n'
        (j.review / "scenes.toml").write_text(draft_content_v1, encoding="utf-8")

        # 首次核可移至 input/
        msg1 = approve_file("approve-test", "scenes.toml", ws=self.workspace)
        self.assertIn("已确认", msg1)
        self.assertTrue((j.input / "scenes.toml").exists())
        self.assertEqual((j.input / "scenes.toml").read_text(encoding="utf-8"), draft_content_v1)
        self.assertFalse((j.review / "scenes.toml").exists())

        # 再次建立新草稿並核可，驗證備份至 input/.previous/
        draft_content_v2 = 'title = "Version 2"\n'
        (j.review / "scenes.toml").write_text(draft_content_v2, encoding="utf-8")

        msg2 = approve_file("approve-test", "scenes.toml", ws=self.workspace)
        self.assertIn("备份到 input/.previous", msg2)
        self.assertEqual((j.input / "scenes.toml").read_text(encoding="utf-8"), draft_content_v2)
        bak_files = list((j.input / ".previous").glob("scenes.*.toml"))
        self.assertTrue(len(bak_files) >= 1)
        self.assertEqual(bak_files[0].read_text(encoding="utf-8"), draft_content_v1)

    def test_check_job_status_workflow(self) -> None:
        """測試 check_job_status 檢查與報錯。"""
        init_job("extract", "check-extract", ws=self.workspace)
        ok, report = check_job_status("check-extract", ws=self.workspace)
        self.assertIn("check-extract", report)


if __name__ == "__main__":
    unittest.main()
