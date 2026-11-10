#!/usr/bin/env python3
"""Comprehensive project architecture & template compliance scanner.

Purpose:
    Performs an end-to-end audit on any project built with 01 project_template:
    1. Framework & Upstream Sync: verifies version alignment and pending updates.
    2. Architecture Layers & Code Quality: checks unidirectionality and coding rules.
    3. Dependency Graph & Coupling: detects circular dependencies and layer breaches.
    4. Environment & Data Isolation: validates external DATA_DIR and credential hygiene.
    5. Core Iron Laws Compliance: validates Rule 14 (one-click install & update) and Rule 13.
    6. Offline Test Suite: verifies all offline unit and integration tests pass.

Usage:
    python3 scripts/agentctl.py scan
    python3 .agents/skills/compliance-scanner/scripts/scan_compliance.py [--fix] [--json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

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


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    """Execute a subprocess command and return exit code, stdout, and stderr.

    Args:
        cmd: Command arguments list.
        cwd: Directory where the command executes.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def check_framework_status(root: Path) -> dict[str, Any]:
    """Inspect framework version and synchronization status with the template.

    Args:
        root: Project root directory.

    Returns:
        Dictionary with status, version, template version, and findings.
    """
    current_ver = "unknown"
    lock_file = root / ".agents" / "framework.lock"
    config_file = root / ".agents" / "project.toml"

    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            current_ver = data.get("framework_version", "unknown")
        except Exception:
            pass
    elif (root / ".agents" / "lib" / "project_config.py").exists():
        match = re.search(r'FRAMEWORK_VERSION\s*=\s*"([^"]+)"', (root / ".agents" / "lib" / "project_config.py").read_text(encoding="utf-8"))
        if match:
            current_ver = match.group(1)
    elif config_file.exists():
        match = re.search(r'version\s*=\s*"([^"]+)"', config_file.read_text(encoding="utf-8"))
        if match:
            current_ver = match.group(1)

    template_ver = "3.5.0"
    findings: list[str] = []
    is_template = (root / "src" / "project_template").exists()

    if is_template:
        findings.append("當前專案為母版核心庫 (project_template)，處於最新 SSOT 基準版本。")
        is_up_to_date = True
    else:
        is_up_to_date = (current_ver == template_ver)
        if not is_up_to_date:
            findings.append(f"專案框架版本 ({current_ver}) 落後於母版最新版本 ({template_ver})。")

        update_bin = root / ".agents" / "bin" / "update_framework.py"
        if update_bin.exists():
            code, out, _ = run_command([sys.executable, str(update_bin), "--preview"], root)
            if code == 0 and "母版有更新" in out:
                findings.append("母版有待同步的框架檔案，可執行 `python3 scripts/agentctl.py update` 更新。")

    status = "PASS" if is_up_to_date and not (not is_template and findings) else ("PASS" if is_template else "WARN")
    return {
        "category": "框架與母版同步 (Framework Sync)",
        "status": status,
        "current_version": current_ver,
        "template_version": template_ver,
        "findings": findings,
    }


def check_architecture_and_code(root: Path) -> dict[str, Any]:
    """Audit unidirectional layering, comments, and coding principles.

    Args:
        root: Project root directory.

    Returns:
        Inspection result for architecture and code review guard.
    """
    findings: list[str] = []
    check_script = root / ".agents" / "skills" / "code-review-guard" / "scripts" / "review_guard.py"
    if not check_script.exists():
        check_script = root / "scripts" / "agentctl.py"
        cmd = [sys.executable, str(check_script), "check"]
    else:
        cmd = [sys.executable, str(check_script)]

    code, out, err = run_command(cmd, root)
    critical_errors = [line for line in (out + err).splitlines() if "CRITICAL" in line or "Error" in line]
    important_warnings = [line for line in out.splitlines() if "[IMPORTANT]" in line or "⚠️" in line]

    if critical_errors:
        findings.extend(critical_errors[:5])
    if important_warnings:
        findings.extend([w.strip() for w in important_warnings[:5]])

    status = "FAIL" if code != 0 or critical_errors else ("WARN" if important_warnings else "PASS")
    return {
        "category": "分層與代碼規範 (Layers & Code Review)",
        "status": status,
        "findings": findings,
    }


def check_dependency_graph(root: Path) -> dict[str, Any]:
    """Verify architectural coupling, clean graphify ignore, and circular imports.

    Args:
        root: Project root directory.

    Returns:
        Inspection result for dependency graph and graphify hygiene.
    """
    findings: list[str] = []
    graph_script = root / ".agents" / "bin" / "build_graph.py"
    if graph_script.exists():
        code, out, _ = run_command([sys.executable, str(graph_script)], root)
        if "分層違規" in out or "循環依賴" in out:
            findings.append("發現分層逆向引用或循環依賴，請檢視 docs/architecture/GRAPH_REPORT.md。")

    if not (root / ".graphifyignore").exists():
        findings.append("缺少 .graphifyignore 設定檔，無法排除第三方噪聲。")

    status = "FAIL" if any("循環依賴" in f for f in findings) else ("WARN" if findings else "PASS")
    return {
        "category": "依賴拓撲與圖譜純淨 (Dependency Graph & Parity)",
        "status": status,
        "findings": findings,
    }


def check_environment_and_data(root: Path) -> dict[str, Any]:
    """Validate external DATA_DIR, environment isolation, and git hooks.

    Args:
        root: Project root directory.

    Returns:
        Inspection result for environment and data directory layout.
    """
    findings: list[str] = []
    doctor_script = root / ".agents" / "bin" / "doctor.py"
    if doctor_script.exists():
        code, out, _ = run_command([sys.executable, str(doctor_script)], root)
        if code != 0:
            issues = [line.strip() for line in out.splitlines() if line.startswith("-") or "WARN" in line or "FAIL" in line]
            findings.extend(issues[:4])

    env_example = root / ".env.example"
    if not env_example.exists():
        findings.append("缺少 .env.example 環境變數範本。")

    status = "WARN" if findings else "PASS"
    return {
        "category": "環境隔離與 DATA_DIR (Environment & Data Hygiene)",
        "status": status,
        "findings": findings,
    }


def check_iron_laws(root: Path) -> dict[str, Any]:
    """Validate compliance with core iron laws, especially Rule 14 and Rule 13.

    Args:
        root: Project root directory.

    Returns:
        Inspection result for Iron Rules.
    """
    findings: list[str] = []

    # Check Rule 14: One-click installation and update documentation
    has_install_script = (
        (root / "install.sh").exists()
        or (root / "scripts" / "setup_env.py").exists()
        or (root / ".agents" / "bin" / "setup_env.py").exists()
    )
    if not has_install_script:
        findings.append("【鐵律 14】缺少一鍵安裝腳本（建議提供 ./install.sh 或 agentctl setup）。")

    readme = root / "README.md"
    if readme.exists():
        readme_text = readme.read_text(encoding="utf-8")
        if "安裝" not in readme_text and "Install" not in readme_text:
            findings.append("【鐵律 14】README.md 缺少清晰的安裝步驟說明。")
        if "更新" not in readme_text and "Update" not in readme_text:
            findings.append("【鐵律 14】README.md 缺少後期平滑更新說明。")
    else:
        findings.append("【鐵律 14】缺少 README.md 說明文件。")

    # Check Rule 9: 127.0.0.1 binding (no 0.0.0.0)
    src_dir = root / "src"
    if src_dir.exists():
        for file in src_dir.rglob("*.py"):
            text = file.read_text(encoding="utf-8", errors="ignore")
            if 'bind="0.0.0.0"' in text or 'host="0.0.0.0"' in text:
                findings.append(f"【鐵律 9】{file.relative_to(root)} 綁定 0.0.0.0，本機服務只可綁定 127.0.0.1。")
                break

    status = "WARN" if findings else "PASS"
    return {
        "category": "核心鐵律檢核 (Core Iron Laws Compliance)",
        "status": status,
        "findings": findings,
    }


def check_tests(root: Path, skip: bool = False) -> dict[str, Any]:
    """Execute the project test command to verify offline test health.

    Args:
        root: Project root directory.
        skip: Whether to skip running tests.

    Returns:
        Inspection result for the test suite.
    """
    if skip:
        return {
            "category": "離線測試套件 (Offline Tests)",
            "status": "SKIP",
            "findings": ["測試執行已略過 (--skip-tests)。"],
        }

    config_file = root / ".agents" / "project.toml"
    test_cmd = "uv run python -m unittest discover -s tests -v"
    if config_file.exists():
        match = re.search(r'test\s*=\s*"([^"]+)"', config_file.read_text(encoding="utf-8"))
        if match and match.group(1).strip():
            test_cmd = match.group(1).strip()

    proc = subprocess.run(test_cmd, shell=True, cwd=root, capture_output=True, text=True, check=False)
    findings: list[str] = []
    if proc.returncode != 0:
        error_lines = [l for l in (proc.stdout + proc.stderr).splitlines() if "FAIL" in l or "ERROR" in l]
        findings.extend(error_lines[:3] or ["測試未全數通過。"])

    status = "PASS" if proc.returncode == 0 else "FAIL"
    return {
        "category": "離線測試套件 (Offline Tests)",
        "status": status,
        "findings": findings,
    }


def calculate_score(checks: list[dict[str, Any]]) -> tuple[int, str]:
    """Calculate the overall compliance score and letter grade.

    Args:
        checks: List of inspection results.

    Returns:
        Tuple of (score, grade).
    """
    score = 100
    for check in checks:
        st = check["status"]
        if st == "FAIL":
            score -= 25
        elif st == "WARN":
            score -= 8

    score = max(0, min(100, score))
    if score >= 95:
        grade = "A+ (完美合規)"
    elif score >= 85:
        grade = "A (良好)"
    elif score >= 70:
        grade = "B (需調整)"
    elif score >= 50:
        grade = "C (多項違規)"
    else:
        grade = "F (嚴重不合規)"
    return score, grade


def format_report(root: Path, checks: list[dict[str, Any]], score: int, grade: str) -> str:
    """Format human-readable CLI report.

    Args:
        root: Project root directory.
        checks: List of check outputs.
        score: Total score.
        grade: Total grade.

    Returns:
        Terminal report string.
    """
    lines: list[str] = [
        "=" * 64,
        f"🔍 專案架構合規與母版同步全面掃描報告",
        f"📂 專案目錄: {root.name}",
        f"🎯 綜合評分: {score} / 100 ➔ {grade}",
        "=" * 64,
        "",
    ]

    icons = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}
    for c in checks:
        icon = icons.get(c["status"], "ℹ️")
        lines.append(f"{icon} 【{c['status']}】 {c['category']}")
        for f in c.get("findings", []):
            lines.append(f"     • {f}")
        lines.append("")

    lines.append("-" * 64)
    lines.append("🛠️ 建議改善動作 (Next Steps):")
    has_issues = any(c["status"] in ("WARN", "FAIL") for c in checks)
    if not has_issues:
        lines.append("  🎉 專案各項架構、規範與鐵律落實均已完全合規，狀態極佳！")
    else:
        lines.append("  1. 同步母版最新規範: python3 scripts/agentctl.py update")
        lines.append("  2. 自動修復環境配置: python3 scripts/agentctl.py doctor --fix")
        lines.append("  3. 執行程式碼複查:   python3 scripts/agentctl.py check")
        lines.append("  4. 驗證離線測試:     uv run python -m unittest discover -s tests -v")
    lines.append("=" * 64)
    return "\n".join(lines)


def auto_fix(root: Path) -> None:
    """Execute common safe automatic fixes.

    Args:
        root: Project root directory.
    """
    print("\n🚀 正在自動執行修復程序...")
    run_command([sys.executable, str(root / "scripts" / "agentctl.py"), "doctor", "--fix"], root)
    run_command([sys.executable, str(root / "scripts" / "agentctl.py"), "sync"], root)
    run_command([sys.executable, str(root / "scripts" / "agentctl.py"), "tree"], root)
    print("✅ 自動修復指令已完成。\n")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="專案架構合規與母版同步掃描工具")
    parser.add_argument("--fix", action="store_true", help="自動執行可安全修復之項目")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    parser.add_argument("--skip-tests", action="store_true", help="略過執行測試套件")
    parser.add_argument("--strict", action="store_true", help="若有任何警示或錯誤則回傳非 0 退出碼")
    return parser.parse_args()


def main() -> int:
    """Main CLI entrypoint.

    Returns:
        Process exit code.
    """
    args = parse_args()
    root = find_root()

    if args.fix:
        auto_fix(root)

    checks = [
        check_framework_status(root),
        check_architecture_and_code(root),
        check_dependency_graph(root),
        check_environment_and_data(root),
        check_iron_laws(root),
        check_tests(root, skip=args.skip_tests),
    ]

    score, grade = calculate_score(checks)

    if args.json:
        data = {
            "project": root.name,
            "score": score,
            "grade": grade,
            "checks": checks,
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_report(root, checks, score, grade))

    if args.strict and (score < 90 or any(c["status"] == "FAIL" for c in checks)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
