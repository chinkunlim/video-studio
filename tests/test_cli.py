"""單元測試：命令列介面 (CLI) 入口點。

測試 entrypoints/cli.py 的命令解析與分發：
- video-studio --help
- video-studio job list
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from video_studio.entrypoints import cli


class TestCLIEntrypoints(unittest.TestCase):
    """測試 CLI 指令解析與執行。"""

    def test_parser_construction(self) -> None:
        """測試 ArgumentParser 能正確建立並包含主要子命令。"""
        parser = cli.build_parser()
        subparsers_actions = [
            action
            for action in parser._actions
            if isinstance(action, unittest.mock.MagicMock) or action.__class__.__name__ == "_SubParsersAction"
        ]
        self.assertTrue(len(subparsers_actions) > 0)

    def test_cli_job_list(self) -> None:
        """測試 job list 子命令呼叫。"""
        with patch("sys.argv", ["video-studio", "job", "list"]):
            ret = cli.main()
            self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
