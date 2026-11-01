#!/usr/bin/env python3
"""End-of-session closeout: verify, check the docs, record what happened, commit and push.

Purpose:
    When the user says "結束對話" / "收工" / "wrap up", the active agent runs this script
    so the next agent (or the same user on another computer) can continue without
    re-reading the whole conversation.

Steps:
    1. Run the configured test command (`[commands] test` in `.agents/project.toml`)
       and `code-review-guard` — stop if either fails.
    2. Refresh generated docs: agent adapters, directory tree, dependency graph.
    3. Markdown check: list the project's own `.md` files that this session (uncommitted changes
       plus unpushed commits) did not touch, so the agent confirms every document is up to date.
       The agent updates the documents BEFORE running closeout (see SKILL.md §1).
    4. Write the local conversation record (git-ignored, deletable when the project ends):
       `.agents/conversations/YYYY-MM-DD-HHMM-<agent>-transcript.md` (full, secrets masked) and
       `...-summary.md` (goal, decisions, errors and root causes, next steps, changed files).
    5. Append a closeout entry to `.agents/handoff/LATEST.md` (in git): one line each for goal,
       errors and next step, so another computer still knows where things stand.
    6. Commit via `.agents/bin/auto_commit.py --closeout` (limited to the agent's active task
       when exactly one is in progress), then push to the upstream branch. The user decided that
       closing a session means pushing; `--no-push` keeps everything local.

Usage:
    python3 .agents/skills/session-closeout/scripts/closeout_runner.py --agent claude-code \
        --goal "Add login API" --decisions "Use JWT; see ADR-002" \
        --issues "Timeout in test: fixture clock not frozen -> fixed" --next "Add refresh token"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[4]
# Markdown files kept up to date by tools (or by the template), not by the session's agent
GENERATED_MD = {"CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md", "docs/architecture/PROJECT_TREE.md"}
GENERATED_MD_PREFIXES = (".agents/", ".cursor/", ".windsurf/", "legacy/", "node_modules/")


def find_root() -> Path:
    """Locate the project root (working directory first, then script location).

    Returns:
        The directory containing `.agents/project.toml`, or the working directory.
    """
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


def git_lines(root: Path, *args: str) -> list[str]:
    """Run a git command and return its non-empty output lines.

    Args:
        root: Repository root.
        *args: git arguments.

    Returns:
        Output lines (empty when the command fails).
    """
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return [line.strip() for line in res.stdout.splitlines() if line.strip()] if res.returncode == 0 else []


def upstream_of(root: Path) -> str:
    """Return the upstream branch of the current branch.

    Args:
        root: Repository root.

    Returns:
        Upstream such as `origin/main`, or an empty string when none is set.
    """
    found = git_lines(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return found[0] if found else ""


def is_project_markdown(rel: str) -> bool:
    """Tell whether a Markdown file is written by the project's agents (not generated or framework-managed).

    Args:
        rel: Repo-relative POSIX path.

    Returns:
        True for documents the session's agent must keep up to date.
    """
    if not rel.endswith(".md") or rel in GENERATED_MD or rel.startswith(GENERATED_MD_PREFIXES):
        return False
    if rel.endswith("/_TEMPLATE.md"):
        return False
    return not rel.startswith("docs/standards/") or rel == "docs/standards/PROJECT_RULES.md"


def session_changed_files(root: Path, lib) -> set[str]:
    """Files changed in this session: uncommitted changes plus commits not pushed yet.

    Args:
        root: Repository root.
        lib: The `project_config` module (None when missing).

    Returns:
        Repo-relative paths.
    """
    changed = {p for _, p in lib.git_changed_files(root)} if lib else set()
    upstream = upstream_of(root)
    if upstream:
        changed.update(git_lines(root, "diff", "--name-only", f"{upstream}..HEAD"))
    return changed


def report_markdown(root: Path, lib, notes: dict[str, str] | None = None) -> list[str]:
    """Print which project documents this session updated and check for missing docs.

    Args:
        root: Repository root.
        lib: The `project_config` module (None when missing).
        notes: Optional closeout notes dictionary (goal, decisions, issues).

    Returns:
        List of warning messages for missing required documents.
    """
    docs = sorted(rel for rel in git_lines(root, "ls-files", "--cached", "--others", "--exclude-standard", "*.md") if is_project_markdown(rel))
    changed = session_changed_files(root, lib)
    code = [rel for rel in changed if not rel.endswith(".md") and not rel.startswith(".agents/")]
    updated = [rel for rel in docs if rel in changed]
    untouched = [rel for rel in docs if rel not in changed]
    print(f"   本次修改 {len(code)} 個非文件檔案；已更新 {len(updated)} 份文件：")
    for rel in updated:
        print(f"   ✅ {rel}")
    if untouched:
        print("   以下文件本次沒有修改，請確認內容仍然正確（不正確就先更新再收尾）：")
        for rel in untouched:
            print(f"   📄 {rel}")

    warnings = []
    if notes:
        issues_text = (notes.get("issues") or "").strip()
        if issues_text and issues_text.lower() not in ("none", "-", "n/a", "無", "無。"):
            has_issue_doc = any(p.startswith("docs/known-issues/") and p != "docs/known-issues/_TEMPLATE.md" for p in changed)
            if not has_issue_doc:
                warnings.append("⚠️ [文件防呆] 本次收尾填寫了錯誤根因 (--issues)，但 docs/known-issues/ 本次未新增/更新紀錄！")
                print("   ⚠️ [文件防呆] 本次收尾填寫了錯誤根因 (--issues)，但 docs/known-issues/ 本次未新增/更新紀錄！")
                print("      可執行：python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-issue <slug> --title \"...\"")

        decisions_text = (notes.get("decisions") or "").strip()
        arch_triggers = any(p in changed for p in (".agents/project.toml", "pyproject.toml")) or any(k in decisions_text for k in ("架構", "ADR", "重構", "選用", "分層", "決定"))
        if arch_triggers:
            has_adr_doc = any(p.startswith("docs/adr/") and p != "docs/adr/_TEMPLATE.md" for p in changed)
            if not has_adr_doc:
                warnings.append("⚠️ [文件防呆] 本次涉及架構變更或重要決策，但 docs/adr/ 本次未新增/更新 ADR 紀錄！")
                print("   ⚠️ [文件防呆] 本次涉及架構變更或重要決策，但 docs/adr/ 本次未新增/更新 ADR 紀錄！")
                print("      可執行：python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title \"...\"")

        if code and "CHANGELOG.md" not in updated:
            warnings.append("⚠️ [文件防呆] 本次修改了程式碼，但 CHANGELOG.md 未在本次更新！")
            print("   ⚠️ [文件防呆] 本次修改了程式碼，但 CHANGELOG.md 本次未更新（請確認是否需在 [Unreleased] 記錄）。")

    return warnings


def push_to_remote(root: Path) -> int:
    """Push the current branch to its upstream (`ALLOW_PUSH=1` lets the pre-push hook through).

    Args:
        root: Repository root.

    Returns:
        0 when pushed or nothing to push, 1 when the push failed or there is no upstream.
    """
    upstream = upstream_of(root)
    if not upstream:
        print("⚠️ 這個分支沒有遠端分支（upstream），沒有推送。請先請使用者確認要推送到哪個 GitHub repo，"
              "再執行 `ALLOW_PUSH=1 git push -u origin <分支>`。")
        return 1
    pending = git_lines(root, "log", "--oneline", f"{upstream}..HEAD")
    if not pending:
        print(f"✅ 沒有未推送的 commit（{upstream} 已是最新）。")
        return 0
    res = subprocess.run(["git", "push"], cwd=root, capture_output=True, text=True, check=False, env={**os.environ, "ALLOW_PUSH": "1"})
    if res.returncode != 0:
        print(f"❌ 推送到 {upstream} 失敗（commit 已保留在本機）：\n{(res.stderr or res.stdout).strip()[-800:]}", file=sys.stderr)
        return 1
    print(f"🚀 已推送 {len(pending)} 個 commit 到 {upstream}：")
    for line in pending[:10]:
        print(f"   - {line}")
    return 0


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


def commit_and_report(root: Path, agent: str, model: str) -> int:
    """Commit remaining changes (pushing is done afterwards by `push_to_remote()`).

    Args:
        root: Project root directory.
        agent: Agent closing the session.
        model: Model name for the commit trailer (may be empty).

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

    print("\n[1/7] 🧪 執行測試與 Code Review Guard...")
    if run_tests(root, cfg) != 0:
        print("❌ 測試未通過，已中止收尾。請先修復失敗的測試。", file=sys.stderr)
        return 1
    if run_review_guard(root) != 0:
        print("❌ Code Review Guard 偵測到 CRITICAL 違規，已中止收尾。", file=sys.stderr)
        return 1

    print("\n[2/7] 🌳 更新入口檔與目錄樹...")
    refresh_generated_docs(root)

    print("\n[3/7] 📚 檢查 Markdown 文件...")
    doc_notes = {"goal": args.goal, "decisions": args.decisions, "issues": args.issues}
    doc_warnings = report_markdown(root, lib, doc_notes)
    if getattr(args, "strict_docs", False) and doc_warnings:
        print("❌ --strict-docs 已啟用，文件檢查未通過，中止收尾。", file=sys.stderr)
        return 1

    print("\n[4/7] 📝 寫入本機對話紀錄（逐字稿 + 摘要，不進 git）...")
    changed = [p for _, p in lib.git_changed_files(root)] if lib else []
    notes = {"goal": args.goal, "decisions": args.decisions, "issues": args.issues, "next": args.next, "note": args.note, "model": model}
    record = write_conversation_record(root, agent, build_summary(agent, notes, changed), args.transcript)
    for path in record or ():
        print(f"   → {path.relative_to(root)}")
    if record:
        print("   （摘要中的 TODO 請補完）")

    print("\n[5/7] 🤝 更新交接看板 .agents/handoff/LATEST.md...")
    append_handoff(root, agent, notes, record)

    print("\n[6/7] 🔒 本機 Commit...")
    if commit_and_report(root, agent, model) != 0:
        print("❌ Commit 失敗，沒有推送。", file=sys.stderr)
        return 1
    if args.no_push:
        print("\n[7/7] ⏸️ 使用 --no-push：commit 保留在本機，沒有推送。")
        return 0
    print("\n[7/7] 🚀 推送到 GitHub...")
    return push_to_remote(root)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Session Closeout — 結束對話收尾 (測試、文件檢查、對話紀錄、交接、Commit、推送)")
    parser.add_argument("--agent", default="", help="AI Agent 名稱；留空時自動偵測 (AI_AGENT_NAME / CLAUDECODE ...)")
    parser.add_argument("--model", default="", help="AI 模型名稱")
    parser.add_argument("--goal", default="", help="本次對話目標")
    parser.add_argument("--decisions", default="", help="做了什麼、關鍵決策與理由")
    parser.add_argument("--issues", default="", help="遇到的錯誤、根因與修正方式")
    parser.add_argument("--next", default="", help="下一步建議")
    parser.add_argument("--note", default="", help="留給下一個 Agent 的一句話交接")
    parser.add_argument("--transcript", default="", help="對話匯出檔（非 Claude Code 時使用；Claude Code 自動讀取）")
    parser.add_argument("--strict-docs", action="store_true", help="強制文件檢查：若缺少 ADR、Known Issues 或 CHANGELOG 更新則中止收尾")
    parser.add_argument("--no-push", action="store_true", help="只在本機 commit，不推送（預設收尾會推送到 upstream）")
    parser.add_argument("--push", action="store_true", help=argparse.SUPPRESS)  # v3.3 and before; pushing is now the default
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
