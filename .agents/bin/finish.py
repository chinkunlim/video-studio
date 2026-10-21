#!/usr/bin/env python3
"""Project completion check ("專案完成了"): verify the project is ready to hand over or archive.

Purpose:
    The counterpart of `init` and `migrate`: before calling a project done, check that the
    code, documents and records are complete, then optionally tag the release locally.

Checks:
    1. `agentctl check` passes (and `--evals` when `[commands] evals` is configured).
    2. The test command passes.
    3. No task card is still open / in progress / handed off.
    4. README.md and docs/architecture/ARCHITECTURE.md were written for this project.
    5. CHANGELOG.md has entries beyond the initial scaffold.
    6. The working tree is clean (everything committed).
    With `--tag` (only when every check passes) it also releases: the `## [Unreleased]`
    entries become `## [X.Y.Z] - date` (minor when something was Added, otherwise patch;
    override with `--bump`), the version files are bumped, a `chore(release)` commit is made
    and an annotated tag `vX.Y.Z` is created locally (never pushed).
    Reminders (not failures): unpushed commits, DATA_DIR backup, local conversation records
    that can be deleted with `agentctl conversations prune`.

Usage:
    python3 scripts/agentctl.py finish
    python3 scripts/agentctl.py finish --tag                 # release Unreleased → vX.Y.Z and tag (local only)
    python3 scripts/agentctl.py finish --tag --bump major
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import (  # noqa: E402
    bump_semver,
    load_config,
    read_version,
    release_bump,
    release_unreleased,
    resolve_agent_identity,
    unreleased_entries,
    write_version,
)

TEMPLATE_MARKERS = {
    "README.md": "AI-assisted software project with standard structure and agent handoff.",
    "docs/architecture/ARCHITECTURE.md": "TODO: 用幾句話或一張圖說明主要元件",
}


def sh(cmd: list[str] | str) -> subprocess.CompletedProcess:
    """Run a command in the project root.

    Args:
        cmd: Argument list, or a shell string (for configured commands).

    Returns:
        The completed process (output is shown to the user).
    """
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), check=False)


def git(*args: str) -> str:
    """Run git quietly.

    Args:
        *args: Arguments after `git`.

    Returns:
        Trimmed standard output.
    """
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def open_tasks() -> list[str]:
    """List task cards that are not done.

    Returns:
        `TASK-NNN (status)` strings.
    """
    folder = ROOT / ".agents" / "tasks"
    items = []
    for f in sorted(folder.glob("TASK-*.json")) if folder.exists() else []:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("status") != "done":
            items.append(f"{data.get('id')} ({data.get('status')})")
    return items


def run_checks(config: dict) -> list[tuple[bool, str]]:
    """Evaluate every completion criterion.

    Args:
        config: Loaded project configuration.

    Returns:
        `(passed, description)` pairs.
    """
    commands = config["commands"]
    check_args = ["--evals"] if commands.get("evals") else []
    test = str(commands.get("test", "")).strip()
    untouched = [rel for rel, marker in TEMPLATE_MARKERS.items() if (ROOT / rel).exists() and marker in (ROOT / rel).read_text(encoding="utf-8")]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if (ROOT / "CHANGELOG.md").exists() else ""
    tasks = open_tasks()
    dirty = git("status", "--porcelain")
    return [
        (sh([sys.executable, "scripts/agentctl.py", "check", *check_args]).returncode == 0, "agentctl check 通過" + ("（含 evals）" if check_args else "")),
        (not test or sh(test).returncode == 0, f"測試通過（{test or '未設定'}）"),
        (not tasks, "任務卡都已完成" + (f"：未完成 {', '.join(tasks)}" if tasks else "")),
        (not untouched, "README / ARCHITECTURE 已改寫" + (f"：尚未改寫 {', '.join(untouched)}" if untouched else "")),
        (bool(unreleased_entries(changelog)) or changelog.count("## [") > 2, "CHANGELOG.md 有實際的變更紀錄"),
        (not dirty, "所有變更都已 commit"),
    ]


def reminders(config: dict) -> list[str]:
    """Collect follow-ups that are the user's decision.

    Args:
        config: Loaded project configuration.

    Returns:
        Reminder lines.
    """
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    unpushed = git("log", f"{upstream}..HEAD", "--oneline") if upstream else git("log", "--oneline")
    count = len([ln for ln in unpushed.splitlines() if ln.strip()])
    conv = ROOT / ".agents" / "conversations"
    records = len(list(conv.glob("*.md"))) if conv.exists() else 0
    lines = [f"未推送 commit：{count} 個（要推送請先確認，再 ALLOW_PUSH=1 git push）"]
    lines.append("備份資料資料夾 DATA_DIR（不在 git 裡）")
    if records:
        lines.append(f"本機對話紀錄 {records} 個檔案：確認不再需要後 `agentctl conversations prune --before <日期>`")
    return lines


def release(config: dict, bump: str) -> str:
    """Turn `## [Unreleased]` into a version, bump version files, commit and tag locally.

    Args:
        config: Loaded project configuration.
        bump: `auto` (minor when something was Added, otherwise patch), `patch`, `minor` or `major`.

    Returns:
        The new version tag such as `v0.2.0`.
    """
    changelog_file = ROOT / "CHANGELOG.md"
    text = changelog_file.read_text(encoding="utf-8") if changelog_file.exists() else "# Changelog\n"
    level = release_bump(unreleased_entries(text)) if bump == "auto" else bump
    version = bump_semver(read_version(ROOT, config), level)
    changelog_file.write_text(release_unreleased(text, version, date.today().isoformat()), encoding="utf-8")
    written = [p.relative_to(ROOT).as_posix() for p in write_version(ROOT, config, version)]
    agent, model = resolve_agent_identity("", "", root=ROOT)
    trailers = [f"Agent: {agent}"] + ([f"Model: {model}"] if model else []) + [f"Version: v{version}"]
    safe_agent = re.sub(r"[^a-zA-Z0-9_.-]", "-", agent)
    trailers.append(f"Co-Authored-By: {agent} <agent+{safe_agent}@local>")
    message = f"chore(release): v{version} [agent:{agent}]\n\n" + "\n".join(trailers)
    sh(["git", "add", "--", "CHANGELOG.md", *written])
    sh(["git", "commit", "-q", "-m", message])
    sh(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])
    return f"v{version}"


def main(argv: list[str] | None = None) -> int:
    """Print the completion report and optionally tag the release.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        0 when every check passes, otherwise 1.
    """
    parser = argparse.ArgumentParser(description="專案完成驗收（交付或封存前）")
    parser.add_argument("--tag", action="store_true", help="全部通過後發布：Unreleased → vX.Y.Z、升版、commit、打本機 tag")
    parser.add_argument("--bump", choices=["auto", "patch", "minor", "major"], default="auto",
                        help="發布的升版幅度（auto：有 Added 就 minor，否則 patch）")
    args = parser.parse_args(argv)
    config = load_config(ROOT)
    results = run_checks(config)
    print("\n🧾 專案完成驗收")
    for passed, desc in results:
        print(f"  {'✅' if passed else '❌'} {desc}")
    for line in reminders(config):
        print(f"  💡 {line}")
    ok = all(p for p, _ in results)
    if ok and args.tag:
        print(f"🏷️ 已發布並建立本機 tag {release(config, args.bump)}（未推送）")
    print("🎉 專案可以交付 / 封存。" if ok else "⏳ 尚未完成，請依 ❌ 項目處理。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
