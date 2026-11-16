"""Tests for FastAPI HTTP API, security guards, static Web UI, and MCP Server."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

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
        self.assertIn("📖 OpenAPI 文件", ui.text)

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

        refused = asyncio.run(
            mcp.call_tool("mcp_init_job", {"job_type": "generate", "name": "mcp-demo", "confirm": False})
        )
        self.assertIn("需要確認", str(refused))
        self.assertFalse((self.workspace / "generate" / "mcp-demo").exists())

        accepted = asyncio.run(
            mcp.call_tool("mcp_init_job", {"job_type": "generate", "name": "mcp-demo", "confirm": True})
        )
        self.assertIn("已建立 generate/mcp-demo", str(accepted))
        self.assertTrue((self.workspace / "generate" / "mcp-demo").exists())

        listed = asyncio.run(mcp.call_tool("mcp_list_jobs", {}))
        self.assertIn("mcp-demo", str(listed))


if __name__ == "__main__":
    unittest.main()
