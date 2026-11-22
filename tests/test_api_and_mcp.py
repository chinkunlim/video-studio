"""Tests for FastAPI HTTP API, security guards, static Web UI, and MCP Server."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_studio.config.env_store import update_editable_env
from video_studio.config.settings import AppConfig
from video_studio.entrypoints.api import create_app
from video_studio.entrypoints.mcp_server import build_mcp_server


class TestAPIAndMCP(unittest.TestCase):
    """Verify FastAPI routes, Host/Origin guards, Web UI, and MCP confirm gates."""

    def setUp(self) -> None:
        """Create an isolated temporary DATA_DIR and workspace for API/MCP tests."""
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name).resolve()
        self.workspace = self.data_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.cfg = AppConfig(
            app_env="test",
            log_to_file=False,
            data_dir=self.data_dir,
            workspace_dir=self.workspace,
        )
        self.env_patch = patch.dict(os.environ, {"SPLIT_VOICE_WORKSPACE": str(self.workspace)})
        self.env_patch.start()
        self.client = TestClient(create_app(self.cfg))

    def tearDown(self) -> None:
        """Restore environment and remove temporary workspace."""
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_health_ui_and_openapi(self) -> None:
        """Verify /health, static Web UI, /docs, and OpenAPI schema endpoints."""
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        ui = self.client.get("/")
        self.assertEqual(ui.status_code, 200)
        self.assertIn("OpenAPI 文件", ui.text)

        docs = self.client.get("/docs")
        self.assertEqual(docs.status_code, 200)

        schema = self.client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/jobs", schema.json()["paths"])

    def test_host_and_origin_guards(self) -> None:
        """Verify non-local Host and disallowed Origin headers return 403."""
        bad_host = self.client.get("/health", headers={"host": "evil.example:8772"})
        self.assertEqual(bad_host.status_code, 403)

        bad_origin = self.client.post(
            "/api/jobs",
            json={"job_type": "generate", "name": "blocked"},
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(bad_origin.status_code, 403)

    def test_jobs_and_vocab_http_workflow(self) -> None:
        """Verify job creation, listing, checking, and vocabulary endpoints."""
        init_res = self.client.post(
            "/api/jobs",
            json={"job_type": "generate", "name": "api-demo", "title": "API 測試"},
        )
        self.assertEqual(init_res.status_code, 200)
        self.assertIn("已建立 generate/api-demo", init_res.json()["output"])

        list_res = self.client.get("/api/jobs")
        self.assertEqual(list_res.status_code, 200)
        self.assertIn("api-demo", list_res.json()["output"])

        vocab_res = self.client.post(
            "/api/vocab",
            json={"key": "MCP", "subtitle": "MCP", "tts": "M C P"},
        )
        self.assertEqual(vocab_res.status_code, 200)
        self.assertIn("MCP", self.client.get("/api/vocab").json()["output"])

    def test_mcp_tools_and_confirm_gate(self) -> None:
        """Verify MCP tool registration, read-only call, and confirm=True gate."""
        mcp = build_mcp_server(self.cfg)
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        self.assertIn("mcp_list_jobs", names)
        self.assertIn("mcp_init_job", names)
        self.assertIn("mcp_build_narration", names)
        self.assertIn("mcp_publish_release", names)

        refused = asyncio.run(
            mcp.call_tool("mcp_init_job", {"job_type": "generate", "name": "mcp-demo", "confirm": False})
        )
        self.assertIn("需要確認", str(refused))
        self.assertFalse((self.workspace / "state" / "mcp-demo").exists())

        accepted = asyncio.run(
            mcp.call_tool("mcp_init_job", {"job_type": "generate", "name": "mcp-demo", "confirm": True})
        )
        self.assertIn("已建立 generate/mcp-demo", str(accepted))
        self.assertTrue((self.workspace / "state" / "mcp-demo" / "job.toml").exists())

        listed = asyncio.run(mcp.call_tool("mcp_list_jobs", {}))
        self.assertIn("mcp-demo", str(listed))

        # Verify publish release confirm gate + HTTP publish route
        pub_refused = asyncio.run(
            mcp.call_tool("mcp_publish_release", {"job_name": "mcp-demo", "confirm": False})
        )
        self.assertIn("需要確認", str(pub_refused))

        v1_dir = self.workspace / "output" / "mcp-demo" / "v1"
        v1_dir.mkdir(parents=True, exist_ok=True)
        (v1_dir / "video_subtitled.mp4").write_bytes(b"fake-mp4")
        (v1_dir / "subtitles_youtube.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8"
        )

        pub_res = self.client.post("/api/jobs/mcp-demo/video/publish", json={"version": "v1"})
        self.assertEqual(pub_res.status_code, 200)
        self.assertIn("已發布定稿 v1", pub_res.json()["output"])
        detail = self.client.get("/api/jobs/mcp-demo/detail").json()
        self.assertEqual(detail["published_release"]["version"], "v1")
        self.assertEqual(detail["output_versions"], ["v1"])

    def test_allowed_host_suffixes_and_cors(self) -> None:
        """Verify configurable HTTP_ALLOWED_HOST_SUFFIXES for Host, Origin, and CORS preflight."""
        ok_health = self.client.get("/health", headers={"host": "demo.tailnet.ts.net"})
        self.assertEqual(ok_health.status_code, 200)

        preflight = self.client.options(
            "/api/jobs",
            headers={
                "host": "demo.tailnet.ts.net",
                "origin": "https://demo.tailnet.ts.net",
                "access-control-request-method": "POST",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers.get("access-control-allow-origin"), "https://demo.tailnet.ts.net")

        ok_post = self.client.post(
            "/api/jobs",
            json={"job_type": "generate", "name": "ts-demo"},
            headers={"host": "demo.tailnet.ts.net", "origin": "https://demo.tailnet.ts.net"},
        )
        self.assertEqual(ok_post.status_code, 200)

        strict_cfg = AppConfig(
            app_env="test",
            log_to_file=False,
            data_dir=self.data_dir,
            workspace_dir=self.workspace,
            http_allowed_host_suffixes=(".my-tailnet.ts.net",),
        )
        strict_client = TestClient(create_app(strict_cfg))
        self.assertEqual(strict_client.get("/health", headers={"host": "other.ts.net"}).status_code, 403)
        self.assertEqual(
            strict_client.get("/health", headers={"host": "box.my-tailnet.ts.net"}).status_code, 200
        )

        disabled_cfg = AppConfig(
            app_env="test",
            log_to_file=False,
            data_dir=self.data_dir,
            workspace_dir=self.workspace,
            http_allowed_host_suffixes=(),
        )
        disabled_client = TestClient(create_app(disabled_cfg))
        self.assertEqual(
            disabled_client.get("/health", headers={"host": "demo.tailnet.ts.net"}).status_code, 403
        )

    def test_env_store_and_newline_injection_guard(self) -> None:
        """Verify env_store preserves comments, updates keys, and blocks newline injection."""
        env_file = self.data_dir / ".env"
        env_file.write_text("# comment\nLOG_LEVEL=INFO\nDATA_DIR=/keep/me\n", encoding="utf-8")

        written = update_editable_env({"LOG_LEVEL": "DEBUG", "OLLAMA_MODEL": "qwen2.5"}, env_path=env_file)
        self.assertEqual(written, {"LOG_LEVEL": "DEBUG", "OLLAMA_MODEL": "qwen2.5"})
        content = env_file.read_text(encoding="utf-8")
        self.assertIn("# comment", content)
        self.assertIn("LOG_LEVEL=DEBUG", content)
        self.assertIn("DATA_DIR=/keep/me", content)
        self.assertIn("OLLAMA_MODEL=qwen2.5", content)

        with self.assertRaises(ValueError):
            update_editable_env({"LOG_LEVEL": "INFO\nDATA_DIR=/tmp/pwn"}, env_path=env_file)

        bad_resp = self.client.put(
            "/api/settings/env",
            json={"values": {"LOG_LEVEL": "INFO\r\nDATA_DIR=/tmp/pwn"}},
        )
        self.assertEqual(bad_resp.status_code, 400)

    def test_mcp_studio_tools_and_confirm_gate(self) -> None:
        """Verify newly added Studio MCP tools are registered, JSON-valid, and confirm-gated."""
        mcp = build_mcp_server(self.cfg)
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        expected = {
            "mcp_avatar_status",
            "mcp_list_review_snapshots",
            "mcp_get_plan_status",
            "mcp_draft_script",
            "mcp_generate_bilingual_subtitles",
            "mcp_render_avatar_video",
            "mcp_mux_external_video",
            "mcp_restore_review_snapshot",
            "mcp_start_plan",
        }
        self.assertTrue(expected.issubset(names))

        status_res = asyncio.run(mcp.call_tool("mcp_avatar_status", {}))
        status_text = status_res.content[0].text if hasattr(status_res, "content") else str(status_res)
        parsed = json.loads(status_text)
        self.assertIn("lightweight", parsed)
        self.assertIn("sadtalker", parsed)

        self.client.post("/api/jobs", json={"job_type": "generate", "name": "studio-mcp"})
        snaps_res = asyncio.run(mcp.call_tool("mcp_list_review_snapshots", {"job_name": "studio-mcp"}))
        snaps_text = snaps_res.content[0].text if hasattr(snaps_res, "content") else str(snaps_res)
        self.assertEqual(json.loads(snaps_text), [])

        mutating_calls = [
            ("mcp_draft_script", {"job_name": "studio-mcp", "confirm": False}),
            ("mcp_generate_bilingual_subtitles", {"job_name": "studio-mcp", "confirm": False}),
            ("mcp_render_avatar_video", {"job_name": "studio-mcp", "confirm": False}),
            ("mcp_mux_external_video", {"job_name": "studio-mcp", "video_path": "a.mp4", "confirm": False}),
            ("mcp_restore_review_snapshot", {"job_name": "studio-mcp", "snap_id": "s1", "confirm": False}),
            ("mcp_start_plan", {"job_name": "studio-mcp", "confirm": False}),
        ]
        for tool_name, args in mutating_calls:
            out = asyncio.run(mcp.call_tool(tool_name, args))
            self.assertIn("需要確認", str(out), msg=f"{tool_name} lacked confirm gate")


if __name__ == "__main__":
    unittest.main()
