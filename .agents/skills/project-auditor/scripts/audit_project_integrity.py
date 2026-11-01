#!/usr/bin/env python3
"""Project integrity auditor: verify conversations, ADRs, known issues and docs before closeout.

Purpose:
    Examines all historical conversation records (.agents/conversations/*-summary.md),
    handoff board (.agents/handoff/LATEST.md), ADRs, Known Issues and CHANGELOG.md.
    Ensures that every decision and bug root cause discovered during development
    has been recorded in permanent documentation with zero omissions and no leftover TODOs.

Usage:
    python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py
    python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py --fix
    python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py --json
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import sys

logger = logging.getLogger(__name__)


def find_root() -> Path:
    """Locate the project root (folder containing `.agents/project.toml`).

    Returns:
        The project root directory.
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents, *Path(__file__).resolve().parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return current


def load_adr_titles(root: Path) -> dict[str, str]:
    """Load existing ADR numbers and titles from docs/adr/.

    Args:
        root: Project root directory.

    Returns:
        Dictionary mapping ADR number/slug to title.
    """
    adr_dir = root / "docs" / "adr"
    titles: dict[str, str] = {}
    if not adr_dir.exists():
        return titles
    for file in adr_dir.glob("[0-9][0-9][0-9]-*.md"):
        content = file.read_text(encoding="utf-8")
        match = re.search(r"^#\s*ADR-\d+[:：]\s*(.+)$", content, re.MULTILINE)
        title = match.group(1).strip() if match else file.stem
        titles[file.stem] = title
    return titles


def load_known_issue_titles(root: Path) -> dict[str, str]:
    """Load existing Known Issues numbers and titles from docs/known-issues/.

    Args:
        root: Project root directory.

    Returns:
        Dictionary mapping issue number/slug to title.
    """
    issue_dir = root / "docs" / "known-issues"
    titles: dict[str, str] = {}
    if not issue_dir.exists():
        return titles
    for file in issue_dir.glob("[0-9][0-9][0-9]-*.md"):
        content = file.read_text(encoding="utf-8")
        match = re.search(r"^#\s*ISSUE-\d+[:：]\s*(.+)$", content, re.MULTILINE)
        title = match.group(1).strip() if match else file.stem
        titles[file.stem] = title
    return titles


def parse_summary_sections(text: str) -> dict[str, list[dict[str, str]]]:
    """Extract structured items from sections in a conversation summary.

    Args:
        text: Conversation summary Markdown text.

    Returns:
        Mapping of section name to list of dicts with 'title' and 'details'.
    """
    sections: dict[str, list[dict[str, str]]] = {}
    current_sec = ""
    current_item: dict[str, str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            sec_name = line[3:].strip().lower()
            if "決策" in sec_name or "decision" in sec_name:
                current_sec = "decisions"
            elif "錯誤" in sec_name or "根因" in sec_name or "error" in sec_name or "issue" in sec_name:
                current_sec = "issues"
            elif "目標" in sec_name or "goal" in sec_name:
                current_sec = "goals"
            elif "下一步" in sec_name or "next" in sec_name:
                current_sec = "next"
            else:
                current_sec = ""
            current_item = None
            if current_sec and current_sec not in sections:
                sections[current_sec] = []
        elif current_sec:
            stripped = line.strip()
            # Top-level item (starts without deep indent)
            if re.match(r"^(\d+\.|\*|-)\s+", line) and not line.startswith(("   ", "\t")):
                clean = re.sub(r"^(\d+\.|\*|-)\s+", "", stripped)
                lead = clean.split("：", 1)[0].split(":", 1)[0].replace("**", "").strip()
                current_item = {"lead": lead, "full_text": clean, "details": ""}
                sections[current_sec].append(current_item)
            elif current_item and stripped:
                # Sub-bullet or continuation detail
                current_item["details"] += " " + stripped
                current_item["full_text"] += " " + stripped

    return sections


def audit_conversations(root: Path) -> dict[str, list[dict[str, str]]]:
    """Audit conversation summaries against ADR and Known Issues records.

    Args:
        root: Project root directory.

    Returns:
        Dictionary of findings containing lists of documented and missing items.
    """
    conv_dir = root / ".agents" / "conversations"
    adr_titles = load_adr_titles(root)
    issue_titles = load_known_issue_titles(root)
    adr_index = (root / "docs" / "adr" / "DECISIONS.md").read_text(encoding="utf-8") if (root / "docs" / "adr" / "DECISIONS.md").exists() else ""
    issue_index = (root / "docs" / "known-issues" / "KNOWN_ISSUES.md").read_text(encoding="utf-8") if (root / "docs" / "known-issues" / "KNOWN_ISSUES.md").exists() else ""

    findings: dict[str, list[dict[str, str]]] = {
        "missing_issues": [],
        "missing_adrs": [],
        "lingering_todos": [],
        "documented_issues": [],
        "documented_adrs": [],
    }

    if not conv_dir.exists():
        logger.info("No conversation directory found at %s", conv_dir)
        return findings

    summaries = sorted(conv_dir.glob("*-summary.md"))
    for summary_file in summaries:
        content = summary_file.read_text(encoding="utf-8")
        sections = parse_summary_sections(content)

        # Check issues & root causes
        for item in sections.get("issues", []):
            lead = item["lead"]
            full_text = item["full_text"]
            if not lead or lead.lower() in ("無", "none", "n/a", "-", "無。"):
                continue

            # Check if covered in known issues
            covered = False
            # Extract distinctive tokens
            tokens = [w for w in re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fa5]{2,}", lead) if w.lower() not in ("issue", "error", "bug")]
            for slug, title in issue_titles.items():
                if any(t in title or t in slug for t in tokens) or lead in title or title in full_text:
                    covered = True
                    break
            if not covered and any(t in issue_index for t in tokens):
                covered = True

            record = {"source": summary_file.name, "item": full_text, "lead": lead}
            if covered:
                findings["documented_issues"].append(record)
            else:
                findings["missing_issues"].append(record)

        # Check architectural decisions
        for item in sections.get("decisions", []):
            lead = item["lead"]
            full_text = item["full_text"]
            if not lead or lead.lower() in ("無", "none", "n/a", "-", "無。"):
                continue

            # Only audit items that represent major architectural decisions
            is_arch = any(k in full_text for k in ("架構", "決策", "選用", "採用", "重構", "ADR", "分層", "模組", "映射", "symlink"))
            if not is_arch:
                continue

            covered = False
            tokens = [w for w in re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fa5]{2,}", lead) if w.lower() not in ("adr", "task")]
            for slug, title in adr_titles.items():
                if any(t in title or t in slug for t in tokens) or lead in title or title in full_text:
                    covered = True
                    break
            if not covered and any(t in adr_index for t in tokens):
                covered = True

            record = {"source": summary_file.name, "item": full_text, "lead": lead}
            if covered:
                findings["documented_adrs"].append(record)
            else:
                findings["missing_adrs"].append(record)

    # Check for lingering TODOs in project records (excluding standards guidelines)
    candidate_docs = [
        *root.glob("docs/adr/*.md"),
        *root.glob("docs/known-issues/*.md"),
        *root.glob("docs/specs/*.md"),
        *root.glob("docs/architecture/*.md"),
        *conv_dir.glob("*-summary.md"),
    ]
    for doc_path in candidate_docs:
        if doc_path.name.startswith("_TEMPLATE"):
            continue
        try:
            doc_lines = doc_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(doc_lines, 1):
            if "TODO" in line:
                findings["lingering_todos"].append({
                    "file": str(doc_path.relative_to(root)),
                    "line": str(lineno),
                    "content": line.strip(),
                })

    return findings


def check_changelog(root: Path) -> dict[str, bool | str]:
    """Verify that CHANGELOG.md has entries and covers recent work.

    Args:
        root: Project root directory.

    Returns:
        Status dictionary with check results.
    """
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        return {"exists": False, "has_unreleased": False, "message": "CHANGELOG.md 不存在"}
    content = changelog.read_text(encoding="utf-8")
    has_unreleased = "## [Unreleased]" in content
    unreleased_lines = []
    if has_unreleased:
        parts = content.split("## [Unreleased]", 1)[1].split("## [", 1)[0]
        unreleased_lines = [l.strip() for l in parts.splitlines() if l.strip().startswith(("-", "*"))]
    return {
        "exists": True,
        "has_unreleased": has_unreleased,
        "unreleased_count": len(unreleased_lines),
        "message": f"CHANGELOG.md 已就緒，[Unreleased] 包含 {len(unreleased_lines)} 條變更紀錄",
    }


def format_report(findings: dict[str, list[dict[str, str]]], changelog_status: dict[str, bool | str]) -> str:
    """Format audit results as a readable markdown terminal report.

    Args:
        findings: Output from audit_conversations.
        changelog_status: Output from check_changelog.

    Returns:
        Formatted report text.
    """
    lines = [
        "# 📋 專案結案完整性審計報告 (Project Integrity Audit Report)",
        "",
        "## 1. 架構決策與錯誤根因覆蓋率",
    ]
    missing_issues = findings["missing_issues"]
    documented_issues = findings["documented_issues"]
    missing_adrs = findings["missing_adrs"]
    documented_adrs = findings["documented_adrs"]

    lines.append(f"- **Known Issues 覆蓋率**：已記錄 {len(documented_issues)} 項，遺漏未建 {len(missing_issues)} 項")
    if missing_issues:
        for item in missing_issues:
            lines.append(f"  ❌ [遺漏 Known Issue] ({item['source']}) {item['lead']}")
    else:
        lines.append("  ✅ 所有對話中出現的錯誤與根因均已建立對應 Known Issue 紀錄！")

    lines.append(f"- **ADR 架構決策覆蓋率**：已記錄 {len(documented_adrs)} 項，遺漏未建 {len(missing_adrs)} 項")
    if missing_adrs:
        for item in missing_adrs:
            lines.append(f"  ❌ [遺漏 ADR] ({item['source']}) {item['lead']}")
    else:
        lines.append("  ✅ 所有對話中重大架構決策均已建立對應 ADR 紀錄！")

    lines.append("")
    lines.append("## 2. 殘留待補完標記 (Lingering TODOs)")
    lingering = findings["lingering_todos"]
    if lingering:
        lines.append(f"⚠️ 偵測到 {len(lingering)} 處檔案仍包含待補完的 TODO 標記：")
        for todo in lingering[:10]:
            lines.append(f"  - `{todo['file']}:{todo['line']}`: {todo['content']}")
        if len(lingering) > 10:
            lines.append(f"  ... 另有 {len(lingering) - 10} 處，請執行完整審計檢查。")
    else:
        lines.append("✅ 文件與對話摘要中無殘留未完成之 TODO 標記。")

    lines.append("")
    lines.append("## 3. 版本變更紀錄 (CHANGELOG)")
    lines.append(f"- {changelog_status.get('message', '')}")
    return "\n".join(lines)


def auto_scaffold_missing(root: Path, findings: dict[str, list[dict[str, str]]]) -> int:
    """Automatically scaffold missing records using adr-issue-tracker.

    Args:
        root: Project root directory.
        findings: Findings with missing items.

    Returns:
        Number of scaffolded records.
    """
    tracker_script = root / ".agents" / "skills" / "adr-issue-tracker" / "scripts" / "tracker_cli.py"
    if not tracker_script.exists():
        logger.warning("Tracker script not found at %s", tracker_script)
        return 0

    import subprocess
    count = 0
    for issue in findings["missing_issues"]:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", issue["lead"].lower()).strip("-")[:30] or "issue-record"
        logger.info("Scaffolding missing issue: %s", slug)
        res = subprocess.run([
            sys.executable, str(tracker_script),
            "--add-issue", slug,
            "--title", issue["lead"],
            "--summary", issue["item"],
            "--agent", "antigravity",
        ], cwd=root, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            count += 1
            print(f"   ✨ 已補建 Known Issue 骨架：{issue['lead']}")

    for adr in findings["missing_adrs"]:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", adr["lead"].lower()).strip("-")[:30] or "adr-record"
        logger.info("Scaffolding missing ADR: %s", slug)
        res = subprocess.run([
            sys.executable, str(tracker_script),
            "--add-adr", slug,
            "--title", adr["lead"],
            "--summary", adr["item"],
            "--agent", "antigravity",
        ], cwd=root, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            count += 1
            print(f"   ✨ 已補建 ADR 骨架：{adr['lead']}")

    return count


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint.

    Args:
        argv: Command line arguments.

    Returns:
        Exit code: 0 on success, 1 on critical missing records.
    """
    parser = argparse.ArgumentParser(description="專案結案完整性審計：檢查對話紀錄、ADR、Known Issues 與文件完整性")
    parser.add_argument("--fix", action="store_true", help="自動補建遺漏的 ADR 與 Known Issue 骨架檔")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式輸出審計結果")
    parser.add_argument("--strict", action="store_true", help="嚴格模式：若有遺漏記錄則回傳非 0 退出碼")
    args = parser.parse_args(argv)

    root = find_root()
    findings = audit_conversations(root)
    changelog_status = check_changelog(root)

    if args.json:
        data = {"findings": findings, "changelog": changelog_status}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    report = format_report(findings, changelog_status)
    print(report)

    if args.fix:
        missing_count = len(findings["missing_issues"]) + len(findings["missing_adrs"])
        if missing_count > 0:
            print(f"\n🛠️ 正在自動為 {missing_count} 項遺漏項目補建骨架檔案...")
            scaffolded = auto_scaffold_missing(root, findings)
            print(f"✅ 完成補建 {scaffolded} 份骨架紀錄。請手動檢視並補齊細節。")

    has_missing = bool(findings["missing_issues"] or findings["missing_adrs"])
    if args.strict and has_missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
