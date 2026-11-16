"""Tests for dual TTS engine (Voicebox + edge-tts) and HTML/GSAP/HyperFrames rendering."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_studio.config.settings import AppConfig
from video_studio.entrypoints.api import create_app
from video_studio.entrypoints.cli import build_parser
from video_studio.entrypoints.mcp_server import build_mcp_server
from video_studio.services.common import job as J
from video_studio.services.narrate import narrate
from video_studio.services.narrate.core.edge_tts_client import DEFAULT_EDGE_VOICE, EdgeTTSClient
from video_studio.services.sv import approve_file, init_job
from video_studio.services.video import video as video_mod
from video_studio.services.video.engine import html_render


class TestDualTTSAndHTMLRender(unittest.TestCase):
    """Verify edge-tts client switching and HyperFrames HTML video pipeline."""

    def setUp(self) -> None:
        """Create an isolated temporary workspace for TTS and HTML render tests."""
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name).resolve()
        self.ws = self.data_dir / "workspace"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(os.environ, {"SPLIT_VOICE_WORKSPACE": str(self.ws)})
        self.env_patch.start()

        init_job("generate", "dual-demo", title="雙引擎測試", ws=self.ws)
        self.job = J.find("dual-demo", self.ws)
        (self.job.input / "script.md").write_text(
            "## 投影片 1\n歡迎使用雙引擎工作流。\n\n## 投影片 2\n支援高畫質網頁動畫渲染。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        """Restore environment and clean up temporary workspace."""
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_edge_tts_config_selection_and_client(self) -> None:
        """Verify job.toml engine=edge-tts selects EdgeTTSClient and generates WAV."""
        toml_path = self.job.dir / "job.toml"
        text = toml_path.read_text(encoding="utf-8")
        text = text.replace(
            'engine = "voicebox"',
            'engine = "edge-tts"',
        )
        toml_path.write_text(text, encoding="utf-8")
        reloaded = J.find("dual-demo", self.ws)

        cfg = narrate.load_narrate_config(reloaded)
        self.assertEqual(cfg["tts"]["engine"], "edge-tts")
        self.assertEqual(cfg["tts"]["edge_voice"], DEFAULT_EDGE_VOICE)

        client = narrate._build_tts_client(cfg)
        self.assertIsInstance(client, EdgeTTSClient)

        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg unavailable")

        async def fake_mp3(self_obj: EdgeTTSClient, text_val: str, mp3_path: Path) -> None:
            _ = (self_obj, text_val)
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=0.4",
                    str(mp3_path),
                ],
                check=True,
            )

        with patch.object(EdgeTTSClient, "_synthesize_mp3", new=fake_mp3):
            wav_bytes = client.generate("測試台灣腔配音")
            self.assertTrue(wav_bytes.startswith(b"RIFF"))

    def test_html_draft_and_render_workflow(self) -> None:
        """Verify deterministic HTML draft, approval, and HyperFrames video muxing."""
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg unavailable")

        v1 = self.job.output / "v1"
        v1.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=500:duration=4.0",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(v1 / "narration.wav"),
            ],
            check=True,
        )
        (v1 / "timeline.json").write_text(
            '[{"no": 1, "start": 0.0, "end": 2.0}, {"no": 2, "start": 2.0, "end": 3.5}]',
            encoding="utf-8",
        )
        (v1 / "script.md").write_text(
            (self.job.input / "script.md").read_text(encoding="utf-8"), encoding="utf-8"
        )

        draft_msg = video_mod.draft_html_scene("dual-demo")
        self.assertIn("index.html", draft_msg)
        review_html = self.job.review / "index.html"
        self.assertTrue(review_html.exists())
        html_text = review_html.read_text(encoding="utf-8")
        self.assertNotIn("Math.random", html_text)
        self.assertNotIn("Date.now", html_text)
        self.assertIn("PingFang TC", html_text)

        approve_file("dual-demo", "index.html", ws=self.ws)
        self.assertTrue((self.job.input / "index.html").exists())

        def fake_hyperframes_render(html_path: Path, out_mp4: Path, cfg: dict[str, object]) -> Path:
            _ = (html_path, cfg)
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x240:d=4.0:r=10",
                    "-c:v",
                    "libx264",
                    str(out_mp4),
                ],
                check=True,
            )
            return out_mp4

        with patch.object(html_render, "render", side_effect=fake_hyperframes_render):
            res = video_mod.render_html_video("dual-demo")
            self.assertIn("完成：", res)
            self.assertTrue((v1 / "video.mp4").exists())
            self.assertTrue((v1 / "video_contact_sheet.jpg").exists())

    def test_cli_api_and_mcp_html_routes(self) -> None:
        """Verify CLI parser, FastAPI OpenAPI route, and MCP confirm gate for html mode."""
        args = build_parser().parse_args(["video", "html", "dual-demo"])
        self.assertEqual(args.video_cmd, "html")

        cfg = AppConfig(app_env="test", log_to_file=False, data_dir=self.data_dir, workspace_dir=self.ws)
        client = TestClient(create_app(cfg))
        schema = client.get("/openapi.json").json()
        self.assertIn("/api/jobs/{job_name}/video/html", schema["paths"])

        mcp = build_mcp_server(cfg)
        refused = asyncio.run(
            mcp.call_tool("mcp_render_html_video", {"job_name": "dual-demo", "confirm": False})
        )
        self.assertIn("需要確認", str(refused))

        _ = SimpleNamespace(slide=1)


if __name__ == "__main__":
    unittest.main()
