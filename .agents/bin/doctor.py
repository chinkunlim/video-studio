#!/usr/bin/env python3
"""Environment doctor: verify (and repair) everything a cloned project needs on this computer.

Purpose:
    Some things are per-machine and are not stored in git: the hook activation
    (`core.hooksPath`), the `.claude/skills` link, `.env`, virtual environments and
    installed tools. Run this after cloning the project on a new computer.

Checks:
    FAIL (exit 1): Python < 3.9 (for these scripts), git missing, not a git repo, hooks not
                   active, skills link missing, uv missing in a Python project, `.venv` created
                   in another folder (project moved; `--fix` rebuilds it from uv.lock).
    WARN         : git user.name/email unset, `.env` missing, `.venv` missing or not on the
                   `.python-version` Python, no `uv.lock`, `node_modules` / `.clasp.json`
                   missing, go / cargo missing, no framework lock.
    Host hygiene (read-only, WARN): `package.json` / `node_modules` in the home folder,
                   root-owned files in `~/.cache/uv`, `PNPM_HOME` (second pnpm), gh not logged in.
    Nothing is ever installed globally; fixes only touch this project.

Usage:
    python3 scripts/agentctl.py doctor          # report only
    python3 scripts/agentctl.py doctor --fix    # also activate hooks, rebuild skill links, create .env, create DATA_DIR,
                                                # rebuild .venv after the project folder was moved
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import load_config, venv_moved  # noqa: E402

HOOKS_DIR = ".agents/hooks"


def git(*args: str) -> str:
    """Run a git command in the project root.

    Args:
        *args: Arguments after `git`.

    Returns:
        Trimmed standard output (empty on failure).
    """
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def check_python() -> tuple[str, str]:
    """Check the Python interpreter version.

    Returns:
        Tuple of status (`OK` / `FAIL`) and message.
    """
    version = ".".join(map(str, sys.version_info[:3]))
    label = f"框架腳本使用 Python {version}（只用內建模組，不安裝任何套件；專案程式用 .venv）"
    return ("OK", label) if sys.version_info >= (3, 9) else ("FAIL", f"框架腳本需要 Python 3.9 以上（目前 {version}）")


def check_git(fix: bool) -> list[tuple[str, str]]:
    """Check git, the repository, the user identity and the versioned hooks.

    Args:
        fix: Activate `core.hooksPath` and make hooks executable when needed.

    Returns:
        List of `(status, message)` results.
    """
    if not shutil.which("git"):
        return [("FAIL", "git 未安裝")]
    if not git("rev-parse", "--is-inside-work-tree"):
        return [("FAIL", "不是 git repo（請在專案根目錄執行，或 git init）")]
    results = [("OK", "git repo")]
    identity = git("config", "user.name") and git("config", "user.email")
    results.append(("OK", "git user.name / user.email 已設定") if identity else ("WARN", "請設定 git config --global user.name / user.email"))
    hooks_ok = git("config", "core.hooksPath") == HOOKS_DIR
    if not hooks_ok and fix and (ROOT / HOOKS_DIR).is_dir():
        git("config", "core.hooksPath", HOOKS_DIR)
        for hook in (ROOT / HOOKS_DIR).iterdir():
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        hooks_ok = True
    results.append(("OK", f"git hooks 已啟用 ({HOOKS_DIR})") if hooks_ok else ("FAIL", "git hooks 未啟用（執行 doctor --fix）"))
    return results


def check_skill_links(fix: bool) -> list[tuple[str, str]]:
    """Check that every configured skill link (e.g. `.claude/skills`) exists.

    Args:
        fix: Rebuild links (and agent entry files) with `sync_agent_adapters.py`.

    Returns:
        List of `(status, message)` results.
    """
    link_dirs = load_config(ROOT)["agents"].get("skill_link_dirs", [])
    missing = [d for d in link_dirs if not (ROOT / d / "catalog.json").exists() and not any((ROOT / d).glob("*/SKILL.md"))]
    if missing and fix:
        subprocess.run([sys.executable, str(ROOT / ".agents" / "bin" / "sync_agent_adapters.py")], cwd=ROOT, check=False, capture_output=True)
        missing = [d for d in missing if not any((ROOT / d).glob("*/SKILL.md"))]
    if missing:
        return [("FAIL", f"skills 連結不存在：{', '.join(missing)}（執行 doctor --fix）")]
    return [("OK", f"skills 連結：{', '.join(link_dirs) or '(未設定)'}")]


DATA_SUBDIRS = ("input", "output", "needs_review", "state", "db", "logs")
IN_PROJECT_DATA = ("data", "input", "output")


PROJECT_FILE_WINS = ("DATA_DIR",)  # same rule as config/settings.py: the project's .env beats the shell


def file_value(name: str, key: str) -> str:
    """Read one key from a project env file.

    Args:
        name: `.env` or `.env.example`.
        key: Variable name.

    Returns:
        The value, or an empty string.
    """
    path = ROOT / name
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        k, _, v = line.partition("=")
        if k.strip() == key and v.strip():
            return v.strip().strip("\"'")
    return ""


def env_value(key: str) -> str:
    """Read a setting the way the project does: environment, then `.env`, then `.env.example`.

    For keys in `PROJECT_FILE_WINS` the project's `.env` comes first, so a variable inherited
    from the shell (e.g. Open WebUI's `DATA_DIR`) cannot redirect the project.

    Args:
        key: Variable name, e.g. `DATA_DIR`.

    Returns:
        The value, or an empty string when it is not defined anywhere.
    """
    if key in PROJECT_FILE_WINS and file_value(".env", key):
        return file_value(".env", key)
    return os.environ.get(key) or file_value(".env", key) or file_value(".env.example", key)


def check_data_dir(fix: bool) -> list[tuple[str, str]]:
    """Check that project data lives in `DATA_DIR`, outside the project folder.

    Args:
        fix: Create `DATA_DIR` and its standard sub-folders when missing.

    Returns:
        List of `(status, message)` results (empty for projects without `DATA_DIR`).
    """
    raw = env_value("DATA_DIR")
    if not raw:
        return []
    inherited = os.environ.get("DATA_DIR", "")
    ignored = [("OK", f"已忽略終端機的 DATA_DIR={inherited}（例如 Open WebUI 設定的），使用專案 .env 的設定")] \
        if inherited and file_value(".env", "DATA_DIR") and inherited != raw else []
    data_dir = Path(raw).expanduser()
    data_dir = (data_dir if data_dir.is_absolute() else ROOT / data_dir).resolve()  # relative = from the project folder
    results = []
    if data_dir == ROOT or ROOT in data_dir.parents:
        results.append(("WARN", f"DATA_DIR 在專案資料夾內（{data_dir}）：資料應放在專案外，例如 ../../projects-data/{ROOT.name}"))
    if not data_dir.exists() and fix:
        for sub in DATA_SUBDIRS:
            (data_dir / sub).mkdir(parents=True, exist_ok=True)
    if not data_dir.exists():
        results.append(("WARN", f"DATA_DIR 不存在：{data_dir}（執行 doctor --fix 建立）"))
    elif not os.access(data_dir, os.W_OK):
        results.append(("FAIL", f"DATA_DIR 無法寫入：{data_dir}"))
    else:
        results.append(("OK", f"資料資料夾：{data_dir}（與程式分開）"))
    stray = [n for n in IN_PROJECT_DATA if (ROOT / n).is_dir() and any(p.is_file() for p in (ROOT / n).rglob("*"))]
    if stray:
        results.append(("WARN", f"專案內有資料資料夾 {', '.join(stray)}/：請搬到 DATA_DIR（{data_dir}）"))
    return ignored + results


def check_env_file(fix: bool) -> list[tuple[str, str]]:
    """Check that `.env` exists wherever a `.env.example` is provided (project root, `mobile/`).

    Args:
        fix: Copy `.env.example` to `.env` (values stay empty; fill them in yourself).

    Returns:
        List of `(status, message)` results.
    """
    results = []
    for folder in (ROOT, ROOT / "mobile"):
        example, env = folder / ".env.example", folder / ".env"
        rel = (env.relative_to(ROOT).as_posix())
        if not example.exists():
            continue
        if env.exists():
            results.append(("OK", f"{rel} 已存在"))
        elif fix:
            shutil.copy2(example, env)
            results.append(("WARN", f"已由 .env.example 建立 {rel}，請填入實際值"))
        else:
            results.append(("WARN", f"{rel} 不存在（執行 agentctl doctor --fix，或 cp {rel}.example {rel}）"))
    return results or [("OK", "不需要 .env")]


def venv_python_version() -> str:
    """Read the Python version of the project `.venv` from `pyvenv.cfg`.

    Returns:
        Version such as `3.11.17`, or an empty string when there is no `.venv`.
    """
    cfg = ROOT / ".venv" / "pyvenv.cfg"
    if not cfg.exists():
        return ""
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("version_info", "version"):
            return value.strip()
    return ""


def check_python_env(fix: bool = False) -> list[tuple[str, str]]:
    """Check the isolated Python environment (uv + project `.venv` + pinned version).

    Args:
        fix: Rebuild `.venv` from `uv.lock` when the project folder was moved.

    Returns:
        List of `(status, message)` results (empty for projects without `pyproject.toml`).
    """
    if not (ROOT / "pyproject.toml").exists():
        return []
    if not shutil.which("uv"):
        return [("FAIL", "uv 未安裝（Python 專案一律用 uv；brew install uv 或官方安裝腳本，不要用全域 pip）")]
    results = [("OK", "uv 已安裝")]
    if venv_moved(ROOT):
        if not fix:
            results.append(("FAIL", "專案資料夾移動過，.venv 裡的工具還指向舊位置（執行 agentctl doctor --fix 重建 .venv）"))
        else:
            shutil.rmtree(ROOT / ".venv")
            synced = subprocess.run(["uv", "sync"] + (["--locked"] if (ROOT / "uv.lock").exists() else []), cwd=ROOT,
                                    capture_output=True, text=True, check=False)
            results.append(("OK", "專案資料夾移動過：已依 uv.lock 重建 .venv") if synced.returncode == 0
                           else ("FAIL", f"重建 .venv 失敗：{synced.stderr.strip()[-200:]}"))
    pinned_file = ROOT / ".python-version"
    pinned = pinned_file.read_text(encoding="utf-8").strip() if pinned_file.exists() else ""
    actual = venv_python_version()
    if not actual:
        results.append(("WARN", "尚未建立 .venv（執行 python3 scripts/agentctl.py setup --install）"))
    elif pinned and not actual.startswith(pinned):
        results.append(("WARN", f".venv 是 Python {actual}，但 .python-version 指定 {pinned}（刪除 .venv 後執行 uv sync）"))
    else:
        results.append(("OK", f".venv 使用 Python {actual}（專案內，與主機隔離）"))
    if not (ROOT / "uv.lock").exists():
        results.append(("WARN", "缺少 uv.lock（執行 uv lock 並 commit，確保每台電腦版本一致）"))
    return results


def check_node_env() -> list[tuple[str, str]]:
    """Check Node, project-local `node_modules`, and clasp setup for GAS folders.

    Returns:
        List of `(status, message)` results.
    """
    folders = [d for d in (ROOT, ROOT / "gas", ROOT / "web", ROOT / "mobile") if (d / "package.json").exists()]
    if not folders:
        return []
    results = [check_node_version(), check_pnpm()]
    for folder in folders:
        name = folder.relative_to(ROOT).as_posix() or "."
        if not (folder / "node_modules").exists():
            results.append(("WARN", f"{name}: 尚未安裝 node_modules（執行 python3 scripts/agentctl.py setup --install）"))
        if (folder / "appsscript.json").exists() and not (folder / ".clasp.json").exists():
            results.append(("WARN", f"{name}: 缺少 .clasp.json（pnpm exec clasp login 後，cp .clasp.json.example .clasp.json 並填入指令碼 ID）"))
    return results


def check_mobile_tools() -> list[tuple[str, str]]:
    """Check the simulators an Expo app in `mobile/` needs (read-only; never installs).

    Returns:
        List of `(status, message)` results (empty when the project has no mobile app).
    """
    if not (ROOT / "mobile" / "app.json").exists():
        return []
    results = []
    xcode = tool_output("xcode-select", "-p")
    has_simctl = subprocess.run(["xcrun", "simctl", "help"], capture_output=True, check=False).returncode == 0
    if has_simctl:
        results.append(("OK", f"iOS Simulator 可用（{xcode}）"))
    else:
        results.append(("WARN", "沒有 iOS Simulator：從 App Store 安裝 Xcode，打開一次同意授權，"
                                "再執行 sudo xcode-select -s /Applications/Xcode.app（需要你自己輸入密碼）"))
    sdk = Path(os.environ.get("ANDROID_HOME", "") or Path.home() / "Library" / "Android" / "sdk")
    if shutil.which("adb") or (sdk / "platform-tools" / "adb").exists():
        results.append(("OK", f"Android SDK 可用（{sdk}）"))
    else:
        results.append(("WARN", "沒有 Android SDK：brew bundle --file Brewfile 安裝 Android Studio，打開後用 Device Manager 建立模擬器"))
    return results


def tool_output(*cmd: str) -> str:
    """Run a command and return its trimmed output.

    Args:
        *cmd: Command and arguments.

    Returns:
        Standard output, or an empty string when the tool is missing or fails.
    """
    if not shutil.which(cmd[0]):
        return ""
    res = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def check_node_version() -> tuple[str, str]:
    """Compare the active Node major version with `.nvmrc`.

    Returns:
        Tuple of status and message.
    """
    current = tool_output("node", "-v").lstrip("v")
    if not current:
        return ("WARN", "node 未安裝：用 nvm 安裝（nvm install）")
    nvmrc = ROOT / ".nvmrc"
    wanted = nvmrc.read_text(encoding="utf-8").strip() if nvmrc.exists() else ""
    if wanted and wanted[0].isdigit() and current.split(".")[0] != wanted.split(".")[0]:
        return ("WARN", f"node {current} 與 .nvmrc ({wanted}) 不同：在專案內執行 nvm use（或 nvm install）")
    return ("OK", f"node {current}" + (f"（符合 .nvmrc {wanted}）" if wanted else ""))


def check_pnpm() -> tuple[str, str]:
    """Check that pnpm is available and comes from corepack/nvm (not a second global copy).

    Returns:
        Tuple of status and message.
    """
    path = shutil.which("pnpm")
    if not path:
        return ("WARN", "pnpm 未啟用：執行 corepack enable（不要用 npm -g 或 pnpm setup）")
    if "PNPM_HOME" in os.environ:
        return ("WARN", f"偵測到 PNPM_HOME（{path}）：可能有第二份 pnpm，請移除 pnpm setup 寫入的設定")
    return ("OK", f"pnpm {tool_output('pnpm', '-v')}（{path}）")


def check_host_hygiene() -> list[tuple[str, str]]:
    """Read-only checks that the host environment is not polluted (never changes anything).

    Returns:
        List of `(status, message)` results.
    """
    home = Path.home()
    results = []
    stray = [n for n in ("package.json", "node_modules", "pnpm-lock.yaml") if (home / n).exists()]
    results.append(("WARN", f"家目錄有 {', '.join(stray)}：會影響 Node 工具判斷，請移除") if stray else ("OK", "家目錄沒有 package.json / node_modules"))
    uv_cache = home / ".cache" / "uv"
    if uv_cache.exists():
        root_owned = tool_output("find", str(uv_cache), "-maxdepth", "3", "-user", "root", "-print", "-quit")
        results.append(("WARN", f"~/.cache/uv 有 root 擁有的檔案（曾用 sudo uvx？）：sudo chown -R \"$(id -un)\" ~/.cache/uv") if root_owned else ("OK", "~/.cache/uv 權限正常"))
    if shutil.which("gh"):
        logged_in = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False).returncode == 0
        results.append(("OK", "gh 已登入") if logged_in else ("WARN", "gh 未登入：gh auth login（push / PR 需要）"))
    return results


def check_brewfile() -> tuple[str, str]:
    """Check that every system tool listed in the project's `Brewfile` is installed (never installs).

    Returns:
        Tuple of status and message.
    """
    brewfile = ROOT / "Brewfile"
    if not brewfile.exists():
        return ("OK", "沒有 Brewfile（專案不需要額外的系統工具）")
    if not shutil.which("brew"):
        return ("WARN", "專案有 Brewfile，但找不到 brew")
    res = subprocess.run(["brew", "bundle", "check", "--file", str(brewfile)], capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return ("OK", "Brewfile 列出的系統工具都已安裝")
    return ("WARN", "Brewfile 有工具尚未安裝：brew bundle --file Brewfile")


def check_toolchain(fix: bool = False) -> list[tuple[str, str]]:
    """Check language tools and the framework lock.

    Args:
        fix: Apply repairs that only touch this project (rebuild a moved `.venv`).

    Returns:
        List of `(status, message)` results.
    """
    results = [*check_python_env(fix), *check_node_env(), *check_mobile_tools()]
    results.append(check_brewfile())
    for marker, tool, hint in (("go.mod", "go", "需要 Go"), ("Cargo.toml", "cargo", "需要 Rust (cargo)")):
        if (ROOT / marker).exists():
            results.append(("OK", f"{tool} 已安裝") if shutil.which(tool) else ("WARN", f"{tool} 未安裝：{hint}"))
    lock = ROOT / ".agents" / "framework.lock"
    if (ROOT / "scripts" / "init_project.py").exists() and (ROOT / ".agents" / "lib" / "framework_install.py").exists():
        results.append(("OK", "這是母版：框架檔案就是來源，不需要 framework.lock"))
    else:
        results.append(("OK", "framework.lock 存在") if lock.exists() else ("WARN", "缺少 .agents/framework.lock（舊版專案，執行 agentctl update 後產生）"))
    return results


def run_checks(fix: bool) -> list[tuple[str, str]]:
    """Run every check in order.

    Args:
        fix: Apply automatic repairs where possible.

    Returns:
        All `(status, message)` results.
    """
    return [
        check_python(), *check_git(fix), *check_skill_links(fix), *check_env_file(fix), *check_data_dir(fix),
        *check_toolchain(fix), *check_host_hygiene(),
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the doctor report.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        1 when any check FAILs, else 0.
    """
    parser = argparse.ArgumentParser(description="檢查（並修復）這台電腦上的專案環境")
    parser.add_argument("--fix", action="store_true", help="自動修復：啟用 hooks、重建 skills 連結、建立 .env")
    args = parser.parse_args(argv)
    icons = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}
    results = run_checks(args.fix)
    print(f"🩺 Doctor — {ROOT.name} ({sys.platform})")
    for status, message in results:
        print(f"  {icons[status]} {message}")
    failed = any(s == "FAIL" for s, _ in results)
    if failed and not args.fix:
        print("\n👉 執行 `python3 scripts/agentctl.py doctor --fix` 自動修復。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
