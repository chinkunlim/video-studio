#!/usr/bin/env python3
"""Migration progress and final acceptance check for projects moved in with the template's `scripts/migrate_project.py`.

Purpose:
    Shows how much of `legacy/` is still waiting to be migrated, and (`--verify`) checks
    every completion criterion in `docs/migration/MIGRATION.md`, so "the migration is
    done" means the whole project meets the new standards, not just that files moved.

Checks in `--verify`:
    1. `legacy/` is gone.
    2. No pip / npm leftovers (`requirements*.txt`, `Pipfile`, `package-lock.json`, `yarn.lock`).
    3. `agentctl check` passes (comments, layers, secrets, lint, mypy, tree).
    4. The project's test command passes.
    5. Every migration task card is `done`.
    6. Every row of the MIGRATION.md file list is ticked (☑).
    7. The template sample code (`create_greeting`, `GreetingRecord`, the sample revision) is gone.
    8. README.md and ARCHITECTURE.md were rewritten for this project; `.env.example` exists.
    9. Develop mode only: no `flask` dependency left in `pyproject.toml`.

`--develop` switches a maintain-mode migration to develop mode: Flask becomes a forbidden
import, a "Flask → FastAPI" task card is created and MIGRATION.md gets the conversion steps.

Usage:
    python3 scripts/agentctl.py migration
    python3 scripts/agentctl.py migration --verify
    python3 scripts/agentctl.py migration --develop
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
PLAN = ROOT / "docs" / "migration" / "MIGRATION.md"
LEFTOVERS = ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "Pipfile", "Pipfile.lock",
             "package-lock.json", "yarn.lock")
FLASK_RULE = "flask:此專案已改為開發模式，Flask 全部改寫成 FastAPI（見 .agents/skills/legacy-migration/FLASK_TO_FASTAPI.md）"
SAMPLE_MARKERS = ("def create_greeting", "class GreetingRecord", '"greetings"')
TEMPLATE_MARKERS = {
    "README.md": "AI-assisted software project with standard structure and agent handoff.",
    "docs/architecture/ARCHITECTURE.md": "TODO: 用幾句話或一張圖說明主要元件",
}


def legacy_files() -> list[str]:
    """List files still inside `legacy/`.

    Returns:
        Repo-relative paths.
    """
    folder = ROOT / "legacy"
    return sorted(p.relative_to(ROOT).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


def migration_tasks() -> list[dict]:
    """Load the task cards created for migration batches.

    Returns:
        Task dictionaries whose title starts with `遷移批次`.
    """
    folder = ROOT / ".agents" / "tasks"
    tasks: list[dict] = []
    for f in sorted(folder.glob("TASK-*.json")) if folder.exists() else []:
        data = json.loads(f.read_text(encoding="utf-8"))
        if str(data.get("title", "")).startswith("遷移批次"):
            tasks.append(data)
    return tasks


def checklist_counts() -> tuple[int, int]:
    """Count ticked and unticked rows in the MIGRATION.md file list.

    Returns:
        Tuple of (done, remaining).
    """
    text = PLAN.read_text(encoding="utf-8") if PLAN.exists() else ""
    return text.count("| ☑ |"), text.count("| ☐ |")


def run(cmd: str) -> int:
    """Run a shell command in the project root and return its exit code.

    Args:
        cmd: Command line.

    Returns:
        Exit code.
    """
    print(f"$ {cmd}")
    return subprocess.run(cmd, shell=True, cwd=ROOT, check=False).returncode


def test_command() -> str:
    """Read `[commands] test` from `.agents/project.toml`.

    Returns:
        The command, or an empty string when none is configured.
    """
    sys.path.insert(0, str(ROOT / ".agents" / "lib"))
    import project_config  # type: ignore

    return str(project_config.load_config(ROOT)["commands"].get("test", "")).strip()


def sample_code_left() -> list[str]:
    """Find template sample code that should be replaced by the real program.

    Returns:
        Files under `src/` and `alembic/versions/` that still contain the greeting sample.
    """
    files = [p for d in (ROOT / "src", ROOT / "alembic" / "versions") if d.exists() for p in d.rglob("*.py")]
    return [p.relative_to(ROOT).as_posix() for p in files if any(m in p.read_text(encoding="utf-8") for m in SAMPLE_MARKERS)]


def project_toml_text() -> str:
    """Read `.agents/project.toml`.

    Returns:
        File text (empty when missing).
    """
    path = ROOT / ".agents" / "project.toml"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def is_develop_mode() -> bool:
    """Tell whether Flask is forbidden (develop mode).

    Returns:
        True when `forbidden_imports` contains a `flask` entry.
    """
    line = next((ln for ln in project_toml_text().splitlines() if ln.startswith("forbidden_imports")), "")
    return '"flask' in line


def flask_dependency_left() -> bool:
    """Check whether `pyproject.toml` still declares Flask.

    Returns:
        True when a `flask` dependency is present.
    """
    pyproject = ROOT / "pyproject.toml"
    return pyproject.exists() and re.search(r'"flask(\[|[<>=~! "]|$)', pyproject.read_text(encoding="utf-8").lower()) is not None


def verify() -> list[tuple[bool, str]]:
    """Evaluate every completion criterion.

    Returns:
        `(passed, description)` pairs.
    """
    tasks = migration_tasks()
    done, remaining = checklist_counts()
    leftovers = [str(p.relative_to(ROOT)) for d in (ROOT, ROOT / "gas", ROOT / "web") for n in LEFTOVERS if (p := d / n).exists()]
    untouched = [rel for rel, marker in TEMPLATE_MARKERS.items() if (ROOT / rel).exists() and marker in (ROOT / rel).read_text(encoding="utf-8")]
    test = test_command()
    return [
        (not legacy_files(), f"legacy/ 已清空（剩 {len(legacy_files())} 個檔案）"),
        (not leftovers, "沒有 pip / npm 遺留檔" + (f"：{', '.join(leftovers)}" if leftovers else "")),
        # the interpreter path may contain spaces, e.g. ".../01 project_template/.venv" (Refs: ISSUE-002)
        (run(f"{shlex.quote(sys.executable)} scripts/agentctl.py check") == 0, "agentctl check 通過（註解、分層、秘密、lint、型別、目錄樹）"),
        (not test or run(test) == 0, f"測試通過（{test or '未設定 [commands] test'}）"),
        (all(t.get("status") == "done" for t in tasks), f"遷移任務卡全部完成（{sum(t.get('status') == 'done' for t in tasks)}/{len(tasks)}）"),
        (remaining == 0, f"MIGRATION.md 檔案清單全部打勾（☑ {done} / ☐ {remaining}）"),
        (not sample_code_left(), "範本範例程式已移除" + (f"：{', '.join(sample_code_left())}" if sample_code_left() else "")),
        (not untouched, "README.md / ARCHITECTURE.md 已改寫" + (f"：尚未改寫 {', '.join(untouched)}" if untouched else "")),
        ((ROOT / ".env.example").exists(), ".env.example 存在"),
    ] + ([(not flask_dependency_left(), "開發模式：pyproject.toml 已沒有 flask 依賴")] if is_develop_mode() else [])


def switch_to_develop() -> int:
    """Switch a maintain-mode migration to develop mode (Flask must be rewritten to FastAPI).

    Returns:
        Process exit code (0 on success, 0 with a note when already in develop mode).
    """
    if is_develop_mode():
        print("ℹ️ 已經是開發模式。")
        return 0
    toml = ROOT / ".agents" / "project.toml"
    text = re.sub(r"^forbidden_imports = .*$", lambda _m: f'forbidden_imports = ["{FLASK_RULE}"]', project_toml_text(), flags=re.M)
    toml.write_text(text, encoding="utf-8")
    title = "遷移批次（開發模式）：Flask → FastAPI 改寫（路由、請求驗證、模板 / 靜態檔）"
    subprocess.run([sys.executable, ".agents/bin/agent_task.py", "create", title, "--paths", "src"], cwd=ROOT, check=True)
    section = (
        "\n## 7. 開發模式：Flask → FastAPI\n\n"
        "此專案已改為開發模式：`import flask` 會被 code-review-guard 擋下，`--verify` 要求 `pyproject.toml` 沒有 flask。\n"
        "改寫步驟與對照表：[`FLASK_TO_FASTAPI.md`](../../.agents/skills/legacy-migration/FLASK_TO_FASTAPI.md)。\n"
    )
    PLAN.write_text(PLAN.read_text(encoding="utf-8").rstrip() + "\n" + section, encoding="utf-8")
    print("✅ 已切換為開發模式：Flask 列為禁止 import，已建立改寫任務卡，MIGRATION.md 已加上步驟。")
    return 0


def print_status() -> None:
    """Print migration progress."""
    files = legacy_files()
    done, remaining = checklist_counts()
    print(f"📦 legacy/ 剩 {len(files)} 個檔案；MIGRATION.md 清單 ☑ {done} / ☐ {remaining}")
    for t in migration_tasks():
        print(f"  {t['id']:<9} {t.get('status', ''):<12} {t.get('agent') or '-':<14} {t.get('title', '')}")
    nxt = next((t for t in migration_tasks() if t.get("status") != "done"), None)
    if nxt:
        print(f"👉 下一批：agentctl task claim {nxt['id']} --agent <名字>（步驟見 .agents/skills/legacy-migration/SKILL.md）")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        0 when (with `--verify`) every criterion passes, otherwise 1.
    """
    parser = argparse.ArgumentParser(description="遷移進度與完成驗收")
    parser.add_argument("--verify", action="store_true", help="逐項檢查遷移完成標準")
    parser.add_argument("--develop", action="store_true", help="切換為開發模式（Flask 全部改寫成 FastAPI）")
    args = parser.parse_args(argv)
    if not PLAN.exists():
        print("ℹ️ 這個專案沒有 docs/migration/MIGRATION.md（不是遷移專案）。")
        return 0
    if args.develop:
        return switch_to_develop()
    print_status()
    if not args.verify:
        return 0
    results = verify()
    print("\n🧾 遷移完成驗收")
    for passed, desc in results:
        print(f"  {'✅' if passed else '❌'} {desc}")
    ok = all(p for p, _ in results)
    print("🎉 遷移完成，整個專案符合新規範。" if ok else "⏳ 尚未完成，請依 ❌ 項目處理。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
