#!/usr/bin/env python3
"""Generate every AI tool's entry file from `AGENTS.md` + `.agents/project.toml`.

Purpose:
    Different AI coding tools read different files. To avoid rules drifting apart,
    `AGENTS.md` and `.agents/project.toml` stay the single source of truth and this
    script writes entry files derived from them (never hand-written rule copies):
      - Claude Code     -> `CLAUDE.md` (imports `@AGENTS.md`) + `.claude/skills` link
      - Gemini CLI      -> `GEMINI.md`
      - GitHub Copilot  -> `.github/copilot-instructions.md`
      - Cursor          -> `.cursor/rules/00-project-constitution.mdc`
      - Windsurf        -> `.windsurf/rules/00-project-constitution.md`
      - Codex / others  -> read `AGENTS.md` directly
    `CLAUDE.md` imports `AGENTS.md` as a whole. Tools without an import feature get the
    block between `<!-- RULES_START -->` and `<!-- RULES_END -->` of `AGENTS.md` copied
    verbatim (relative links rewritten for the entry file's folder), so editing AGENTS.md
    and running `agentctl sync` updates every tool.
    It also writes a Skills index (name, when to use, command) into `AGENTS.md` and every
    entry file, because most tools cannot discover `.agents/skills/` on their own.

Usage:
    python3 scripts/agentctl.py sync
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import layer_names_top_down, load_config  # noqa: E402

SKILLS_BLOCK_RE = re.compile(r"(<!-- SKILLS_START -->\n)[\s\S]*?(\n<!-- SKILLS_END -->)")
RULES_BLOCK_RE = re.compile(r"<!-- RULES_START -->\n([\s\S]*?)\n?<!-- RULES_END -->")
LEGACY_RULES_RE = re.compile(r"^## 1\.[\s\S]*?(?=^## (?:2\.5|3)\b)", flags=re.M)
LINK_RE = re.compile(r"\]\((?!https?:|#|/|mailto:)([^)\s]+)\)")
GENERATED_NOTE = "> ⚠️ 由 `python3 scripts/agentctl.py sync` 自動產生，請勿直接修改；請改 `AGENTS.md` 或 `.agents/project.toml`。"


def installed_skills(root: Path) -> list[tuple[str, str, str]]:
    """List installed skills with their trigger and command.

    Metadata comes from `.agents/skills/catalog.json`; skills missing from the catalog
    fall back to the `description` in their `SKILL.md` front matter.

    Args:
        root: Project root directory.

    Returns:
        Sorted `(name, trigger, command)` tuples.
    """
    skills_dir = root / ".agents" / "skills"
    catalog_file = skills_dir / "catalog.json"
    catalog = json.loads(catalog_file.read_text(encoding="utf-8")).get("skills", {}) if catalog_file.exists() else {}
    rows = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []:
        name = skill_md.parent.name
        meta = catalog.get(name, {})
        match = re.search(r"^description:\s*>?-?\s*(.+)$", skill_md.read_text(encoding="utf-8"), flags=re.M)
        trigger = meta.get("trigger") or (match.group(1).strip() if match else "")
        rows.append((name, trigger, meta.get("command", f"見 .agents/skills/{name}/SKILL.md")))
    return rows


def render_skills_index(root: Path) -> str:
    """Render the Skills index as a Markdown table.

    Args:
        root: Project root directory.

    Returns:
        Markdown table (or a note when no skills are installed).
    """
    rows = installed_skills(root)
    if not rows:
        return "（尚未安裝 skills）"
    lines = ["| Skill | 何時使用 | 指令 |", "|---|---|---|"]
    lines += [f"| `{n}` | {t} | `{c}` |" for n, t, c in rows]
    lines.append("\n詳細步驟：`.agents/skills/<skill>/SKILL.md`")
    return "\n".join(lines)


def extract_rules(root: Path) -> str:
    """Read the rules block of `AGENTS.md` (the text every tool must follow).

    Args:
        root: Project root directory.

    Returns:
        Markdown between the RULES markers; projects created before the markers existed
        fall back to sections 1-2. Empty when `AGENTS.md` is missing.
    """
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.exists() else ""
    match = RULES_BLOCK_RE.search(text) or LEGACY_RULES_RE.search(text)
    if not match:
        return ""
    return (match.group(1) if match.re is RULES_BLOCK_RE else match.group(0)).strip()


def relink(markdown: str, prefix: str) -> str:
    """Rewrite relative Markdown links so they still resolve from a nested entry file.

    Args:
        markdown: Markdown copied from `AGENTS.md` (links relative to the project root).
        prefix: Path from the entry file's folder back to the root, such as `../../`.

    Returns:
        Markdown with relative link targets prefixed.
    """
    return LINK_RE.sub(lambda m: f"]({prefix}{m.group(1)})", markdown) if prefix else markdown


def render_adapter(tool: str, context: dict[str, str]) -> str:
    """Render one tool's entry file.

    Args:
        tool: One of `claude`, `gemini`, `copilot`, `cursor`, `windsurf`.
        context: Values for `name`, `layers`, `test`, `skills`, `rules` (AGENTS.md rules block)
            and `prefix` (relative path to the root).

    Returns:
        File content.
    """
    p = context["prefix"]
    if tool == "claude":
        # Claude Code expands `@AGENTS.md`, so it already gets the rules and the Skills index.
        return f"# CLAUDE.md — {context['name']}\n\n{GENERATED_NOTE}\n\n@AGENTS.md\n"
    rules = relink(context["rules"], p) or f"（`AGENTS.md` 缺少規則段落，請直接閱讀 [`AGENTS.md`]({p}AGENTS.md)）"
    body = f"""{GENERATED_NOTE}

完整規則、文件地圖與規範索引在 [`AGENTS.md`]({p}AGENTS.md)；設定在 [`.agents/project.toml`]({p}.agents/project.toml)。
以下規則段落**直接取自 AGENTS.md**。

- **本專案分層（上 ➔ 下，下層不可 import 上層）**：`{context["layers"]}`
- **測試指令**：`{context["test"]}`

{rules}

## Skills
{context["skills"]}
"""
    if tool == "cursor":
        header = f'---\ndescription: {context["name"]} rules (source: AGENTS.md)\nglobs: "**/*"\nalwaysApply: true\n---\n\n'
        return header + f"# {context['name']} — Cursor Rules\n\n" + body
    titles = {"gemini": "GEMINI.md", "copilot": "GitHub Copilot Instructions", "windsurf": "Windsurf Rules"}
    return f"# {titles[tool]} — {context['name']}\n\n" + body


def link_skill_dirs(root: Path, link_dirs: list[str]) -> list[str]:
    """Point each skill link directory (e.g. `.claude/skills`) at `.agents/skills`.

    Uses a relative symlink; falls back to copying when symlinks are not allowed
    (e.g. Windows without developer mode). These links are per-machine and git-ignored.

    Args:
        root: Project root directory.
        link_dirs: Repo-relative link locations.

    Returns:
        The link directories that were (re)created.
    """
    src = root / ".agents" / "skills"
    if not src.exists():
        return []
    linked = []
    for rel_dir in link_dirs:
        dst = root / rel_dir
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.exists():
            shutil.rmtree(dst)
        try:
            dst.symlink_to(os.path.relpath(src, dst.parent), target_is_directory=True)
        except OSError:
            shutil.copytree(src, dst)
        linked.append(rel_dir)
    return linked


def update_agents_md(root: Path, skills_md: str) -> None:
    """Replace the SKILLS block inside `AGENTS.md`.

    Args:
        root: Project root directory.
        skills_md: Rendered Skills index.
    """
    agents = root / "AGENTS.md"
    if not agents.exists():
        return
    text = agents.read_text(encoding="utf-8")
    if SKILLS_BLOCK_RE.search(text):
        updated = SKILLS_BLOCK_RE.sub(lambda m: m.group(1) + skills_md + m.group(2), text)
        if updated != text:
            agents.write_text(updated, encoding="utf-8")


def sync_adapters(root: Path) -> list[str]:
    """Write every configured entry file, the AGENTS.md skills block, and skill links.

    Args:
        root: Project root directory.

    Returns:
        Repo-relative paths that were written or linked.
    """
    config = load_config(root)
    skills_md = render_skills_index(root)
    context = {
        "name": config["project"].get("name") or root.name,
        "layers": " ➔ ".join(layer_names_top_down(config)),
        "test": config["commands"].get("test") or "(未設定 [commands] test)",
        "skills": skills_md,
        "rules": extract_rules(root),
    }
    targets = {
        "claude": "CLAUDE.md",
        "gemini": "GEMINI.md",
        "copilot": ".github/copilot-instructions.md",
        "cursor": ".cursor/rules/00-project-constitution.mdc",
        "windsurf": ".windsurf/rules/00-project-constitution.md",
    }
    written = []
    for tool in config["agents"].get("adapters", []):
        rel = targets.get(tool)
        if not rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_adapter(tool, {**context, "prefix": "../" * rel.count("/")}), encoding="utf-8")
        written.append(rel)
    update_agents_md(root, skills_md)
    return written + link_skill_dirs(root, list(config["agents"].get("skill_link_dirs", [])))


def main() -> int:
    """Generate the entry files and print what was written.

    Returns:
        Process exit code (always 0).
    """
    items = sync_adapters(ROOT)
    print(f"✅ 已同步 Agent 入口檔與 skills 連結：{', '.join(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
