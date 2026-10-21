#!/usr/bin/env python3
"""Update an existing project's framework files from the template, safely.

Purpose:
    The template (`01 project_template`) keeps improving; existing projects should get
    those improvements without losing their own edits. `.agents/framework.lock` stores
    the SHA-256 of every framework file as it was installed, so each file is classified:
      - unchanged in the project      -> overwritten with the new template version
      - modified by the project, or not
        recorded in the lock (old projects) -> NOT overwritten; the template version is saved
                                         next to it as `<file>.template` for manual merging
      - new in the template           -> added
      - removed from the template     -> reported only (never deleted automatically)
    Skills follow `[skills] enabled` in `.agents/project.toml` (core skills are always kept).
    Project-owned files (`.agents/project.toml`, `AGENTS.md`, `README.md`, `src/`, `docs/`
    except `docs/standards/`, tests) are never touched.

Usage:
    python3 scripts/agentctl.py update --from "/path/to/01 project_template" --dry-run
    python3 scripts/agentctl.py update --from "/path/to/01 project_template"
    # From the template, for a project whose own copy of this script is older (v3.1 and before):
    python3 .agents/bin/update_framework.py --from . --project "/path/to/project"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root (`--project` overrides)
sys.path.insert(0, str(ROOT / ".agents" / "lib"))
# The template's own layout matches a project's; these files exist only in the template.
TEMPLATE_MARKERS = (Path("scripts") / "init_project.py", Path(".agents") / "lib" / "framework_install.py")

from project_config import load_config  # noqa: E402


def load_template_modules(template_dir: Path):
    """Import the template's installer module and framework version.

    Args:
        template_dir: Root of the template folder.

    Returns:
        Tuple of the `framework_install` module and the template's framework version.
    """
    sys.path.insert(0, str(template_dir / ".agents" / "lib"))
    import importlib

    for name in ("framework_install", "project_config"):
        sys.modules.pop(name, None)
    installer = importlib.import_module("framework_install")
    template_config = importlib.import_module("project_config")
    version = template_config.FRAMEWORK_VERSION
    sys.path.pop(0)
    for name in ("framework_install", "project_config"):
        sys.modules.pop(name, None)
    return installer, version


def classify(mapping: dict[str, Path], lock_files: dict[str, str], sha256_of) -> dict[str, list[str]]:
    """Decide what to do with every framework file.

    Args:
        mapping: Destination path -> template source path.
        lock_files: Destination path -> SHA-256 recorded at install time.
        sha256_of: Hash function taking a `Path`.

    Returns:
        Dict with lists `update`, `add`, `same`, `conflict`, `removed`.
    """
    plan: dict[str, list[str]] = {"update": [], "add": [], "same": [], "conflict": [], "removed": []}
    for rel, src in sorted(mapping.items()):
        current = ROOT / rel
        current_hash = sha256_of(current)
        if not current.exists():
            plan["add"].append(rel)
        elif current_hash == sha256_of(src):
            plan["same"].append(rel)
        elif lock_files.get(rel) != current_hash:  # edited by the project, or unknown (no lock entry)
            plan["conflict"].append(rel)
        else:
            plan["update"].append(rel)
    plan["removed"] = sorted(rel for rel in lock_files if rel not in mapping and (ROOT / rel).exists())
    return plan


def print_plan(plan: dict[str, list[str]]) -> None:
    """Print the update plan.

    Args:
        plan: Output of `classify()`.
    """
    labels = {
        "update": "🔄 更新", "add": "➕ 新增", "conflict": "⚠️ 專案已修改（不覆蓋，另存 .template）",
        "removed": "🗑️ 母版已移除（請自行確認是否刪除）",
    }
    for key, label in labels.items():
        for rel in plan[key]:
            print(f"  {label}: {rel}")
    print(f"  ✅ 相同：{len(plan['same'])} 個檔案")


def apply_plan(plan: dict[str, list[str]], mapping: dict[str, Path], installer) -> list[str]:
    """Copy updated/new files and write `.template` copies for conflicts.

    Args:
        plan: Output of `classify()`.
        mapping: Destination path -> template source path.
        installer: The template's `framework_install` module.

    Returns:
        Destination paths that now match the template (for the new lock).
    """
    installer.install_files(ROOT, {rel: mapping[rel] for rel in plan["update"] + plan["add"]})
    for rel in plan["conflict"]:
        shutil.copy2(mapping[rel], ROOT / f"{rel}.template")
    return plan["update"] + plan["add"] + plan["same"]


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="從母版安全更新框架檔案（不覆蓋專案修改過的檔案）")
    parser.add_argument("--from", dest="template_dir", required=True, help="母版資料夾 (01 project_template)")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼")
    parser.add_argument("--project", help="要更新的專案（預設：這個腳本所在的專案）")
    args = parser.parse_args(argv)

    global ROOT
    if args.project:
        ROOT = Path(args.project).expanduser().resolve()
    template_dir = Path(args.template_dir).expanduser().resolve()
    if not all((template_dir / marker).exists() for marker in TEMPLATE_MARKERS):
        print(f"❌ 不是有效的母版資料夾（需 3.2 以上）：{template_dir}", file=sys.stderr)
        return 1
    if ROOT == template_dir:
        print("❌ 母版不能更新自己：框架檔案在母版就是最新版本。", file=sys.stderr)
        return 1
    installer, version = load_template_modules(template_dir)
    config = load_config(ROOT)
    catalog = installer.load_catalog(template_dir)
    enabled = [s for s in config["skills"].get("enabled", []) if s in catalog]
    languages = [config["project"].get("stack", "generic"), *config["project"].get("addons", [])]
    skills = installer.select_skills(catalog, languages, enabled)
    mapping = installer.framework_file_map(template_dir, skills)
    lock = installer.read_lock(ROOT)
    plan = classify(mapping, lock.get("files", {}), installer.sha256_of)

    print(f"📦 框架 v{lock.get('framework_version', '?')} ➔ v{version}（skills: {', '.join(skills)}）")
    print_plan(plan)
    if args.dry_run:
        return 0
    current = apply_plan(plan, mapping, installer)
    kept = {rel: h for rel, h in lock.get("files", {}).items() if rel in plan["conflict"]}
    installer.write_lock(ROOT, template_dir, version, skills, current)
    if kept:  # keep the original install hash so conflicts stay detectable next time
        lock_path = ROOT / installer.LOCK_RELATIVE_PATH
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["files"].update(kept)
        lock_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for script in ("sync_agent_adapters.py", "update_tree.py"):
        subprocess.run([sys.executable, str(ROOT / ".agents" / "bin" / script)], cwd=ROOT, check=False, capture_output=True)
    print(f"✅ 已更新 {len(plan['update']) + len(plan['add'])} 個檔案；{len(plan['conflict'])} 個衝突請手動合併 (*.template)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
