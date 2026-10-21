#!/usr/bin/env python3
"""TDD helper: create a failing test (RED) with a fixture, then run the project's tests.

Purpose:
    Enforces "no production code without a failing test first" (adapted from
    obra/superpowers test-driven-development):
      `--new-test <name>` writes a fixture and a test that fails on purpose, so the agent
      sees RED before implementing; `--verify` runs the project's configured test command.

Layout (matches the language starters):
    Python : tests/test_<name>.py (unittest)          + tests/fixtures/<name>_sample.<ext>
    Node   : test/<name>.test.cjs (node:test, works in ESM and CommonJS projects)
             + test/fixtures/<name>_sample.<ext>

Usage:
    python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py --new-test price_parser
    python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py --verify
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

PY_TEST = '''"""RED-phase test for `{name}`: replace the failure with real assertions."""

from __future__ import annotations

import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "{fixture}"


class {cls}Test(unittest.TestCase):
    """Behaviour of `{name}`."""

    def test_{name}_red_phase(self) -> None:
        """Fails until `{name}` is implemented (TDD RED phase)."""
        self.assertTrue(FIXTURE.read_text(encoding="utf-8"))
        self.fail("TDD RED: `{name}` is not implemented yet")


if __name__ == "__main__":
    unittest.main()
'''

NODE_TEST = '''/**
 * @file RED-phase test for `{name}`: replace the failure with real assertions.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const FIXTURE = path.join(__dirname, "fixtures", "{fixture}");

test("{name} (TDD RED phase)", () => {{
  assert.ok(fs.readFileSync(FIXTURE, "utf8").length > 0);
  assert.fail("TDD RED: `{name}` is not implemented yet");
}});
'''

SAMPLES = {"json": '{\n  "status": "ok",\n  "sample": true\n}\n', "html": "<html><body>Sample</body></html>\n"}


def find_root() -> Path:
    """Locate the project root (folder containing `.agents/project.toml`).

    Returns:
        The project root, or the current working directory when none is found.
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return current


def detect_stack(root: Path) -> str:
    """Decide whether to generate a Python or a Node test.

    Args:
        root: Project root.

    Returns:
        `python` when `pyproject.toml` exists, otherwise `node`.
    """
    return "python" if (root / "pyproject.toml").exists() else "node"


def scaffold_tdd_test(root: Path, name: str, fixture_ext: str = "json") -> list[Path]:
    """Create a fixture and a failing test for `name` (existing files are kept).

    Args:
        root: Project root.
        name: Feature or bug name, e.g. `price_parser`.
        fixture_ext: Fixture file extension (`json`, `html`, `xml`, `txt`).

    Returns:
        Paths of the fixture and the test file.
    """
    clean = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_") or "feature"
    is_python = detect_stack(root) == "python"
    test_dir = root / ("tests" if is_python else "test")
    fixture = test_dir / "fixtures" / f"{clean}_sample.{fixture_ext}"
    if is_python:
        test_file = test_dir / f"test_{clean}.py"
        content = PY_TEST.format(name=clean, fixture=fixture.name, cls="".join(p.title() for p in clean.split("_")))
    else:
        test_file = test_dir / f"{clean}.test.cjs"
        content = NODE_TEST.format(name=clean, fixture=fixture.name)
    for path, text in ((fixture, SAMPLES.get(fixture_ext, "sample\n")), (test_file, content)):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return [fixture, test_file]


def run_test_suite(root: Path) -> int:
    """Run `[commands] test` from `.agents/project.toml` (or a sensible default).

    Args:
        root: Project root.

    Returns:
        The test command's exit code.
    """
    lib = root / ".agents" / "lib"
    command = ""
    if (lib / "project_config.py").exists():
        sys.path.insert(0, str(lib))
        import project_config  # type: ignore

        command = str(project_config.load_config(root)["commands"].get("test", "")).strip()
    if not command:
        command = "uv run python -m unittest discover -s tests -v" if detect_stack(root) == "python" else "node --test"
    print(f"$ {command}")
    return subprocess.run(command, shell=True, cwd=root, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="TDD 工具：建立失敗測試 (RED) 與執行測試")
    parser.add_argument("--new-test", help="建立指定名稱的失敗測試與 fixture")
    parser.add_argument("--fixture-ext", default="json", choices=["json", "html", "xml", "txt"], help="Fixture 副檔名")
    parser.add_argument("--verify", action="store_true", help="執行專案測試指令")
    args = parser.parse_args(argv)
    root = find_root()
    if args.new_test:
        for path in scaffold_tdd_test(root, args.new_test, args.fixture_ext):
            print(f"✅ {path.relative_to(root)}")
        print("👉 先執行 --verify 確認測試失敗 (RED)，再寫最小實作讓它通過 (GREEN)。")
        return 0
    return run_test_suite(root)


if __name__ == "__main__":
    raise SystemExit(main())
