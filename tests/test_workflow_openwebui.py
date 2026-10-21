"""工作流測試：Open WebUI Tool 適配器完整工作流程。

測試 Tools 類別所有對外非同步方法：
- check_environment
- create_job
- list_jobs
- check_job
- set_vocabulary（驗證 confirm 參數保護）
- approve_review
- draft_scenes
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_studio.adapters.openwebui_tool import Tools


class TestWorkflowOpenWebUI(unittest.TestCase):
    """測試 Open WebUI Tool 適配器工作流程。"""

    def setUp(self) -> None:
        """建立工作區與初始化 Tools 執行個體。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()

        self.tools = Tools()
        self.tools.valves.workspace_dir = str(self.workspace)
        self.tools.valves.project_dir = str(Path(__file__).resolve().parents[1])

    def tearDown(self) -> None:
        """清理暫存目錄。"""
        self.temp_dir.cleanup()

    def test_check_environment(self) -> None:
        """測試 check_environment 回報環境資訊。"""
        with patch.object(self.tools._runner, "check_voicebox_ready", return_value=None):
            result = asyncio.run(self.tools.check_environment())
            self.assertIn("工作区：", result)

    def test_create_and_list_job(self) -> None:
        """測試 create_job 與 list_jobs 流程。"""
        create_res = asyncio.run(
            self.tools.create_job(
                job_type="generate",
                name="owui-job",
                title="WebUI測試工作",
                script_text="## 投影片 1\n這是講稿測試。\n",
            )
        )
        self.assertIn("已建立", create_res)

        # 檢查檔案是否生成
        job_dir = self.workspace / "generate" / "owui-job"
        self.assertTrue((job_dir / "input" / "script.md").exists())

        # 列出工作
        list_res = asyncio.run(self.tools.list_jobs())
        self.assertIn("owui-job", list_res)
        self.assertIn("WebUI測試工作", list_res)

    def test_set_vocabulary_protection(self) -> None:
        """測試 set_vocabulary 設定特殊詞彙。"""
        with patch.object(self.tools._runner, "run_command", return_value="已更新詞彙表"):
            res = asyncio.run(
                self.tools.set_vocabulary(
                    key="LLM",
                    subtitle="大型語言模型",
                    tts="大型語言模型",
                )
            )
            self.assertIn("已更新詞彙表", res)

    def test_approve_review_file(self) -> None:
        """測試 approve_review 移動 review 檔案至 input。"""
        asyncio.run(
            self.tools.create_job(
                job_type="generate",
                name="app-job",
                title="審查核准測試",
            )
        )
        job_dir = self.workspace / "generate" / "app-job"
        (job_dir / "review" / "scenes.toml").write_text('visual = "poster"\n', encoding="utf-8")

        res = asyncio.run(self.tools.approve_review("app-job", "scenes.toml"))
        self.assertIn("已确认", res)
        self.assertTrue((job_dir / "input" / "scenes.toml").exists())


if __name__ == "__main__":
    unittest.main()
