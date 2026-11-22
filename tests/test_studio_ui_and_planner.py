"""Tests for notebooklm-batch-studio style Web UI, full settings APIs, and agy CLI planner."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from video_studio.config.settings import AppConfig
from video_studio.entrypoints.api import create_app
from video_studio.services.common import job as J
from video_studio.services.narrate.narrate import load_narrate_config


class TestStudioUIAndPlanner(unittest.TestCase):
    """Verify full Web UI assets, job config/script/brief/upload endpoints, and agy planner."""

    def setUp(self) -> None:
        """Create isolated workspace and TestClient."""
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name).resolve()
        self.ws = self.data_dir / "workspace"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(os.environ, {"SPLIT_VOICE_WORKSPACE": str(self.ws)})
        self.env_patch.start()
        self.cfg = AppConfig(app_env="test", log_to_file=False, data_dir=self.data_dir, workspace_dir=self.ws)
        self.client = TestClient(create_app(self.cfg))

    def tearDown(self) -> None:
        """Restore environment and clean up temp directory."""
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_studio_static_assets(self) -> None:
        """Verify index.html, studio-theme.css, studio.css, and studio.js load with typing UI."""
        html = self.client.get("/")
        self.assertEqual(html.status_code, 200)
        self.assertIn("qa-drawer", html.text)
        self.assertIn("cfgVoiceLanguage", html.text)
        self.assertIn('id="assetFileInput" multiple', html.text)
        self.assertIn("btnLayoutGuides", html.text)
        self.assertIn("OpenAPI 文件", html.text)

        css = self.client.get("/studio.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("qa-typing-dots", css.text)
        self.assertIn("qaBounce", css.text)
        self.assertIn("layout-guide-hud", css.text)

        theme = self.client.get("/studio-theme.css")
        self.assertEqual(theme.status_code, 200)
        self.assertIn("--canvas: #f4eee6", theme.text)

        js = self.client.get("/studio.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("runAntigravityPlan", js.text)
        self.assertIn("showToast", js.text)
        self.assertIn("^(generate|dub|extract)", js.text)

        missing = self.client.get("/api/jobs/nonexistent-job/detail")
        self.assertEqual(missing.status_code, 404)

        tune_js = self.client.get("/studio-layout-tune.js")
        self.assertEqual(tune_js.status_code, 200)
        self.assertIn("toggleLayoutGuides", tune_js.text)
        self.assertIn("toggleLayoutTuneMode", tune_js.text)

        ux_js = self.client.get("/studio-ux.js")
        self.assertEqual(ux_js.status_code, 200)
        self.assertIn("initDraftAutosave", ux_js.text)
        self.assertIn("refreshLiveTerminal", ux_js.text)

        shell_js = self.client.get("/studio-shell.js")
        self.assertEqual(shell_js.status_code, 200)
        self.assertIn("initStudioUxOverhaul", shell_js.text)

        actions_js = self.client.get("/studio-actions.js")
        self.assertEqual(actions_js.status_code, 200)
        self.assertIn("bindOverviewEvents", actions_js.text)

        tail = self.client.get("/api/logs/tail?lines=10")
        self.assertEqual(tail.status_code, 200)
        self.assertIn("lines", tail.json())

    def test_job_config_script_brief_and_upload(self) -> None:
        """Verify creating a job, saving brief/script/job.toml, and uploading an asset."""
        self.assertEqual(
            self.client.post(
                "/api/jobs", json={"job_type": "generate", "name": "ui-job", "title": "UI 測試"}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put("/api/jobs/ui-job/brief", json={"content": "## 主題\n測試規劃說明"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                "/api/jobs/ui-job/script",
                json={"content": "## 投影片 1\n第一句測試。", "auto_format": False},
            ).status_code,
            200,
        )
        cfg_res = self.client.put(
            "/api/jobs/ui-job/config",
            json={
                "title": "UI 測試",
                "visual_mode": "html",
                "voice_engine": "edge-tts",
                "voice_language": "en",
                "edge_voice": "en-US-AriaNeural",
                "whisper_model": "base",
                "opencc_mode": "none",
                "subtitle_font_size": 26,
                "fps": 24,
                "loudness": -14.0,
                "burn_in": True,
                "inputs": {"script": "script.md"},
            },
        )
        self.assertEqual(cfg_res.status_code, 200)

        up_res = self.client.post(
            "/api/jobs/ui-job/upload",
            files={"file": ("slides.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        self.assertEqual(up_res.status_code, 200)

        detail = self.client.get("/api/jobs/ui-job/detail").json()
        self.assertEqual(detail["config"]["voice"]["engine"], "edge-tts")
        self.assertEqual(detail["config"]["voice"]["language"], "en")
        self.assertEqual(detail["config"]["whisper"]["model"], "base")
        self.assertEqual(detail["config"]["whisper"]["opencc_mode"], "none")
        self.assertEqual(detail["config"]["subtitles"]["font_size"], 26)
        self.assertEqual(detail["config"]["output"]["fps"], 24)
        self.assertEqual(detail["config"]["visual"]["mode"], "html")
        self.assertIn("slides.pdf", detail["input_files"])
        self.assertIn("測試規劃說明", detail["brief"])

        narrate_cfg = load_narrate_config(J.find("ui-job"))
        self.assertEqual(narrate_cfg["voicebox"]["language"], "en")
        self.assertEqual(narrate_cfg["whisper"]["model"], "base")
        self.assertEqual(narrate_cfg["whisper"]["opencc_mode"], "none")

    def test_agy_planner_streams_response(self) -> None:
        """Verify agy -p background planner streams output and finishes cleanly."""
        self.client.post("/api/jobs", json={"job_type": "generate", "name": "plan-job", "title": "規劃測試"})
        self.client.put("/api/jobs/plan-job/brief", json={"content": "請用簡潔森林風格規劃兩幕動畫"})

        fake_proc = MagicMock()
        fake_proc.stdout = iter(["正在讀取 brief.md…\n", "已將分鏡寫入 review/index.html\n"])
        fake_proc.wait.return_value = 0

        with (
            patch("video_studio.services.planner.shutil.which", return_value="/usr/local/bin/agy"),
            patch("video_studio.services.planner.subprocess.Popen", return_value=fake_proc),
        ):
            start = self.client.post(
                "/api/jobs/plan-job/plan", json={"instruction": "第一幕淡入", "mode": "html"}
            )
            self.assertEqual(start.status_code, 200)
            run_id = start.json()["run_id"]
            self.assertEqual(start.json()["status"], "running")

            for _ in range(20):
                st = self.client.get(f"/api/plan/{run_id}").json()
                if st["status"] != "running":
                    break
                time.sleep(0.05)

            self.assertEqual(st["status"], "done")
            self.assertIn("已將分鏡寫入 review/index.html", st["output"])


if __name__ == "__main__":
    unittest.main()
