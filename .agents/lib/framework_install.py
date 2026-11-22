"""Shared install logic for the template's `scripts/init_project.py` and `.agents/bin/update_framework.py`.

Purpose:
    Defines in one place which template files a project receives, where they go,
    which skills are selected, and how the installed state is recorded in
    `.agents/framework.lock` (version, template commit, SHA-256 of every file).
    The lock lets `update_framework.py` tell "unchanged framework file" (safe to
    overwrite) from "file the project customised" (must not be overwritten).

Main functions:
    - `load_catalog()`        : read `.agents/skills/catalog.json`.
    - `select_skills()`       : core + stack-specific + explicitly requested skills.
    - `framework_file_map()`  : destination path -> template source path.
    - `install_files()`       : copy files and mark scripts executable.
    - `write_lock()` / `read_lock()` : persist / load `.agents/framework.lock`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

LOCK_RELATIVE_PATH = Path(".agents") / "framework.lock"
SKIP_PARTS = {"upstream", "__pycache__", ".DS_Store", "node_modules"}
# The template is laid out like the projects it creates, so a framework file has the same
# relative path in both. These folders are copied as a whole (`.agents/skills/` per skill).
FRAMEWORK_FOLDERS = (".agents/lib", ".agents/bin", ".agents/hooks", "docs/standards")
FRAMEWORK_FILES = ("scripts/agentctl.py", ".agents/skills/catalog.json", ".graphifyignore")
# Files in those folders that belong to the template as a project, not to the framework.
PROJECT_OWNED = {"docs/standards/PROJECT_RULES.md"}


def load_catalog(template_root: Path) -> dict[str, dict]:
    """Read the skill catalog of the template.

    Args:
        template_root: Root of the `01 project_template` folder.

    Returns:
        Mapping of skill name -> metadata (`tier`, `stacks`, `trigger`, `command`).
    """
    path = template_root / ".agents" / "skills" / "catalog.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("skills", {})


def select_skills(catalog: dict[str, dict], languages: list[str], requested: list[str]) -> list[str]:
    """Choose which skills a project gets.

    Args:
        catalog: Skill catalog from `load_catalog()`.
        languages: Base stack plus add-ons, e.g. `["python", "web", "gas"]`.
        requested: Extra skill names asked for explicitly (any tier).

    Returns:
        Sorted skill names: every core skill, stack skills matching any language, plus `requested`.

    Raises:
        ValueError: When a requested skill is not in the catalog.
    """
    unknown = [name for name in requested if name not in catalog]
    if unknown:
        raise ValueError(f"Unknown skill(s): {', '.join(unknown)}. Available: {', '.join(sorted(catalog))}")
    chosen = {
        name
        for name, meta in catalog.items()
        if meta.get("tier") == "core" or (meta.get("tier") == "stack" and set(languages) & set(meta.get("stacks", [])))
    }
    return sorted(chosen | set(requested))


def _iter_files(folder: Path) -> list[Path]:
    """List files below `folder`, skipping caches and upstream reference clones.

    Args:
        folder: Directory to walk.

    Returns:
        Sorted file paths.
    """
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.rglob("*") if p.is_file() and not SKIP_PARTS.intersection(p.relative_to(folder).parts) and p.suffix != ".pyc"
    )


def framework_file_map(template_root: Path, skills: list[str]) -> dict[str, Path]:
    """Map every framework-managed destination path to its template source.

    Args:
        template_root: Root of the template folder.
        skills: Skill names to include.

    Returns:
        Dict of repo-relative destination path -> absolute source path.
    """
    mapping: dict[str, Path] = {}
    for folder in FRAMEWORK_FOLDERS:
        for f in _iter_files(template_root / folder):
            mapping[(f.relative_to(template_root)).as_posix()] = f
    for rel in FRAMEWORK_FILES:
        if (template_root / rel).is_file():
            mapping[rel] = template_root / rel
    for name in skills:
        skill_dir = template_root / ".agents" / "skills" / name
        for f in _iter_files(skill_dir):
            mapping[f.relative_to(template_root).as_posix()] = f
    for rel in PROJECT_OWNED:
        mapping.pop(rel, None)
    return mapping


def install_files(target_root: Path, mapping: dict[str, Path]) -> list[str]:
    """Copy mapped files into the project and make scripts/hooks executable.

    Args:
        target_root: Project root directory.
        mapping: Output of `framework_file_map()` (possibly filtered).

    Returns:
        Repo-relative paths that were written.
    """
    written: list[str] = []
    for rel, src in sorted(mapping.items()):
        dst = target_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if rel.startswith(".agents/hooks/") or src.read_bytes()[:2] == b"#!":
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(rel)
    return written


def sha256_of(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Args:
        path: File to hash.

    Returns:
        Hex digest, or an empty string when the file does not exist.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def template_commit(template_root: Path) -> str:
    """Return the template's current git commit (marks uncommitted edits with `+dirty`).

    Args:
        template_root: Root of the template folder.

    Returns:
        Short commit SHA, `+dirty` suffixed when the working tree has changes, or `unversioned`.
    """
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=template_root, capture_output=True, text=True)
    if head.returncode != 0:
        return "unversioned"
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=template_root, capture_output=True, text=True).stdout.strip()
    return head.stdout.strip() + ("+dirty" if dirty else "")


def write_lock(target_root: Path, template_root: Path, version: str, skills: list[str], files: list[str]) -> Path:
    """Record the installed framework state in `.agents/framework.lock`.

    Args:
        target_root: Project root directory.
        template_root: Template the files came from.
        version: Framework version string.
        skills: Installed skill names.
        files: Repo-relative framework files to hash.

    Returns:
        Path of the lock file.
    """
    lock = {
        "framework_version": version,
        "template_commit": template_commit(template_root),
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skills": sorted(skills),
        "files": {rel: sha256_of(target_root / rel) for rel in sorted(files)},
    }
    path = target_root / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_lock(target_root: Path) -> dict:
    """Load `.agents/framework.lock` (empty structure when missing, e.g. pre-3.0 projects).

    Args:
        target_root: Project root directory.

    Returns:
        Lock data with at least `skills` and `files` keys.
    """
    path = target_root / LOCK_RELATIVE_PATH
    if not path.exists():
        return {"skills": [], "files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_rules_block(agents_md: Path) -> str:
    """Extract text between `<!-- RULES_START -->` and `<!-- RULES_END -->`.

    Args:
        agents_md: Path to `AGENTS.md`.

    Returns:
        The extracted rules section, or an empty string if the markers are absent.
    """
    if not agents_md.is_file():
        return ""
    text = agents_md.read_text(encoding="utf-8", errors="replace")
    start_marker, end_marker = "<!-- RULES_START -->", "<!-- RULES_END -->"
    if start_marker not in text or end_marker not in text:
        return ""
    return text.split(start_marker, 1)[1].split(end_marker, 1)[0]


def _rule_numbers(block: str) -> set[int]:
    """Extract numbered core rule indices (`N. **...`) from an AGENTS.md rules block.

    Args:
        block: Text extracted by `_extract_rules_block()`.

    Returns:
        Set of integer rule numbers found.
    """
    return {int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\.\s+\*\*", block, flags=re.M)}


def _load_project_cfg(project_root: Path) -> dict:
    """Load `.agents/project.toml` using `project_config` without polluting module cache.

    Args:
        project_root: Project root directory.

    Returns:
        Merged project configuration dictionary.
    """
    lib_dir = project_root / ".agents" / "lib"
    if not (lib_dir / "project_config.py").exists():
        lib_dir = Path(__file__).resolve().parent
    lib_str = str(lib_dir)
    if lib_str not in sys.path:
        sys.path.insert(0, lib_str)
    import project_config  # type: ignore

    return project_config.load_config(project_root)


def _check_rules_drift(project_root: Path, template_root: Path | None) -> list[str]:
    """Detect missing core rules or commands in `AGENTS.md` relative to the template.

    Args:
        project_root: Project root directory.
        template_root: Optional template root directory for direct comparison.

    Returns:
        List of drift findings for `AGENTS.md`.
    """
    findings: list[str] = []
    proj_block = _extract_rules_block(project_root / "AGENTS.md")
    if not proj_block:
        return ["AGENTS.md 缺少 <!-- RULES_START -->..<!-- RULES_END --> 規則區段（請補齊後執行 agentctl sync）"]
    expected_nums = set(range(1, 16))
    need_scan = (project_root / ".agents" / "skills" / "compliance-scanner").is_dir()
    if template_root and (template_root / "AGENTS.md").is_file():
        tpl_block = _extract_rules_block(template_root / "AGENTS.md")
        expected_nums = _rule_numbers(tpl_block) or expected_nums
        need_scan = "agentctl.py scan" in tpl_block
    missing_nums = sorted(expected_nums - _rule_numbers(proj_block))
    if missing_nums:
        nums_str = ", ".join(str(n) for n in missing_nums)
        findings.append(f"AGENTS.md 核心規則落後母版，缺少規則編號：{nums_str}（請同步 AGENTS.md 並執行 agentctl sync）")
    if need_scan and "agentctl.py scan" not in proj_block:
        findings.append("AGENTS.md 核心規則區段缺少 `agentctl.py scan` 觸發指令（請同步 AGENTS.md 並執行 agentctl sync）")
    return findings


def _check_skills_drift(project_root: Path, template_root: Path | None) -> list[str]:
    """Compare `[skills] enabled` in `.agents/project.toml` against installed skills and core catalog.

    Args:
        project_root: Project root directory.
        template_root: Optional template root directory holding `catalog.json`.

    Returns:
        List of drift findings for `[skills] enabled`.
    """
    cfg = _load_project_cfg(project_root)
    enabled = {str(s) for s in cfg.get("skills", {}).get("enabled", []) if str(s).strip()}
    if not enabled:
        return []
    skills_dir = project_root / ".agents" / "skills"
    installed = (
        {d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()}
        if skills_dir.is_dir()
        else set()
    )
    catalog = load_catalog(template_root or project_root)
    core_skills = {k for k, v in catalog.items() if v.get("tier") == "core"}
    findings: list[str] = []
    missing_core = sorted(core_skills - enabled)
    missing_dirs = sorted(enabled - installed)
    unlisted = sorted(installed - enabled)
    if missing_core:
        findings.append(f"[skills] enabled 缺少核心技能：{', '.join(missing_core)}")
    if missing_dirs:
        findings.append(f"[skills] enabled 列出但未安裝的技能：{', '.join(missing_dirs)}")
    if unlisted:
        findings.append(f"已安裝但未列入 [skills] enabled 的技能：{', '.join(unlisted)}")
    return findings


def detect_framework_drift(project_root: Path, template_root: Path | None = None) -> list[str]:
    """Detect project-owned config/doc drift from template standards (AGENTS.md rules & skills list).

    Args:
        project_root: Project root directory to inspect.
        template_root: Optional template directory (`01 project_template`); defaults to built-in expectations.

    Returns:
        Human-readable drift warning strings (empty when aligned).
    """
    return _check_rules_drift(project_root, template_root) + _check_skills_drift(project_root, template_root)
