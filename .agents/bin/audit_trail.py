#!/usr/bin/env python3
"""Agent audit trail: who changed what, in which task, in which commit.

Purpose:
    Builds one report that answers "which agent/model did this, for which task, and
    what else did it touch?" by cross-referencing:
  1. Git Commits (`Agent:`, `Model:`, `Task:` trailers + `[agent:...]` tags + modified files)
  2. Multi-Agent Task Cards (`.agents/tasks/TASK-*.json` including `handoff` history)

Outputs:
  - `docs/architecture/AGENT_AUDIT_REPORT.md` (full ledger, written when no filter is given;
    generated on demand and git-ignored, since git history is the real record)
  - Terminal report filtered by `--agent <name>`, `--file <rel_path>`, or `--task <TASK-NNN>`.
  - `--verify` exits 1 when a commit (other than the initial scaffold) has no agent attribution.

Usage:
    python3 scripts/agentctl.py audit [--agent NAME] [--file PATH] [--task TASK-NNN] [--verify]
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

from project_config import md_cell  # noqa: E402

REPORT_FILE = ROOT / "docs" / "architecture" / "AGENT_AUDIT_REPORT.md"


def collect_git_commits(root: Path = ROOT, max_count: int = 100) -> list[dict]:
    """Read recent commits with their Agent / Model / Task trailers and changed files.

    Args:
        root: Repository root directory.
        max_count: Maximum number of commits to read.

    Returns:
        Commit dicts with `sha`, `date`, `subject`, `agent`, `model`, `task`, `files`.
    """
    if not (root / ".git").exists():
        return []
    sep = "@@COMMIT@@"
    field_sep = "@@FIELD@@"
    fmt = f"{sep}%h{field_sep}%ad{field_sep}%s{field_sep}%(trailers:key=Agent,valueonly=true){field_sep}%(trailers:key=Model,valueonly=true){field_sep}%(trailers:key=Task,valueonly=true)"
    res = subprocess.run(
        ["git", "log", f"-n{max_count}", "--date=short", f"--pretty=format:{fmt}", "--name-only"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if res.returncode != 0 or not res.stdout.strip():
        return []

    commits: list[dict] = []
    for raw_chunk in res.stdout.split(sep):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        header = lines[0]
        files = [ln.strip() for ln in lines[1:] if ln.strip()]
        parts = header.split(field_sep)
        if len(parts) < 6:
            continue
        sha, dt_str, subject, tr_agent, tr_model, tr_task = [p.strip() for p in parts[:6]]
        if not tr_agent:
            m = re.search(r"\[agent:([^\]]+)\]", subject)
            if m:
                tr_agent = m.group(1).strip()
        if not tr_task:
            mt = re.search(r"\b(TASK-\d{3})\b", subject)
            if mt:
                tr_task = mt.group(1).strip()
        commits.append({
            "sha": sha,
            "date": dt_str,
            "subject": subject,
            "agent": tr_agent or "system/init",
            "model": tr_model or "-",
            "task": tr_task or "-",
            "files": files,
        })
    return commits


def collect_tasks(root: Path = ROOT) -> list[dict]:
    """Load every task card.

    Args:
        root: Project root directory.

    Returns:
        Task dictionaries (unreadable files are skipped).
    """
    tasks_dir = root / ".agents" / "tasks"
    if not tasks_dir.exists():
        return []
    out: list[dict] = []
    for f in sorted(tasks_dir.glob("TASK-*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def render_audit_report(
    commits: list[dict],
    tasks: list[dict],
    agent_filter: str = "",
    file_filter: str = "",
    task_filter: str = "",
) -> str:
    """Render the audit report Markdown, optionally filtered.

    Args:
        commits: Output of `collect_git_commits()`.
        tasks: Output of `collect_tasks()`.
        agent_filter: Keep only entries by this agent.
        file_filter: Keep only entries touching this path (prefix match).
        task_filter: Keep only entries for this task ID.

    Returns:
        Markdown text of the report.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if agent_filter:
        commits = [c for c in commits if c["agent"] == agent_filter]
        tasks = [t for t in tasks if t.get("agent") == agent_filter or t.get("handed_off_from") == agent_filter]
    if file_filter:
        norm_f = file_filter.strip("/")
        commits = [c for c in commits if any(f == norm_f or f.startswith(norm_f) for f in c["files"])]
    if task_filter:
        tf = task_filter.upper()
        commits = [c for c in commits if c["task"].upper() == tf]
        tasks = [t for t in tasks if t.get("id", "").upper() == tf]

    # 1. Agent Contribution Summary
    agent_stats: dict[str, dict[str, int]] = {}
    for c in commits:
        ag = c["agent"]
        st = agent_stats.setdefault(ag, {"commits": 0, "files_touched": 0, "tasks": 0})
        st["commits"] += 1
        st["files_touched"] += len(c["files"])
    for t in tasks:
        ag = t.get("agent") or "unassigned"
        st = agent_stats.setdefault(ag, {"commits": 0, "files_touched": 0, "tasks": 0})
        st["tasks"] += 1

    stat_rows = [
        f"| `{ag}` | {vals['commits']} | {vals['tasks']} | {vals['files_touched']} |"
        for ag, vals in sorted(agent_stats.items())
    ] or ["| (尚無紀錄) | 0 | 0 | 0 |"]

    # 2. Task & Handoff Ledger
    task_rows = []
    for t in tasks:
        hist_str = " ➔ ".join(
            f"{h.get('action')}({h.get('agent') or h.get('from_agent', '-')})" for h in t.get("history", [])
        ) or "-"
        task_rows.append(
            f"| **{t['id']}** | {md_cell(t.get('title', ''))} | `{t.get('status', '')}` | `{t.get('agent') or '-'}` | "
            f"`{t.get('handed_off_to') or '-'}` | {md_cell(t.get('done_items') or t.get('summary') or '-')} | "
            f"{md_cell(t.get('todo_items') or '-')} | {hist_str} |"
        )
    if not task_rows:
        task_rows = ["| (無任務紀錄) | - | - | - | - | - | - | - |"]

    # 3. Git Commit Attribution Ledger
    commit_rows = []
    for c in commits[:50]:
        f_preview = ", ".join(f"`{p}`" for p in c["files"][:4])
        if len(c["files"]) > 4:
            f_preview += f" (+{len(c['files']) - 4} files)"
        commit_rows.append(
            f"| `{c['sha']}` | {c['date']} | `{c['agent']}` | `{c['task']}` | {md_cell(c['subject'])} | {f_preview or '-'} |"
        )
    if not commit_rows:
        commit_rows = ["| (無 Commit 紀錄) | - | - | - | - | - |"]

    nl = "\n"
    return f"""# 🕵️ Agent 協作與變更溯源報告 (AGENT_AUDIT_REPORT)

> ⚠️ 由 `python3 scripts/agentctl.py audit` 自動彙整產生（最後更新：`{now_str}`）。
> 串聯 **Git Commit Trailers** 與 **任務與交接卡 (`.agents/tasks/`)**；需要時才產生，不進 git。

---

## 1. 各 AI Agent 貢獻統計總覽

| AI Agent | Git Commits 數 | 參與任務卡數 | 累計觸及檔案人次 |
|---|---|---|---|
{nl.join(stat_rows)}

---

## 2. 任務卡與跨 Agent 交接軌跡 (`Tasks & Handoffs`)

| 任務 ID | 標題 | 狀態 | 目前/完成 Agent | 待接手 Agent | 已完成項目 (`done`) | 待辦事項 (`todo`) | 狀態流轉歷史 |
|---|---|---|---|---|---|---|---|
{nl.join(task_rows)}

---

## 3. Git Commit 全鏈路署名紀錄 (最近 50 筆)

| Commit | 日期 | 執行 Agent | 任務卡 | Commit 標題 | 修改檔案 |
|---|---|---|---|---|---|
{nl.join(commit_rows)}
"""


def main() -> int:
    """Generate the report (or a filtered view) and optionally verify attribution.

    Returns:
        Process exit code (1 when `--verify` finds unattributed commits).
    """
    parser = argparse.ArgumentParser(description="多 AI Agent 全鏈路溯源與審計報表工具")
    parser.add_argument("--agent", default="", help="僅篩選特定 AI Agent 的變更紀錄")
    parser.add_argument("--file", default="", help="追蹤特定檔案的歷次 Agent 修改紀錄")
    parser.add_argument("--task", default="", help="追蹤特定任務編號 (如 TASK-001) 的所有變更")
    parser.add_argument("--verify", action="store_true", help="驗證所有非初始 Commit 是否皆具備 Agent 署名")
    args = parser.parse_args()

    commits = collect_git_commits(ROOT)
    tasks = collect_tasks(ROOT)

    report_md = render_audit_report(
        commits,
        tasks,
        agent_filter=args.agent,
        file_filter=args.file,
        task_filter=args.task,
    )

    if not (args.agent or args.file or args.task):
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(report_md, encoding="utf-8")
        print(
            f"✅ 已更新全鏈路審計報告 `{REPORT_FILE.relative_to(ROOT)}` "
            f"(共 {len(commits)} 筆 Commits、{len(tasks)} 張任務卡)"
        )
    else:
        print(report_md)

    if args.verify:
        unattributed = [
            c for c in commits
            if c["agent"] in ("unattributed-agent", "") and not c["subject"].startswith("chore(init):")
        ]
        if unattributed:
            print(f"⚠️ 發現 {len(unattributed)} 筆未標註特定 Agent 名稱的 Commit：", file=sys.stderr)
            for c in unattributed:
                print(f"  - [{c['sha']}] {c['subject']}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
