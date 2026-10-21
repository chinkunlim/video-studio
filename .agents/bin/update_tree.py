#!/usr/bin/env python3
"""Directory tree generator for agent-readable project maps.

Purpose:
    Keeps two views of the project structure up to date so any agent can find files
    without exploring the disk:
      1. `docs/architecture/PROJECT_TREE.md` — the full annotated tree.
      2. The block between `<!-- TREE_START -->` and `<!-- TREE_END -->` in `AGENTS.md` —
         a folders-only summary limited to `[tree] agents_md_depth` (default 2), so adding
         a file does not change AGENTS.md (less commit noise, shorter for every agent).
    The legacy markers `PROJECT_TREE_START` / `PROJECT_TREE_END` are also recognised.

Usage:
    python3 scripts/agentctl.py tree           # update files
    python3 scripts/agentctl.py tree --check   # CI: exit 1 when out of date
"""
from __future__ import annotations

import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import load_config  # noqa: E402
from tree_annotations import ANNOTATIONS, IGNORE_NAMES  # noqa: E402

PROJECT_TREE_FILE = ROOT / "docs" / "architecture" / "PROJECT_TREE.md"
# Tool/editor folders agents never need to browse; left out of the AGENTS.md summary only.
SUMMARY_SKIP = {".cursor", ".windsurf", ".vscode", ".github"}
AGENTS_FILE = ROOT / "AGENTS.md"
TREE_BLOCK_RE = re.compile(r"(<!-- (?:PROJECT_)?TREE_START -->\n)[\s\S]*?(\n<!-- (?:PROJECT_)?TREE_END -->)")
NOTE_COLUMN = 44
COLLAPSED_DIRS = {"legacy"}  # shown as one line: old project files waiting to be migrated


@lru_cache(maxsize=1)
def git_ignored_paths() -> frozenset[str]:
    """List git-ignored files and folders so build output never appears in the tree.

    Keeps the tree identical on every machine and in CI (e.g. `*.egg-info`, `target/`,
    `node_modules/` created by installs are skipped).

    Returns:
        Repo-relative paths (folders end with `/`); empty outside a git repository.
    """
    res = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return frozenset(line.strip() for line in res.stdout.splitlines() if line.strip()) if res.returncode == 0 else frozenset()


def is_hidden(entry: Path, rel_path: str) -> bool:
    """Decide whether a path is left out of the tree.

    Args:
        entry: File or folder.
        rel_path: Its repo-relative path.

    Returns:
        True for names in `IGNORE_NAMES` and git-ignored paths.
    """
    ignored = git_ignored_paths()
    return entry.name in IGNORE_NAMES or rel_path in ignored or f"{rel_path}/" in ignored


def generate_tree_lines(
    directory: Path,
    annotations: dict[str, str],
    max_depth: int | None,
    rel_prefix: str = "",
    padding: str = "",
    dirs_only: bool = False,
) -> list[str]:
    """Recursively render a directory as tree lines (`├── name  # note`).

    Args:
        directory: Directory to render.
        annotations: Map of repo-relative path -> short description.
        max_depth: Maximum depth to descend (None = unlimited).
        rel_prefix: Repo-relative path of `directory` ("" for the root).
        padding: Indentation prefix inherited from the parent level.
        dirs_only: Leave files out (used for the AGENTS.md summary).

    Returns:
        Rendered lines, directories first, sorted case-insensitively.
    """
    entries = sorted(
        (
            p for p in directory.iterdir()
            if not is_hidden(p, f"{rel_prefix}/{p.name}" if rel_prefix else p.name)
            and (not dirs_only or (p.is_dir() and (rel_prefix or p.name not in SUMMARY_SKIP)))
        ),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    lines: list[str] = []
    for idx, entry in enumerate(entries):
        is_last = idx == len(entries) - 1
        rel_path = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
        lines.append(_format_line(entry, rel_path, padding, is_last, annotations))
        depth = rel_path.count("/") + 1
        expand = rel_path not in COLLAPSED_DIRS and (max_depth is None or depth < max_depth)
        if entry.is_dir() and not entry.is_symlink() and expand:
            child_padding = padding + ("    " if is_last else "│   ")
            lines.extend(generate_tree_lines(entry, annotations, max_depth, rel_path, child_padding, dirs_only))
    return lines


def _format_line(entry: Path, rel_path: str, padding: str, is_last: bool, annotations: dict[str, str]) -> str:
    """Format one tree line with an optional aligned `# note`.

    Args:
        entry: File or directory being rendered.
        rel_path: Repo-relative path used to look up the annotation.
        padding: Indentation prefix.
        is_last: Whether this is the last entry in its directory.
        annotations: Map of repo-relative path -> short description.

    Returns:
        The formatted line.
    """
    connector = "└── " if is_last else "├── "
    left = f"{padding}{connector}{entry.name}{'/' if entry.is_dir() else ''}"
    note = annotations.get(rel_path, "")
    if not note:
        return left
    return f"{left}{' ' * max(1, NOTE_COLUMN - len(left))}# {note}"


def build_tree_markdown(max_depth: int | None, annotations: dict[str, str], dirs_only: bool = False, title: str = "") -> str:
    """Render the project tree as a fenced Markdown code block.

    Args:
        max_depth: Maximum depth (None = full tree).
        annotations: Map of repo-relative path -> short description.
        dirs_only: Show folders only.
        title: Name on the first line: the project name from `.agents/project.toml`, not the folder
            name, so moving / renaming the folder or a CI checkout does not change the tree.

    Returns:
        Markdown text starting with ```text.
    """
    lines = [f"{title or ROOT.name}/"] + generate_tree_lines(ROOT, annotations, max_depth, dirs_only=dirs_only)
    return "```text\n" + "\n".join(lines) + "\n```"


def _write_if_changed(path: Path, content: str, check_only: bool) -> bool:
    """Write `content` only when it differs from the file on disk.

    Args:
        path: Target file.
        content: Desired content.
        check_only: Only report differences, never write.

    Returns:
        True when the file was (or would be) changed.
    """
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    if not check_only:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


def sync_agents_md(summary: str, check_only: bool) -> bool:
    """Replace the tree block inside `AGENTS.md`.

    Args:
        summary: Depth-limited tree Markdown.
        check_only: Only report differences, never write.

    Returns:
        True when `AGENTS.md` was (or would be) changed.
    """
    if not AGENTS_FILE.exists():
        return False
    agents_text = AGENTS_FILE.read_text(encoding="utf-8")
    if not TREE_BLOCK_RE.search(agents_text):
        print("⚠️ AGENTS.md 缺少 `<!-- TREE_START -->` / `<!-- TREE_END -->` 標記，略過摘要樹更新。", file=sys.stderr)
        return False
    updated = TREE_BLOCK_RE.sub(lambda m: m.group(1) + summary + m.group(2), agents_text)
    return _write_if_changed(AGENTS_FILE, updated, check_only)


def main() -> int:
    """Regenerate both tree views (or verify them with `--check`).

    Returns:
        Process exit code (1 when `--check` finds stale files).
    """
    check_only = "--check" in sys.argv
    config = load_config(ROOT)
    annotations = {**ANNOTATIONS, **config["tree"].get("annotations", {})}
    title = str(config["project"].get("name") or "")
    if not check_only and not PROJECT_TREE_FILE.exists():
        # Create the file first so the generated tree already lists it (otherwise the first run is stale).
        PROJECT_TREE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROJECT_TREE_FILE.touch()
    full_doc = (
        "# 專案完整檔案與資料夾結構樹 (PROJECT_TREE)\n\n"
        "> ⚠️ 本檔案由 `python3 scripts/agentctl.py tree` 自動產生，請勿手動編輯。\n\n"
        f"{build_tree_markdown(None, annotations, title=title)}\n"
    )
    changed = _write_if_changed(PROJECT_TREE_FILE, full_doc, check_only)
    summary = build_tree_markdown(int(config["tree"]["agents_md_depth"]), annotations, dirs_only=True, title=title)
    changed = sync_agents_md(summary, check_only) or changed
    if check_only and changed:
        print("❌ 目錄樹尚未同步，請執行：python3 scripts/agentctl.py tree", file=sys.stderr)
        return 1
    print("✅ 目錄樹已同步 (PROJECT_TREE.md 完整樹 / AGENTS.md 摘要樹)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
