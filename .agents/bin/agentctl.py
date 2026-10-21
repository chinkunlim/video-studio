#!/usr/bin/env python3
"""agentctl — the single entry point for every framework command.

Purpose:
    Agents and humans only need to remember one command. Each sub-command forwards
    its remaining arguments to the underlying script, so `agentctl commit --help`
    shows the full options of `auto_commit.py`.

Sub-commands:
    status    Handoff board, last handoff (goal / next step), recent summaries, uncommitted changes.
    pause     Leaving mid-task ("去上課"): note it on the board + WIP commit, e.g. pause "class break"
    task      Task cards: create / claim / handoff / done / list   (agent_task.py)
    commit    Attributed local commit + CHANGELOG Unreleased        (auto_commit.py)
    closeout  End-of-session: tests, session log, handoff, commit   (session-closeout skill)
    check     code-review-guard + layers + lint + type check + DB check + dependency check + tree (--evals: output quality)
    sync      Regenerate agent entry files, skills index and the directory tree
    setup     Create / check the isolated environments (uv sync, pnpm install)  (setup_env.py)
    tree      Refresh docs/architecture/PROJECT_TREE.md (--check: CI mode)     (update_tree.py)
    graph     Dependency graph + layer violations (GRAPH_REPORT.md, on demand) (build_graph.py)
    audit     Agent audit report (AGENT_AUDIT_REPORT.md, on demand)  (audit_trail.py)
    conversations  Local transcript + summary records: list / prune  (conversations.py)
    finish    Completion check; --tag releases Unreleased → vX.Y.Z   (finish.py)
    doctor    Verify / repair this computer's setup                 (doctor.py)
    update    Update framework files from the template              (update_framework.py)
    migration Legacy migration progress / acceptance (--verify)     (legacy-migration skill)

Framework scripts live in `.agents/bin/`; the project's `scripts/` folder only holds this
command's thin launcher (`scripts/agentctl.py`) plus the project's own scripts.

Usage:
    python3 scripts/agentctl.py status
    python3 scripts/agentctl.py task create "Add login API" --agent claude-code
    python3 scripts/agentctl.py commit --agent claude-code --model claude-opus-5-5
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
SCRIPTS = ROOT / ".agents" / "bin"
SKILLS = ROOT / ".agents" / "skills"
LIVE_START, LIVE_END = "<!-- LIVE_STATE_START -->", "<!-- LIVE_STATE_END -->"

FORWARDED = {
    "task": (SCRIPTS / "agent_task.py", "任務卡：create / claim / handoff / done / list"),
    "commit": (SCRIPTS / "auto_commit.py", "署名 + CHANGELOG Unreleased + 秘密掃描的本機 commit"),
    "closeout": (SKILLS / "session-closeout" / "scripts" / "closeout_runner.py", "結束對話收尾"),
    "audit": (SCRIPTS / "audit_trail.py", "更新 / 查詢 Agent 溯源報告"),
    "conversations": (SCRIPTS / "conversations.py", "本機對話紀錄：list / prune --before <日期>"),
    "finish": (SCRIPTS / "finish.py", "專案完成驗收（--tag：Unreleased → 新版本、升版、本機 tag）"),
    "doctor": (SCRIPTS / "doctor.py", "檢查並修復這台電腦的環境 (--fix)"),
    "update": (SCRIPTS / "update_framework.py", "從母版更新框架檔案 (--from <template>)"),
    "setup": (SCRIPTS / "setup_env.py", "建立 / 檢查隔離環境（--install / --check）"),
    "tree": (SCRIPTS / "update_tree.py", "更新目錄樹（--check：CI 檢查是否同步）"),
    "graph": (SCRIPTS / "build_graph.py", "依賴圖與分層違規（寫 GRAPH_REPORT.md）"),
    "migration": (SKILLS / "legacy-migration" / "scripts" / "migration_status.py", "舊專案遷移進度與驗收 (--verify)"),
}


def run_script(script: Path, args: list[str]) -> int:
    """Run a framework script with the current Python interpreter.

    Args:
        script: Script path.
        args: Arguments passed through unchanged.

    Returns:
        The script's exit code (1 when the script is not installed).
    """
    if not script.exists():
        print(f"❌ 找不到 {script.relative_to(ROOT)}（此專案可能未安裝該 skill / 腳本）", file=sys.stderr)
        return 1
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, check=False).returncode


def print_board() -> None:
    """Print the live section of `.agents/handoff/LATEST.md`."""
    handoff = ROOT / ".agents" / "handoff" / "LATEST.md"
    if not handoff.exists():
        print("（尚無交接看板 .agents/handoff/LATEST.md）")
        return
    text = handoff.read_text(encoding="utf-8")
    live = text.split(LIVE_START, 1)[-1].split(LIVE_END, 1)[0] if LIVE_START in text else text[:1500]
    print(live.strip())


def print_last_handoff() -> None:
    """Print the newest timeline entry of `LATEST.md` (last closeout / pause / handoff, shared through git)."""
    handoff = ROOT / ".agents" / "handoff" / "LATEST.md"
    text = handoff.read_text(encoding="utf-8") if handoff.exists() else ""
    timeline = text.split(LIVE_END, 1)[-1]
    entries = [e for e in timeline.split("\n### ")[1:] if e.strip()]
    if entries:
        print("\n### 🕘 上一次的交接紀錄（目標、下一步）\n")
        print("### " + entries[0].strip())


def section_of(markdown: str, title_prefix: str) -> str:
    """Return the body of the `## <title>` section whose title starts with `title_prefix`.

    Args:
        markdown: Markdown document.
        title_prefix: Beginning of the section title, e.g. `下一步`.

    Returns:
        Section body without the heading (empty when missing).
    """
    for block in markdown.split("\n## ")[1:]:
        heading, _, body = block.partition("\n")
        if heading.strip().startswith(title_prefix):
            return body.strip()
    return ""


def print_recent_sessions(limit: int = 3) -> None:
    """Print the newest local conversation summaries (`.agents/conversations/`, not in git).

    Args:
        limit: How many summaries to list.
    """
    folder = ROOT / ".agents" / "conversations"
    logs = sorted(folder.glob("*-summary.md"), reverse=True)[:limit] if folder.exists() else []
    print("\n### 🗂️ 最近的對話摘要（本機）")
    for p in logs:
        print(f"- {p.relative_to(ROOT).as_posix()}")
    if logs:
        next_steps = section_of(logs[0].read_text(encoding="utf-8"), "下一步")
        if next_steps:
            print(f"\n最新摘要的「下一步」：\n{next_steps}")
    else:
        print("- (這台電腦尚無；其他電腦的進度請看上方交接看板)")


def print_git_summary() -> None:
    """Print the current branch and the number of uncommitted files."""
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    changed = len([ln for ln in status.splitlines() if ln.strip()])
    print(f"\n### 🌿 Git：分支 `{branch or '-'}`，未提交檔案 {changed} 個")


def cmd_status() -> int:
    """Show everything an agent needs at the start of a session.

    Returns:
        Process exit code (always 0).
    """
    lock = ROOT / ".agents" / "framework.lock"
    version = json.loads(lock.read_text(encoding="utf-8")).get("framework_version", "?") if lock.exists() else "?"
    print(f"# {ROOT.name} — agentctl status (framework v{version})\n")
    print_board()
    print_last_handoff()
    print_recent_sessions()
    print_git_summary()
    print("\n👉 接手：agentctl task claim TASK-NNN --agent <名字>；新工作：agentctl task create \"標題\" --agent <名字>")
    return 0


def cmd_pause(args: list[str]) -> int:
    """Pause mid-task (class, meeting…): note it on the handoff board and make a WIP commit.

    Args:
        args: Reason words (English, used in the commit message), optionally `--agent <name>`.

    Returns:
        Exit code of the commit.
    """
    sys.path.insert(0, str(ROOT / ".agents" / "lib"))
    sys.path.insert(0, str(SCRIPTS))
    import agent_task  # type: ignore
    from project_config import resolve_agent_identity  # noqa: E402

    agent_arg = args[args.index("--agent") + 1] if "--agent" in args[:-1] else ""
    words = [w for i, w in enumerate(args) if w != "--agent" and (i == 0 or args[i - 1] != "--agent")]
    reason = " ".join(words).strip() or "pause session"
    agent = resolve_agent_identity(agent_arg, root=ROOT)[0]
    agent_task.update_handoff_file(
        event_title="Pause (暫停離席)", agent=agent,
        bullets=[f"**原因**: {reason}", "**接手**: 先執行 `python3 scripts/agentctl.py status`，從進行中的任務繼續"], root=ROOT,
    )
    rc = run_script(SCRIPTS / "auto_commit.py", ["--agent", agent, "--bump", "none", "-m", f"wip(handoff): {reason}"])
    if rc != 0:
        # Unfinished code may not pass the pre-commit checks yet; nothing is lost because the
        # work and the board note stay in this folder (agents take turns on the same machine).
        print("⏸️ 未完成的程式還沒通過檢查，所以這次沒有 commit；改動與交接看板的紀錄都保留在工作區。"
              "回來後 `agentctl status` 會列出未提交的檔案，補齊後再 commit。")
    return 0


def cmd_sync() -> int:
    """Regenerate entry files, the skills index and the directory tree.

    Returns:
        0 when every generator succeeded, otherwise 1.
    """
    results = [run_script(SCRIPTS / name, []) for name in ("sync_agent_adapters.py", "update_tree.py")]
    return 0 if all(r == 0 for r in results) else 1


def split_commands(command: str) -> list[str]:
    """Split a shell command on top-level `&&` (parenthesised sub-shells stay whole).

    Args:
        command: Command such as `uv run mypy && (cd mobile && pnpm exec tsc --noEmit)`.

    Returns:
        The parts, stripped.
    """
    parts, depth, current = [], 0, ""
    i = 0
    while i < len(command):
        ch = command[i]
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0 and command.startswith("&&", i):
            parts.append(current.strip())
            current, i = "", i + 2
            continue
        current += ch
        i += 1
    return [p for p in [*parts, current.strip()] if p]


def missing_tool_hint(part: str) -> str:
    """Tell why one command part cannot run yet (its project-local tools are not installed).

    Args:
        part: One part from `split_commands()`.

    Returns:
        A hint, or an empty string when the part can run.
    """
    if "uv run" in part and not (ROOT / ".venv").exists():
        return "尚未建立 .venv"
    if "uv run" in part:
        sys.path.insert(0, str(ROOT / ".agents" / "lib"))
        from project_config import venv_moved  # noqa: E402

        if venv_moved(ROOT):
            return "專案資料夾移動過，.venv 要重建（python3 scripts/agentctl.py doctor --fix）"
    folder = re.match(r"\(\s*cd\s+(\S+)\s*&&\s*pnpm\s", part)
    if folder and not (ROOT / folder.group(1) / "node_modules").exists():
        return f"尚未安裝 {folder.group(1)}/node_modules"
    return ""


def run_configured(name: str) -> int:
    """Run a `[commands]` entry (`lint`, `typecheck`, `dbcheck`) from `.agents/project.toml`.

    Parts whose project-local tools are missing (`uv run` without `.venv`, `(cd x && pnpm ...)`
    without `x/node_modules`) are skipped with a hint, so `check` never creates environments
    or downloads tools on its own; the other parts still run.

    Args:
        name: Key under `[commands]`.

    Returns:
        The command's exit code (0 when it is not configured or everything was skipped).
    """
    sys.path.insert(0, str(ROOT / ".agents" / "lib"))
    from project_config import load_config  # noqa: E402

    command = str(load_config(ROOT)["commands"].get(name, "")).strip()
    runnable = []
    for part in split_commands(command):
        hint = missing_tool_hint(part)
        if hint:
            fix = "" if "doctor --fix" in hint else "（先執行 python3 scripts/agentctl.py setup --install）"
            print(f"ℹ️ 略過 {name}（{part}）：{hint}{fix}")
        else:
            runnable.append(part)
    if not runnable:
        return 0
    joined = " && ".join(runnable)
    print(f"$ {joined}")
    return subprocess.run(joined, shell=True, cwd=ROOT, check=False).returncode


def cmd_check(args: list[str] | None = None) -> int:
    """Run the quality gates without committing.

    Args:
        args: Extra flags; `--evals` also runs `[commands] evals`.

    Returns:
        0 when every gate passes, otherwise 1.
    """
    results = [
        run_script(SKILLS / "code-review-guard" / "scripts" / "review_guard.py", [str(ROOT)]),
        run_script(SCRIPTS / "update_tree.py", []),  # local: refresh the tree; CI uses --check
        run_script(SCRIPTS / "build_graph.py", []),  # layer direction (report is git-ignored)
        run_configured("lint"),
        run_configured("typecheck"),
        run_configured("dbcheck"),
    ]
    if "--evals" in (args or []):
        results.append(run_configured("evals"))
    if (ROOT / "pyproject.toml").exists():
        results.append(run_script(SCRIPTS / "setup_env.py", ["--check"]))
    return 0 if all(r == 0 for r in results) else 1


def print_help() -> None:
    """Print the list of sub-commands."""
    print(__doc__.split("Usage:")[0].strip())
    print("\nUsage: python3 scripts/agentctl.py <sub-command> [options]   (<sub-command> --help for details)")


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the requested sub-command.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return 0
    command, rest = args[0], args[1:]
    if command in FORWARDED:
        return run_script(FORWARDED[command][0], rest)
    if command == "check":
        return cmd_check(rest)
    local = {"status": cmd_status, "sync": cmd_sync}
    if command in local:
        return local[command]()
    if command == "pause":
        return cmd_pause(rest)
    print(f"❌ 未知的子指令：{command}", file=sys.stderr)
    print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
