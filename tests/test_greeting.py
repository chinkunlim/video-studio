"""Unit tests for the starter greeting service and CLI."""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from video_studio.config.settings import AppConfig  # noqa: E402
from video_studio.domain.models import GreetingRequest  # noqa: E402
from video_studio.entrypoints.cli import main  # noqa: E402
from video_studio.services.greeting import create_greeting  # noqa: E402


class GreetingServiceTest(unittest.TestCase):
    """Behaviour of `create_greeting` and the CLI."""

    def test_returns_expected_message(self) -> None:
        """A normal name is greeted and the environment is passed through."""
        cfg = AppConfig(app_env="test", log_level="DEBUG", timeout_seconds=5)
        result = create_greeting(GreetingRequest(user_name="Alice"), cfg)
        self.assertEqual(result.message, "Hello, Alice!")
        self.assertEqual(result.environment, "test")

    def test_blank_name_falls_back_to_world(self) -> None:
        """A blank name produces the default greeting."""
        result = create_greeting(GreetingRequest(user_name="   "), AppConfig(app_env="test"))
        self.assertEqual(result.message, "Hello, World!")

    def test_cli_prints_greeting(self) -> None:
        """The CLI prints the greeting and exits with 0 (no log file is written during tests)."""
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"LOG_TO_FILE": "false"}), redirect_stdout(out):
            code = main(["--name", "Bob"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "Hello, Bob!")


if __name__ == "__main__":
    unittest.main()
