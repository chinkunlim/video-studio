#!/usr/bin/env python3
"""End-of-session closeout: verify, record what happened, and commit.

Purpose:
    When the user says "結束對話" / "收工" / "wrap up", the active agent runs this script
    so the next agent (or the same user on another computer) can continue without
    re-reading the whole conversation.

Steps:
    1. Run the configured test command (`[commands] test` in `.agents/project.toml`)
       and `code-review-guard` — stop if either fails.
    2. Refresh generated docs: agent adapters, directory tree, dependency graph.
    3. Write the local conversation record (git-ignored, deletable when the project ends):
       `.agents/conversations/YYYY-MM-DD-HHMM-<agent>-transcript.md` (full, secrets masked) and
       `...-summary.md` (goal, decisions, errors and root causes, next steps, changed files).
    4. Append a closeout entry to `.agents/handoff/LATEST.md` (in git): one line each for goal,
       errors and next step, so another computer still knows where things stand.
    5. Commit via `.agents/bin/auto_commit.py --closeout` (limited to the agent's active task
       when exactly one is in progress) and refresh the audit report.

Usage:
    python3 .agents/skills/session-closeout/scripts/closeout_runner.py --agent claude-code \
        --goal "Add login API" --decisions "Use JWT; see ADR-002" \
        --issues "Timeout in test: fixture clock not frozen -> fixed" --next "Add refresh token"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[4]


def find_root() -> Path:
    """Locate the project root (script location first, then the working directory).

    Returns:
        The directory containing `.agents/project.toml`.
    """
    if (SCRIPT_ROOT / ".agents" / "project.toml").exists():
        return SCRIPT_ROOT
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return current


def load_lib(root: Path):
    """Import the project's `project_config` module from `.agents/lib`.

    Args:
        root: Project root directory.

    Returns:
        The imported module, or None when the framework library is missing.
    """
    lib_dir = root / ".agents" / "lib"
    if not lib_dir.exists():
        return None
    sys.path.insert(0, str(lib_dir))
    import project_config  # type: ignore

    return project_config


def run_tests(root: Path, cfg: dict) -> int:
    """Run the project's configured test command (or a sensible default).

    The command comes from `.agents/project.toml` and is executed through the shell so
    chains such as `a && b` work; it is printed first so the user sees what runs.

    Args:
        root: Project root directory.
        cfg: Loaded project configuration.

    Returns:
        The test command's exit code (0 when no tests are configured).
    """
    configured = str(cfg.get("commands", {}).get("test", "")).strip()
    if configured:
        print(f"$ {configured}")
        return subprocess.run(configured, shell=True, cwd=root, check=False).returncode
    if (root / "pyproject.toml").exists():
        return subprocess.run(["uv", "run", "python", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root).returncode
    if (root / "package.json").exists():
        return subprocess.run(["pnpm", "test"], cwd=root, check=False).returncode
    return 0


def run_review_guard(root: Path) -> int:
    """Run the code-review-guard skill when it is installed.

    Args:
        root: Project root directory.

    Returns:
        The guard's exit code (0 when the skill is not installed).
    """
    guard = root / ".agents" / "skills" / "code-review-guard" / "scripts" / "review_guard.py"
    if not guard.exists():
        return 0
    return subprocess.run([sys.executable, str(guard), str(root)], cwd=root, check=False).returncode


def refresh_generated_docs(root: Path) -> None:
    """Regenerate the agent entry files and the directory tree.

    Args:
        root: Project root directory.
    """
    for name in ("sync_agent_adapters.py", "update_tree.py"):
        script = root / ".agents" / "bin" / name
        if script.exists():
            subprocess.run([sys.executable, str(script)], cwd=root, check=False)


def active_task_of(root: Path, agent: str) -> str:
    """Return the single in-progress task owned by `agent`, if there is exactly one.

    Args:
        root: Project root directory.
        agent: Agent name.

    Returns:
        Task ID such as `TASK-003`, or an empty string.
    """
    folder = root / ".agents" / "tasks"
    owned = []
    for f in sorted(folder.glob("TASK-*.json")) if folder.exists() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "in_progress" and data.get("agent") == agent and data.get("paths"):
            owned.append(str(data.get("id", "")))
    return owned[0] if len(owned) == 1 else ""


def first_line(text: str, fallback: str = "-") -> str:
    """Return the first non-empty line of a note, for one-line handoff bullets.

    Args:
        text: Multi-line note.
        fallback: Value when the note is empty.

    Returns:
        The first line (at most 160 characters).
    """
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:160] or fallback


def build_summary(agent: str, notes: dict[str, str], changed: list[str]) -> str:
    """Render the conversation summary Markdown.

    Args:
        agent: Agent that ran the conversation.
        notes: Dict with `goal`, `decisions`, `issues`, `next`, `note` and `model` texts.
        changed: Repo-relative paths changed during the conversation.

    Returns:
        Markdown text (empty sections get a TODO for the agent to complete).
    """
    def section(title: str, body: str, placeholder: str) -> str:
        """Render one `##` section, using a TODO placeholder when the body is empty.

        Args:
            title: Section heading.
            body: Section text supplied by the agent.
            placeholder: Hint shown when `body` is empty.

        Returns:
            Markdown section text.
        """
        return f"## {title}\n\n{body.strip() or f'> TODO({agent}): {placeholder}'}\n"

    files = "\n".join(f"- `{p}`" for p in changed[:50]) or "- (無未提交變更)"
    return "\n".join([
        f"# Summary — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} — `{agent}`",
        "",
        f"- **Agent**: `{agent}`" + (f" (`{notes['model']}`)" if notes.get("model") else ""),
        f"- **交接備註**: {notes.get('note') or '-'}",
        "",
        section("目標 (Goal)", notes.get("goal", ""), "本次對話要完成什麼？"),
        section("做了什麼與決策 (Work & Decisions)", notes.get("decisions", ""), "做了哪些修改？為什麼這樣選？相關 ADR？"),
        section("錯誤與根因 (Errors & Root Causes)", notes.get("issues", ""), "遇到什麼錯誤？根本原因？如何修正？(重要者另記 docs/known-issues/)"),
        section("下一步 (Next Steps)", notes.get("next", ""), "下一位 Agent 應該從哪裡開始？"),
        "## 本次變更檔案 (Changed Files)\n",
        files,
    ])


def write_conversation_record(root: Path, agent: str, summary: str, transcript: str) -> tuple[Path, Path] | None:
    """Write the local transcript + summary pair via `scripts/conversations.py`.

    Args:
        root: Project root directory.
        agent: Agent name.
        summary: Summary Markdown.
        transcript: Exported transcript file path, or empty to auto-detect Claude Code.

    Returns:
        Tuple of (transcript path, summary path), or None when the tool is not installed.
    """
    scripts_dir = root / ".agents" / "bin"
    if not (scripts_dir / "conversations.py").exists():
        return None
    sys.path.insert(0, str(scripts_dir))
    import conversations  # type: ignore

    return conversations.write_record(agent, summary, Path(transcript).expanduser() if transcript else None)


def append_handoff(root: Path, agent: str, notes: dict[str, str], record: tuple[Path, Path] | None) -> None:
    """Add a closeout entry to `.agents/handoff/LATEST.md` (the part that is shared through git).

    Args:
        root: Project root directory.
        agent: Agent closing the session.
        notes: Dict with `goal`, `issues`, `next`, `note` texts (one line of each is kept).
        record: Local transcript / summary paths (named for this computer only).
    """
    scripts_dir = root / ".agents" / "bin"
    if not (scripts_dir / "agent_task.py").exists():
        return
    sys.path.insert(0, str(scripts_dir))
    import agent_task  # type: ignore

    bullets = [
        "**檢查結果**: 測試與 Code Review Guard 通過",
        f"**目標**: {first_line(notes.get('goal', ''))}",
        f"**錯誤與根因**: {first_line(notes.get('issues', ''), '無')}",
        f"**下一步**: {first_line(notes.get('next', ''))}",
        f"**交接備註**: {notes.get('note') or '下一位 Agent 請先閱讀上方看板。'}",
    ]
    if record:
        bullets.append(f"**本機對話紀錄**: `.agents/conversations/{record[1].name}`（只在這台電腦）")
    agent_task.update_handoff_file(event_title="Session Closeout (結束對話收尾)", agent=agent, bullets=bullets, root=root)


def commit_and_report(root: Path, agent: str, model: str, push: bool) -> int:
    """Commit remaining changes.

    Args:
        root: Project root directory.
        agent: Agent closing the session.
        model: Model name for the commit trailer (may be empty).
        push: Push to the remote after committing.

    Returns:
        Exit code of `auto_commit.py` (0 when it is not installed).
    """
    auto_commit = root / ".agents" / "bin" / "auto_commit.py"
    if not auto_commit.exists():
        return 0
    cmd = [sys.executable, str(auto_commit), "--closeout", "--agent", agent]
    cmd += ["--model", model] if model else []
    task = active_task_of(root, agent)
    cmd += ["--task", task] if task else []
    cmd += ["--push"] if push else []
    return subprocess.run(cmd, cwd=root, check=False).returncode


def run_closeout(root: Path, args: argparse.Namespace) -> int:
    """Run all closeout steps in order, stopping on failed checks.

    Args:
        root: Project root directory.
        args: Parsed command-line arguments.

    Returns:
        Process exit code.
    """
    lib = load_lib(root)
    cfg = lib.load_config(root) if lib else {"commands": {"test": ""}}
    agent, model = lib.resolve_agent_identity(args.agent, args.model, root=root) if lib else (args.agent or "unattributed-agent", args.model)
    print("=" * 68 + f"\n🏁 Session Closeout — Agent: {agent}\n" + "=" * 68)

    print("\n[1/5] 🧪 執行測試與 Code Review Guard...")
    if run_tests(root, cfg) != 0:
        print("❌ 測試未通過，已中止收尾。請先修復失敗的測試。", file=sys.stderr)
        return 1
    if run_review_guard(root) != 0:
        print("❌ Code Review Guard 偵測到 CRITICAL 違規，已中止收尾。", file=sys.stderr)
        return 1

    print("\n[2/5] 🌳 更新入口檔與目錄樹...")
    refresh_generated_docs(root)

    print("\n[3/5] 📝 寫入本機對話紀錄（逐字稿 + 摘要，不進 git）...")
    changed = [p for _, p in lib.git_changed_files(root)] if lib else []
    notes = {"goal": args.goal, "decisions": args.decisions, "issues": args.issues, "next": args.next, "note": args.note, "model": model}
    record = write_conversation_record(root, agent, build_summary(agent, notes, changed), args.transcript)
    for path in record or ():
        print(f"   → {path.relative_to(root)}")
    if record:
        print("   （摘要中的 TODO 請補完）")

    print("\n[4/5] 🤝 更新交接看板 .agents/handoff/LATEST.md...")
    append_handoff(root, agent, notes, record)

    print("\n[5/5] 🔒 本機 Commit 與未推送統計...")
    return commit_and_report(root, agent, model, args.push)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Session Closeout — 結束對話收尾 (測試、對話紀錄、交接、Commit)")
    parser.add_argument("--agent", default="", help="AI Agent 名稱；留空時自動偵測 (AI_AGENT_NAME / CLAUDECODE ...)")
    parser.add_argument("--model", default="", help="AI 模型名稱")
    parser.add_argument("--goal", default="", help="本次對話目標")
    parser.add_argument("--decisions", default="", help="做了什麼、關鍵決策與理由")
    parser.add_argument("--issues", default="", help="遇到的錯誤、根因與修正方式")
    parser.add_argument("--next", default="", help="下一步建議")
    parser.add_argument("--note", default="", help="留給下一個 Agent 的一句話交接")
    parser.add_argument("--transcript", default="", help="對話匯出檔（非 Claude Code 時使用；Claude Code 自動讀取）")
    parser.add_argument("--push", action="store_true", help="收尾後推送至遠端 (需使用者同意)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    return run_closeout(find_root(), parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
