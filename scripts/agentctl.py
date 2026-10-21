#!/usr/bin/env python3
"""Launcher for `agentctl`, the single entry point of the agent framework.

Purpose:
    The framework's scripts live in `.agents/bin/` so this `scripts/` folder stays free
    for the project's own scripts. This file only forwards every argument to
    `.agents/bin/agentctl.py`, keeping the familiar command:

Usage:
    python3 scripts/agentctl.py status
    python3 scripts/agentctl.py --help
"""
from __future__ import annotations

from pathlib import Path
import runpy
import sys

TARGET = Path(__file__).resolve().parents[1] / ".agents" / "bin" / "agentctl.py"

if __name__ == "__main__":
    if not TARGET.exists():
        sys.exit(f"❌ 找不到 {TARGET}；請從專案模板執行 `agentctl update` 或重新安裝框架。")
    sys.argv[0] = str(TARGET)
    runpy.run_path(str(TARGET), run_name="__main__")
