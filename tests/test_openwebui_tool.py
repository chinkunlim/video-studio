"""Unit tests for Open WebUI tool adapter."""

import unittest
from unittest.mock import MagicMock, patch

from video_studio.adapters.openwebui_runner import OpenWebUIRunner, ToolValves
from video_studio.adapters.openwebui_tool import Tools


class TestOpenWebUITool(unittest.IsolatedAsyncioTestCase):
    """Test suite for Open WebUI tool adapter functionality."""

    def setUp(self) -> None:
        """Initialize tools instance with isolated valves."""
        self.tools = Tools()
        self.valves = ToolValves(
            project_dir="/tmp/fake_project",
            workspace_dir="/tmp/fake_workspace",
        )
        self.runner = OpenWebUIRunner(self.valves)

    def test_valves_default_values(self) -> None:
        """Verify default valves values are initialized properly."""
        valves = Tools.Valves()
        self.assertTrue(valves.project_dir)
        self.assertEqual(valves.voicebox_url, "http://127.0.0.1:17493")
        self.assertEqual(valves.timeout_minutes, 90)

    @patch("pathlib.Path.exists", return_value=True)
    def test_job_validation(self, mock_exists: MagicMock) -> None:
        """Test resolving job identifier returns expected name."""
        with patch.object(self.runner, "job_dirs", return_value=["generate/test-job"]):
            self.assertEqual(self.runner.resolve_job("test-job"), "test-job")
            self.assertEqual(self.runner.resolve_job("generate/test-job"), "generate/test-job")

    def test_job_not_found(self) -> None:
        """Test resolving nonexistent job raises RuntimeError."""
        with patch.object(self.runner, "job_dirs", return_value=["generate/other-job"]):
            with self.assertRaises(RuntimeError):
                self.runner.resolve_job("nonexistent")

    async def test_guard_catches_exception(self) -> None:
        """Test guard handles exceptions and returns safe error message."""

        async def failing_action() -> str:
            raise ValueError("Something went wrong")

        emitted: list[dict[str, object]] = []

        async def fake_emitter(payload: dict[str, object]) -> None:
            emitted.append(payload)

        result = await self.runner.guard(fake_emitter, failing_action)
        self.assertIn("❌ 错误", result)
        self.assertIn("Something went wrong", result)
        self.assertTrue(len(emitted) > 0)


if __name__ == "__main__":
    unittest.main()
