#!/usr/bin/env python3
"""One-click, isolated environment setup and dependency check.

Purpose:
    Lets a freshly cloned project run on any computer without touching the host's own
    Python or Node installations:
      - Python: `uv sync` creates the project-local `.venv/` with the uv-managed Python from
        `.python-version` and installs exactly what `uv.lock` says. No global pip, no sudo.
      - Node:   `pnpm install` (pnpm from corepack, version pinned by `packageManager`; Node
        version from `.nvmrc`) into each folder's own `node_modules/` (root, `gas/`, `web/`, `mobile/`);
        tools such as clasp are dev dependencies run with `pnpm exec`.

Commands:
    --install : set up Python (uv) and Node dependencies.
    --check   : report third-party imports under `[architecture] source_roots` that are not
                declared in `pyproject.toml`. It only reports; add packages with `uv add <name>`.

Usage:
    python3 scripts/agentctl.py setup --install
    python3 scripts/agentctl.py setup --check
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

# Import name -> PyPI name hints shown in `--check` output (never installed automatically; use `uv add`)
IMPORT_HINTS = {
    "bs4": "beautifulsoup4", "cv2": "opencv-python", "dotenv": "python-dotenv", "fitz": "PyMuPDF",
    "PIL": "Pillow", "sklearn": "scikit-learn", "yaml": "PyYAML", "telegram": "python-telegram-bot",
    "google": "google-* (check which Google package you use)",
}


def run(cmd: list[str]) -> int:
    """Run a command in the project root, echoing it first.

    Args:
        cmd: Command and arguments.

    Returns:
        The command's exit code.
    """
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def install_python() -> int:
    """Create/refresh the project `.venv` with uv (uv-managed Python, locked versions).

    Returns:
        Exit code of `uv sync` (0 when the project has no `pyproject.toml`, 1 when uv is missing).
    """
    if not (ROOT / "pyproject.toml").exists():
        return 0
    uv = shutil.which("uv")
    if not uv:
        print("❌ 找不到 uv。請安裝（只裝在使用者目錄，不影響系統 Python）：")
        print("   macOS:  brew install uv    或  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print("   Windows: powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
        return 1
    return run([uv, "sync", "--locked"] if (ROOT / "uv.lock").exists() else [uv, "sync"])


def node_project_dirs() -> list[Path]:
    """List folders that contain a `package.json` (root, `gas/`, `web/`, `mobile/`).

    Returns:
        Existing Node project folders.
    """
    return [d for d in (ROOT, ROOT / "gas", ROOT / "web", ROOT / "mobile") if (d / "package.json").exists()]


def node_install_command(folder: Path) -> list[str] | None:
    """Choose the install command for one Node folder (pnpm preferred, npm only for npm projects).

    Args:
        folder: Folder containing `package.json`.

    Returns:
        Command list, or None when the required package manager is missing.
    """
    uses_npm = (folder / "package-lock.json").exists() and not (folder / "pnpm-lock.yaml").exists()
    if uses_npm:
        npm = shutil.which("npm")
        return [npm, "ci"] if npm else None
    pnpm = shutil.which("pnpm")
    if not pnpm:
        return None
    return [pnpm, "install", "--frozen-lockfile"] if (folder / "pnpm-lock.yaml").exists() else [pnpm, "install"]


def install_node() -> int:
    """Install Node dependencies into each folder's own `node_modules` (never global).

    Returns:
        Highest exit code (0 when there is no Node project, 1 when pnpm/npm is missing).
    """
    codes = []
    for folder in node_project_dirs():
        print(f"[{folder.relative_to(ROOT).as_posix() or '.'}]")
        cmd = node_install_command(folder)
        if cmd is None:
            print("⚠️ 找不到 pnpm：請先 `nvm install` 並執行 `corepack enable`（不要用 npm -g 或 pnpm setup）。")
            codes.append(1)
            continue
        codes.append(subprocess.run(cmd, cwd=folder, check=False).returncode)
    return max(codes, default=0)


def declared_packages() -> set[str]:
    """Collect normalised package names declared in `pyproject.toml` and `requirements.txt`.

    Returns:
        Lower-case names with `_` replaced by `-`.
    """
    text = ""
    for name in ("pyproject.toml", "requirements.txt"):
        path = ROOT / name
        text += path.read_text(encoding="utf-8") + "\n" if path.exists() else ""
    specs = re.findall(r'"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:[<>=!~;\[].*?)?"', text)
    specs += re.findall(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", text, flags=re.M)
    return {s.lower().replace("_", "-") for s in specs}


def imported_top_level_modules(source_roots: list[Path]) -> dict[str, str]:
    """Find absolute imports used by the project's Python sources.

    Args:
        source_roots: Directories to scan.

    Returns:
        Mapping of top-level module name -> first file that imports it.
    """
    found: dict[str, str] = {}
    for base in source_roots:
        for py in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    found.setdefault(name.split(".")[0], py.relative_to(ROOT).as_posix())
    return found


def local_module_names(source_roots: list[Path]) -> set[str]:
    """List module/package names that belong to the project itself.

    Args:
        source_roots: Directories to scan.

    Returns:
        Names of packages and modules defined under the source roots (and `src/`).
    """
    names: set[str] = set()
    for base in [*source_roots, ROOT / "src"]:
        if base.is_dir():
            names.add(base.name)
            names.update(p.stem for p in base.rglob("*.py"))
            names.update(p.name for p in base.rglob("*") if p.is_dir())
    return names


def is_stdlib(name: str) -> bool:
    """Tell whether a top-level module belongs to the Python standard library.

    Uses `sys.stdlib_module_names` on Python 3.10+, and the module's install location
    on older versions.

    Args:
        name: Top-level module name, e.g. `json`.

    Returns:
        True for standard-library (or built-in) modules.
    """
    if name in getattr(sys, "stdlib_module_names", ()) or name in sys.builtin_module_names or name == "__future__":
        return True
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    origin = (spec.origin or "") if spec else ""
    stdlib_dir = sysconfig.get_paths()["stdlib"]
    return bool(origin) and origin.startswith(stdlib_dir) and "site-packages" not in origin


def check_dependencies() -> int:
    """Report third-party imports that are not declared as dependencies.

    Returns:
        0 when everything is declared, 1 otherwise.
    """
    from project_config import load_config, source_dirs  # noqa: E402

    roots = source_dirs(ROOT, load_config(ROOT))
    declared = declared_packages()
    local = local_module_names(roots)
    missing = {
        mod: where
        for mod, where in imported_top_level_modules(roots).items()
        if not is_stdlib(mod) and mod not in local and mod.lower().replace("_", "-") not in declared
    }
    if not missing:
        print("✅ 所有第三方 import 都已宣告在 pyproject.toml / requirements.txt。")
        return 0
    print("⚠️ 以下 import 尚未宣告為依賴（確認套件名稱後執行 `uv add <套件>`，不要用 pip）：")
    for mod, where in sorted(missing.items()):
        print(f"   - {mod:<16} (於 {where})  建議套件：{IMPORT_HINTS.get(mod, mod)}")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="一鍵安裝隔離環境（uv / 專案內 node_modules）與依賴檢查")
    parser.add_argument("--install", action="store_true", help="uv sync + pnpm install（全部裝在專案內）")
    parser.add_argument("--check", action="store_true", help="檢查是否有未宣告的第三方 import")
    args = parser.parse_args(argv)
    if args.check:
        return check_dependencies()
    if args.install:
        rc_py, rc_node = install_python(), install_node()
        print("✅ 環境安裝完成！" if rc_py == rc_node == 0 else "⚠️ 安裝過程有錯誤，請查看上方輸出。")
        return rc_py or rc_node
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
