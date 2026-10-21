#!/usr/bin/env python3
"""Task cards and the handoff board for agents that take turns on one project.

Purpose:
    Only one AI agent edits the project at a time. Task cards record what is being
    worked on, what is finished, what is left, and who should continue, so the next
    agent (or the next session) can pick up exactly where the last one stopped.

Commands:
    create   Register a task card `.agents/tasks/TASK-NNN-<slug>.json`.
    claim    Take over an `open` or `handed_off` task (refuses tasks another agent
             is still working on unless `--force`).
    handoff  Pause a task and record done items, remaining TODOs and blockers.
    done     Mark a task finished with a summary.
    list     Print every task card.

Every command refreshes `.agents/handoff/LATEST.md`: a live board at the top plus a
timeline of the last 20 events (older events move to `.agents/handoff/ARCHIVE.md`).

Usage:
    python3 scripts/agentctl.py task create "Add login API" --paths src/app/services --agent claude-code
    python3 scripts/agentctl.py task handoff TASK-001 --done-items "..." --todo-items "..." --to cursor
    python3 scripts/agentctl.py task claim TASK-001 --agent cursor
    python3 scripts/agentctl.py task done TASK-001 --summary "..."
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import md_cell, resolve_agent_identity  # noqa: E402

LIVE_START = "<!-- LIVE_STATE_START -->"
LIVE_END = "<!-- LIVE_STATE_END -->"
TIMELINE_HEADER = "## 📜 交接與活動時間軸 (Handoff & Activity Timeline)"
MAX_TIMELINE_ENTRIES = 20
ACTIVE_STATUSES = ("in_progress", "handed_off", "open")
STATUS_BADGES = {
    "in_progress": "🟢 `in_progress`",
    "handed_off": "🟠 `handed_off` (待接手)",
    "open": "⚪ `open`",
}
BOARD_INTRO = (
    "> **AI Agent 開工必讀**：進入對話時請先閱讀下方「即時狀態看板」，確認上一位 Agent 的完成進度、"
    "待接手任務 (`handed_off`) 與注意事項；詳細過程請看本機的 `.agents/conversations/`。"
)


def _now_iso() -> str:
    """Return the current UTC time formatted for logs.

    Returns:
        Timestamp such as `2026-10-19 08:30 UTC`.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _slugify(title: str) -> str:
    """Turn a task title into a short ASCII slug for the file name.

    Args:
        title: Free-text task title (any language).

    Returns:
        Lower-case slug of at most 32 characters (`task` when nothing ASCII remains).
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return slug[:32] or "task"


def tasks_dir(root: Path = ROOT) -> Path:
    """Return the directory that stores task cards.

    Args:
        root: Project root directory.

    Returns:
        Path to `.agents/tasks`.
    """
    return root / ".agents" / "tasks"


def load_all_tasks(root: Path = ROOT) -> list[dict]:
    """Load every readable task card, sorted by file name.

    Args:
        root: Project root directory.

    Returns:
        List of task dictionaries (corrupt files are skipped).
    """
    folder = tasks_dir(root)
    if not folder.exists():
        return []
    tasks: list[dict] = []
    for f in sorted(folder.glob("TASK-*.json")):
        try:
            tasks.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return tasks


def find_task_file(task_id: str, root: Path = ROOT) -> Path | None:
    """Locate the JSON file of a task card.

    Args:
        task_id: Task ID such as `TASK-001` (case-insensitive).
        root: Project root directory.

    Returns:
        The task card path, or None when it does not exist.
    """
    folder = tasks_dir(root)
    if not folder.exists():
        return None
    wanted = task_id.upper()
    for f in sorted(folder.glob("TASK-*.json")):
        if f.name.upper() == f"{wanted}.JSON" or f.name.upper().startswith(f"{wanted}-"):
            return f
    return None


def next_task_id(root: Path = ROOT) -> str:
    """Compute the next free task ID (highest existing number + 1).

    Args:
        root: Project root directory.

    Returns:
        A new ID such as `TASK-004`.
    """
    numbers = [0]
    for f in tasks_dir(root).glob("TASK-*.json"):
        match = re.match(r"TASK-(\d+)", f.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"TASK-{max(numbers) + 1:03d}"


def save_task(path: Path, task: dict) -> None:
    """Write a task card to disk as pretty-printed UTF-8 JSON.

    Args:
        path: Destination file.
        task: Task data.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _git_info(root: Path = ROOT) -> tuple[str, str]:
    """Read the current branch and latest commit for the board header.

    Args:
        root: Repository root directory.

    Returns:
        Tuple of branch name and `<short-sha> <subject>`.
    """
    def run(args: list[str]) -> str:
        """Run one git command and return its trimmed output.

        Args:
            args: Arguments after `git`.

        Returns:
            Standard output, or an empty string on failure.
        """
        res = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
        return res.stdout.strip() if res.returncode == 0 else ""

    branch = run(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
    head = run(["log", "-1", "--pretty=format:%h %s"]) or "(尚無 Commit)"
    return branch, head


def _task_row(task: dict) -> str:
    """Render one task card as a Markdown table row for the live board.

    Args:
        task: Task data.

    Returns:
        A single `| ... |` row with every cell escaped.
    """
    status = task.get("status", "open")
    next_agent = (task.get("handed_off_to") or "any") if status == "handed_off" else "-"
    todo_parts = []
    if task.get("todo_items"):
        todo_parts.append(f"**TODO**: {md_cell(task['todo_items'])}")
    if task.get("blockers"):
        todo_parts.append(f"⚠️ **卡點**: {md_cell(task['blockers'])}")
    cells = [
        f"**{task['id']}**<br/>{md_cell(task.get('title', ''))}",
        STATUS_BADGES.get(status, md_cell(status)),
        f"`{md_cell(task.get('agent') or '-')}`",
        f"`{md_cell(next_agent)}`",
        ", ".join(f"`{md_cell(p)}`" for p in task.get("paths", [])) or "-",
        md_cell(task.get("done_items") or task.get("summary") or "-"),
        "<br/>".join(todo_parts) or "-",
    ]
    return "| " + " | ".join(cells) + " |"


def render_live_dashboard(root: Path = ROOT, last_actor: str = "") -> str:
    """Build the live board section at the top of `LATEST.md`.

    Args:
        root: Project root directory.
        last_actor: Agent that triggered this update.

    Returns:
        Markdown wrapped in the LIVE_STATE markers.
    """
    branch, head_commit = _git_info(root)
    active = [t for t in load_all_tasks(root) if t.get("status") in ACTIVE_STATUSES]
    lines = [
        LIVE_START,
        "## 📊 即時狀態看板 (Live Snapshot)",
        "",
        f"- **最後更新時間**: `{_now_iso()}`",
        f"- **最近操作 Agent**: `{md_cell(last_actor or '-')}`",
        f"- **目前 Git 分支**: `{branch}`",
        f"- **最新 Git Commit**: `{md_cell(head_commit)}`",
        "",
        "### 🎯 進行中 / 待接手任務 (Active & Handed-Off Tasks)",
        "",
    ]
    if not active:
        lines.append('> 目前無進行中或待接手任務。可執行 `python3 scripts/agentctl.py task create "任務名稱" --agent <name>` 建立任務。')
    else:
        lines.append("| 任務 | 狀態 | 目前/上一位 Agent | 建議接手 | 相關範圍 | 已完成 | 待辦與卡點 |")
        lines.append("|---|---|---|---|---|---|---|")
        lines.extend(_task_row(t) for t in active)
    lines.extend(["", LIVE_END])
    return "\n".join(lines)


def _read_timeline(handoff_file: Path) -> list[str]:
    """Read the existing timeline entries from `LATEST.md`.

    Args:
        handoff_file: Path to `LATEST.md`.

    Returns:
        Timeline entries, newest first.
    """
    if not handoff_file.exists():
        return []
    raw = handoff_file.read_text(encoding="utf-8")
    if TIMELINE_HEADER not in raw:
        return []
    after = raw.split(TIMELINE_HEADER, 1)[1].strip()
    return [e.strip() for e in re.split(r"(?=^### \[)", after, flags=re.M) if e.strip()]


def _archive_overflow(entries: list[str], archive_file: Path) -> list[str]:
    """Move timeline entries beyond the limit into `ARCHIVE.md`.

    Args:
        entries: All timeline entries, newest first.
        archive_file: Path to `ARCHIVE.md`.

    Returns:
        The entries that stay in `LATEST.md`.
    """
    if len(entries) <= MAX_TIMELINE_ENTRIES:
        return entries
    overflow = entries[MAX_TIMELINE_ENTRIES:]
    previous = archive_file.read_text(encoding="utf-8") if archive_file.exists() else "# 歷史交接歸檔 (Handoff Archive)\n\n"
    archive_file.write_text(previous.rstrip() + "\n\n" + "\n\n".join(overflow) + "\n", encoding="utf-8")
    return entries[:MAX_TIMELINE_ENTRIES]


def update_handoff_file(event_title: str, agent: str, bullets: list[str], root: Path = ROOT) -> None:
    """Refresh the live board and prepend one timeline entry to `LATEST.md`.

    Args:
        event_title: Short title of the event, e.g. `完成任務 TASK-001`.
        agent: Agent that performed the event.
        bullets: Markdown bullet lines (without the leading `- `).
        root: Project root directory.
    """
    handoff_file = root / ".agents" / "handoff" / "LATEST.md"
    handoff_file.parent.mkdir(parents=True, exist_ok=True)
    new_entry = "\n".join([f"### [{_now_iso()}] {event_title} (by `{agent}`)", *[f"- {b}" for b in bullets]])
    entries = _archive_overflow([new_entry, *_read_timeline(handoff_file)], handoff_file.with_name("ARCHIVE.md"))
    doc = (
        "# 🤝 Agent 狀態看板與交接紀錄 (`LATEST.md`)\n\n"
        f"{BOARD_INTRO}\n\n"
        f"{render_live_dashboard(root, last_actor=agent)}\n\n"
        f"{TIMELINE_HEADER}\n\n" + "\n\n".join(entries) + "\n"
    )
    handoff_file.write_text(doc, encoding="utf-8")


def _load_task_or_fail(task_id: str) -> tuple[Path, dict] | None:
    """Load a task card, printing an error when it is missing.

    Args:
        task_id: Task ID such as `TASK-001`.

    Returns:
        Tuple of file path and task data, or None when not found.
    """
    path = find_task_file(task_id)
    if not path:
        print(f"❌ 找不到任務 `{task_id}`", file=sys.stderr)
        return None
    return path, json.loads(path.read_text(encoding="utf-8"))


def _record(task: dict, action: str, **details: str) -> None:
    """Append one history event to a task card and bump `updated_at`.

    Args:
        task: Task data (mutated in place).
        action: Event name such as `claimed` or `handed_off`.
        **details: Extra string fields stored with the event.
    """
    now = _now_iso()
    task["updated_at"] = now
    task.setdefault("history", []).append({"timestamp": now, "action": action, **details})


def cmd_create(title: str, paths: list[str], agent: str) -> int:
    """Create a task card, optionally claiming it immediately.

    Args:
        title: Task title.
        paths: Files or folders the task is about (informational, helps the next agent).
        agent: Agent to assign right away; empty leaves the task `open`.

    Returns:
        Process exit code (0 on success).
    """
    task_id = next_task_id()
    resolved = resolve_agent_identity(agent, root=ROOT)[0] if agent else ""
    task = {
        "id": task_id,
        "title": title,
        "status": "in_progress" if resolved else "open",
        "agent": resolved,
        "handed_off_from": "",
        "handed_off_to": "",
        "paths": paths,
        "done_items": "",
        "todo_items": "",
        "blockers": "",
        "created_at": _now_iso(),
    }
    _record(task, "created_and_claimed" if resolved else "created", agent=resolved or "system")
    path = tasks_dir() / f"{task_id}-{_slugify(title)}.json"
    save_task(path, task)
    update_handoff_file(
        f"建立任務 `{task_id}`: {md_cell(title)}",
        resolved or "system",
        [f"**狀態**: `{task['status']}`", f"**相關範圍**: `{md_cell(', '.join(paths) or '-')}`"],
    )
    print(f"✅ 已建立任務卡 `{task_id}` ({path.relative_to(ROOT)})")
    return 0


def cmd_claim(task_id: str, agent: str, force: bool) -> int:
    """Take over an `open` or `handed_off` task.

    Args:
        task_id: Task ID such as `TASK-001`.
        agent: Agent taking over the task.
        force: Allow claiming a task that is `done` or `in_progress` by another agent.

    Returns:
        Process exit code (1 when the task is missing or not claimable).
    """
    loaded = _load_task_or_fail(task_id)
    if not loaded:
        return 1
    path, task = loaded
    status, owner = task.get("status"), task.get("agent") or ""
    blocked = status == "done" or (status == "in_progress" and owner and owner != agent)
    if blocked and not force:
        print(f"❌ `{task['id']}` 目前狀態為 `{status}` (Agent: {owner or '-'})；確認要接手請加 --force", file=sys.stderr)
        return 1
    previous = owner or task.get("handed_off_from") or ""
    task.update({"agent": agent, "status": "in_progress"})
    _record(task, "claimed", agent=agent, previous_agent=previous)
    save_task(path, task)
    bullets = [f"**相關範圍**: `{md_cell(', '.join(task.get('paths', [])) or '-')}`"]
    if previous:
        bullets.append(f"**接棒自**: `{previous}`")
    if task.get("todo_items"):
        bullets.append(f"**延續待辦事項**: {md_cell(task['todo_items'])}")
    update_handoff_file(f"認領任務 `{task['id']}` ({md_cell(task.get('title', ''))})", agent, bullets)
    print(f"✅ `{task['id']}` 已由 Agent `{agent}` 認領")
    return 0


def cmd_handoff(task_id: str, agent: str, to_agent: str, notes: dict[str, str]) -> int:
    """Pause an in-progress task so the next agent can continue it.

    Args:
        task_id: Task ID such as `TASK-001`.
        agent: Agent handing the task off (resolved automatically when empty).
        to_agent: Suggested next agent (`any` when unknown).
        notes: Dict with `done_items`, `todo_items` and `blockers` text.

    Returns:
        Process exit code (0 on success).
    """
    loaded = _load_task_or_fail(task_id)
    if not loaded:
        return 1
    path, task = loaded
    from_agent = agent or task.get("agent") or resolve_agent_identity(root=ROOT, task_id=task_id)[0]
    target = to_agent or "any"
    task.update({"status": "handed_off", "handed_off_from": from_agent, "handed_off_to": target, **notes})
    _record(task, "handed_off", from_agent=from_agent, to_agent=target, **notes)
    save_task(path, task)
    bullets = [
        f"**交接狀態**: 🟠 `handed_off` (`{from_agent}` ➔ `{target}`)",
        f"**已完成進度 (Done)**: {md_cell(notes['done_items'] or '(未填寫)')}",
        f"**待接手事項 (TODO)**: {md_cell(notes['todo_items'] or '(未填寫)')}",
    ]
    if notes["blockers"]:
        bullets.append(f"**已知卡點 / 風險 (Blockers)**: {md_cell(notes['blockers'])}")
    update_handoff_file(f"任務交接 `{task['id']}` — {md_cell(task.get('title', ''))}", from_agent, bullets)
    print(f"🤝 已登錄 `{task['id']}` 交接 [handed_off] (`{from_agent}` ➔ `{target}`)")
    return 0


def cmd_done(task_id: str, summary: str, agent: str = "") -> int:
    """Mark a task finished.

    Args:
        task_id: Task ID such as `TASK-001`.
        summary: What was delivered (shown on the board and in the audit report).
        agent: Agent finishing the task (resolved automatically when empty).

    Returns:
        Process exit code (0 on success).
    """
    loaded = _load_task_or_fail(task_id)
    if not loaded:
        return 1
    path, task = loaded
    actor = agent or task.get("agent") or resolve_agent_identity(root=ROOT, task_id=task_id)[0]
    task.update({"status": "done", "agent": actor, "summary": summary, "todo_items": ""})
    task["done_items"] = summary or task.get("done_items", "")
    _record(task, "done", agent=actor, summary=summary)
    save_task(path, task)
    bullets = ["**狀態**: ✅ 已完成 (`done`)", f"**完成摘要**: {md_cell(summary or '(無)')}"]
    update_handoff_file(f"完成任務 `{task['id']}` — {md_cell(task.get('title', ''))}", actor, bullets)
    print(f"✅ 已完成 `{task['id']}` (Agent: `{actor}`)")
    return 0


def cmd_list() -> int:
    """Print every task card as a plain-text table.

    Returns:
        Process exit code (always 0).
    """
    tasks = load_all_tasks()
    if not tasks:
        print('ℹ️ 目前沒有任務卡（可用 `python3 scripts/agentctl.py task create "標題"` 建立）。')
        return 0
    print(f"{'ID':<10} {'STATUS':<13} {'AGENT':<15} {'NEXT':<12} TITLE")
    print("-" * 80)
    for t in tasks:
        next_agent = t.get("handed_off_to", "-") if t.get("status") == "handed_off" else "-"
        print(f"{t['id']:<10} {t.get('status', ''):<13} {t.get('agent') or '-':<15} {next_agent:<12} {t.get('title', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser.

    Returns:
        Configured `ArgumentParser` with one sub-command per task action.
    """
    parser = argparse.ArgumentParser(description="Agent 任務卡、交接 (handoff) 與狀態看板工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="建立新任務卡")
    p_create.add_argument("title_pos", nargs="?", default="", help="任務標題 (位置參數)")
    p_create.add_argument("--title", default="", help="任務標題")
    p_create.add_argument("--paths", nargs="+", default=[], help="此任務主要涉及的目錄或檔案（供下一位 Agent 參考）")
    p_create.add_argument("--agent", default="", help="立即指派給特定 Agent")

    p_claim = sub.add_parser("claim", help="接手 open 或 handed_off 任務")
    p_claim.add_argument("task_id", help="任務編號，如 TASK-001")
    p_claim.add_argument("--agent", required=True, help="Agent 名稱，如 claude-code / cursor")
    p_claim.add_argument("--force", action="store_true", help="強制接手 done 或他人進行中的任務")

    p_handoff = sub.add_parser("handoff", help="暫停任務並交接給下一位 Agent")
    p_handoff.add_argument("task_id", help="任務編號，如 TASK-001")
    p_handoff.add_argument("--agent", default="", help="交出任務的 Agent 名稱")
    p_handoff.add_argument("--to", default="any", help="建議接手的 Agent 名稱 (預設 any)")
    p_handoff.add_argument("--done-items", default="", help="目前已完成的部分")
    p_handoff.add_argument("--todo-items", default="", help="尚未完成、需下一位 Agent 接手的部分")
    p_handoff.add_argument("--blockers", default="", help="卡點、風險或待確認事項")

    p_done = sub.add_parser("done", help="標記任務完成")
    p_done.add_argument("task_id", help="任務編號，如 TASK-001")
    p_done.add_argument("--agent", default="", help="完成任務的 Agent 名稱")
    p_done.add_argument("--summary", default="", help="完成摘要")

    sub.add_parser("list", help="列出所有任務卡")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the requested task command.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.cmd == "create":
        return cmd_create(args.title or args.title_pos or "Untitled Task", args.paths, args.agent)
    if args.cmd == "claim":
        return cmd_claim(args.task_id, args.agent, args.force)
    if args.cmd == "handoff":
        notes = {"done_items": args.done_items, "todo_items": args.todo_items, "blockers": args.blockers}
        return cmd_handoff(args.task_id, args.agent, args.to, notes)
    if args.cmd == "done":
        return cmd_done(args.task_id, args.summary, args.agent)
    return cmd_list()


if __name__ == "__main__":
    raise SystemExit(main())
