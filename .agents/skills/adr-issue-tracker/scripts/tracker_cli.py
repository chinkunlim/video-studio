#!/usr/bin/env python3
"""ADR and known-issue tracker: numbered decision and bug records with index tables.

Purpose:
    Keeps "why did we decide X?" (Architecture Decision Records) and "what went wrong and
    why?" (known issues) in fixed places with stable IDs, so agents can reference them
    from code comments (`# Refs: ADR-003`), commits and session logs.

Commands:
    --add-adr <slug> --title "..."     Create `docs/adr/NNN-<slug>.md` and add a row to `DECISIONS.md`.
    --add-issue <slug> --title "..."   Create `docs/known-issues/NNN-<slug>.md` and add a row to `KNOWN_ISSUES.md`.
    New records follow the folder's `_TEMPLATE.md` ({{NUM}}, {{TITLE}}, {{DATE}}, {{AGENT}},
    {{TASK}}, {{SUMMARY}}, {{STATUS}} are filled in); a built-in format is used when it is missing.
    --list                             Print both index tables (default).

Usage:
    python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr cache-strategy \
        --title "Use in-memory LRU cache" --summary "API latency too high" --agent claude-code --task TASK-004
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re

STATUS_MAP = {
    "open": "🔴 未解決 (Open)",
    "mitigated": "🟡 已規避 (Mitigated)",
    "resolved": "🟢 已根治 (Resolved)",
}
TEMPLATE_NAME = "_TEMPLATE.md"
FALLBACK_ADR = (
    "# ADR-{{NUM}}：{{TITLE}}\n\n- **狀態**：Accepted\n- **日期**：{{DATE}}\n- **Agent**：`{{AGENT}}`\n- **任務**：`{{TASK}}`\n\n"
    "## 1. 背景與問題\n\n{{SUMMARY}}\n\n## 2. 評估過的方案\n\nTODO\n\n## 3. 決策與理由\n\nTODO\n\n## 4. 影響與代價\n\nTODO\n"
)
FALLBACK_ISSUE = (
    "# ISSUE-{{NUM}}：{{TITLE}}\n\n- **狀態**：{{STATUS}}\n- **發現日期**：{{DATE}}\n- **Agent**：`{{AGENT}}`\n- **任務**：`{{TASK}}`\n\n"
    "## 1. 現象\n\n{{SUMMARY}}\n\n## 2. 根本原因\n\nTODO\n\n## 3. 修正或規避方式\n\nTODO（程式碼加註 `Refs: ISSUE-{{NUM}}`）\n\n## 4. 防回歸\n\nTODO\n"
)
ADR_INDEX_HEADER = "# 架構決策總表 (ADR Index)\n\n| ADR | 標題 | 狀態 | 日期 | 相關程式 |\n|---|---|---|---|---|\n"
ISSUE_INDEX_HEADER = "# 已知問題總表 (Known Issues Index)\n\n| ISSUE | 狀態 | 標題 | 現象 | 程式與測試 |\n|---|---|---|---|---|\n"
KINDS = {
    "adr": {"folder": "docs/adr", "index": "DECISIONS.md", "header": ADR_INDEX_HEADER, "fallback": FALLBACK_ADR, "prefix": "ADR"},
    "issue": {"folder": "docs/known-issues", "index": "KNOWN_ISSUES.md", "header": ISSUE_INDEX_HEADER, "fallback": FALLBACK_ISSUE, "prefix": "ISSUE"},
}


def find_root() -> Path:
    """Locate the project root (folder containing `.agents/project.toml`).

    Returns:
        The project root, or the current working directory when none is found.
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents, *Path(__file__).resolve().parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return current


def cell(text: str) -> str:
    """Escape text for a Markdown table cell.

    Args:
        text: Raw text.

    Returns:
        Text with `|` escaped and newlines replaced by spaces.
    """
    return text.replace("|", "\\|").replace("\n", " ")


def next_number(folder: Path) -> int:
    """Compute the next record number in a folder (`_TEMPLATE.md` and index files are ignored).

    Args:
        folder: `docs/adr` or `docs/known-issues`.

    Returns:
        Highest existing `NNN-*.md` number + 1 (at least 1).
    """
    nums = [int(m.group(1)) for f in folder.glob("[0-9][0-9][0-9]-*.md") if (m := re.match(r"^(\d{3})-", f.name))]
    return max([0, *nums]) + 1


def slugify(slug: str) -> str:
    """Normalise a slug to lower-case ASCII words joined by `-`.

    Args:
        slug: User-supplied slug.

    Returns:
        Clean slug (`record` when nothing remains).
    """
    return re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "record"


def append_index_row(index_file: Path, header: str, row: str) -> None:
    """Append a row to an index table, creating the index when missing.

    Args:
        index_file: `DECISIONS.md` or `KNOWN_ISSUES.md`.
        header: Header used when the file must be created.
        row: Markdown table row.
    """
    text = index_file.read_text(encoding="utf-8") if index_file.exists() else header
    index_file.write_text(text.rstrip() + "\n" + row + "\n", encoding="utf-8")


def render_record(folder: Path, fallback: str, values: dict[str, str]) -> str:
    """Fill the folder's `_TEMPLATE.md` (or the built-in fallback) with record values.

    Args:
        folder: `docs/adr` or `docs/known-issues`.
        fallback: Template used when the folder has no `_TEMPLATE.md`.
        values: Placeholder name -> value, e.g. `{"NUM": "003", "TITLE": "..."}`.

    Returns:
        The rendered Markdown.
    """
    template_file = folder / TEMPLATE_NAME
    text = template_file.read_text(encoding="utf-8") if template_file.exists() else fallback
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def create_record(root: Path, kind: str, args: argparse.Namespace) -> Path:
    """Create a numbered ADR or ISSUE file from the template and add it to the index.

    Args:
        root: Project root.
        kind: `adr` or `issue`.
        args: Parsed arguments (`add_adr` / `add_issue`, `title`, `summary`, `status`, `agent`, `task`).

    Returns:
        Path of the new record.
    """
    spec = KINDS[kind]
    folder = root / spec["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    num = f"{next_number(folder):03d}"
    target = folder / f"{num}-{slugify(args.add_adr if kind == 'adr' else args.add_issue)}.md"
    today = date.today().isoformat()
    status = STATUS_MAP[args.status] if kind == "issue" else "Accepted"
    values = {
        "NUM": num, "TITLE": args.title, "DATE": today, "AGENT": args.agent or "-", "TASK": args.task or "-",
        "SUMMARY": args.summary or "TODO", "STATUS": status,
    }
    target.write_text(render_record(folder, spec["fallback"], values), encoding="utf-8")
    link = f"[{spec['prefix']}-{num}]({target.name})"
    row = (
        f"| {link} | {cell(args.title)} | {status} | {today} | TODO |" if kind == "adr"
        else f"| {link} | {status} | {cell(args.title)} | {cell(args.summary or '-')} | TODO |"
    )
    append_index_row(folder / spec["index"], spec["header"], row)
    return target


def print_indexes(root: Path) -> None:
    """Print both index tables.

    Args:
        root: Project root.
    """
    for rel in ("docs/adr/DECISIONS.md", "docs/known-issues/KNOWN_ISSUES.md"):
        path = root / rel
        if path.exists():
            print(f"\n=== {rel} ===\n{path.read_text(encoding='utf-8')}")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="ADR 與 Known Issues 編號紀錄工具")
    parser.add_argument("--add-adr", metavar="SLUG", help="新增 ADR（英文短代稱，例如 cache-strategy）")
    parser.add_argument("--add-issue", metavar="SLUG", help="新增 ISSUE（英文短代稱，例如 api-timeout）")
    parser.add_argument("--title", default="未命名紀錄", help="標題")
    parser.add_argument("--summary", default="", help="背景（ADR）或現象（ISSUE）")
    parser.add_argument("--status", choices=list(STATUS_MAP), default="open", help="ISSUE 狀態")
    parser.add_argument("--agent", default="", help="記錄者 Agent 名稱")
    parser.add_argument("--task", default="", help="相關任務編號")
    parser.add_argument("--list", action="store_true", help="列出總表")
    args = parser.parse_args(argv)
    root = find_root()
    if args.add_adr:
        print(f"✅ 已建立 {create_record(root, 'adr', args).relative_to(root)}（請補完 TODO）")
    elif args.add_issue:
        print(f"✅ 已建立 {create_record(root, 'issue', args).relative_to(root)}（請補完 TODO）")
    else:
        print_indexes(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
