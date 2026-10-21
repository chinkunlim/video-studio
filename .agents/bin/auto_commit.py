#!/usr/bin/env python3
"""Local git commit tool with agent attribution, changelog entries and secret scanning.

Purpose:
    Lets any AI agent commit its work in one command while keeping a consistent,
    traceable history: who (agent/model) changed what, and for which task.

What one run does:
    1. Refreshes the directory tree (`update_tree.py`).
    2. Collects changed files (optionally limited by `--task` or `--paths`).
    3. Infers a Conventional Commit subject (`feat(services): ...`) unless `-m` is given.
    4. Adds one line under `## [Unreleased]` in `CHANGELOG.md` (skipped for `--bump none`,
       test-only commits and commits that only touch the handoff board / task cards). The version number is NOT bumped here: releasing is a
       separate, deliberate step (`agentctl finish --tag`).
    5. Stages exactly the collected files, scans the staged diff for secrets, and commits
       with trailers: `Agent:`, `Model:`, `Task:`, `Version:` (current base), `Co-Authored-By:`.
    If staging, scanning or committing fails, every file this tool edited is restored.

Usage:
    python3 scripts/agentctl.py commit --agent claude-code --model claude-opus-5-5
    python3 scripts/agentctl.py commit --task TASK-001 -m "fix(api): handle timeout"
    python3 scripts/agentctl.py commit --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import (  # noqa: E402
    SECRET_PATTERNS,
    add_unreleased_entry,
    detect_layer,
    git_changed_files,
    load_config,
    read_version,
    resolve_agent_identity,
)

CHANGELOG_FILE = ROOT / "CHANGELOG.md"
GENERATED_FILES = ("AGENTS.md", "docs/architecture/PROJECT_TREE.md")
ALWAYS_IN_SCOPE = (".agents/handoff/", ".agents/tasks/", "CHANGELOG.md", *GENERATED_FILES)
SECTION_MAP = {"feat": "Added", "fix": "Fixed", "docs": "Documentation", "refactor": "Changed", "test": "Testing", "chore": "Chore"}
DEPENDENCY_FILES = ("pyproject.toml", "uv.lock", "requirements.txt", "package.json", "package-lock.json", ".python-version", "Cargo.toml", "go.mod")


@dataclass
class CommitPlan:
    """Everything decided before touching git, shared between the helper steps."""

    agent: str
    model: str
    task: str
    commit_type: str
    scope: str
    summary: str
    bullets: list[str]
    bump: str
    version: str
    changes: list[tuple[str, str]] = field(default_factory=list)


class FileSnapshot:
    """Remember original file contents so failed commits can be rolled back."""

    def __init__(self) -> None:
        """Start with no saved files."""
        self._saved: dict[Path, bytes | None] = {}

    def save(self, path: Path) -> None:
        """Record the current content of `path` (once) before it is modified.

        Args:
            path: File that is about to be written or created.
        """
        if path not in self._saved:
            self._saved[path] = path.read_bytes() if path.exists() else None

    def restore(self) -> None:
        """Put every recorded file back to its original content (deleting new files)."""
        for path, content in self._saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)


def run_git(args: list[str], check: bool = True) -> str:
    """Run a git command in the project root.

    Args:
        args: Arguments after `git`.
        check: Raise `CalledProcessError` on a non-zero exit code.

    Returns:
        Standard output with trailing whitespace removed (leading spaces are kept).
    """
    res = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=check)
    return res.stdout.rstrip()


def has_head() -> bool:
    """Tell whether the repository already has at least one commit.

    Returns:
        True when `HEAD` resolves to a commit.
    """
    return subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=ROOT, capture_output=True).returncode == 0


def ensure_git_repo() -> None:
    """Initialise a git repository with a `main` branch when none exists."""
    if not (ROOT / ".git").exists():
        run_git(["init", "-b", "main"])


def in_scope(rel_path: str, prefixes: list[str]) -> bool:
    """Check whether a changed file belongs to the requested scope.

    Args:
        rel_path: Repo-relative POSIX path.
        prefixes: Allowed path prefixes; framework bookkeeping files are always allowed.

    Returns:
        True when the file should be committed.
    """
    if any(rel_path == a or rel_path.startswith(a) for a in ALWAYS_IN_SCOPE):
        return True
    norm = rel_path.strip("/")
    return any(norm == p.strip("/") or norm.startswith(p.strip("/") + "/") for p in prefixes)


def resolve_task_scopes(task_id: str) -> list[str]:
    """Read the `paths` of a task card.

    Args:
        task_id: Task ID such as `TASK-001`.

    Returns:
        The task's paths, or an empty list when the task does not exist.
    """
    tasks_dir = ROOT / ".agents" / "tasks"
    for f in sorted(tasks_dir.glob("TASK-*.json")) if tasks_dir.exists() else []:
        if f.name.upper().startswith(task_id.upper() + "-") or f.name.upper() == f"{task_id.upper()}.JSON":
            return list(json.loads(f.read_text(encoding="utf-8")).get("paths", []))
    return []


def collect_changes(prefixes: list[str]) -> list[tuple[str, str]]:
    """List changed files, limited to `prefixes` when any are given.

    Args:
        prefixes: Path prefixes from `--paths` / `--task`; empty means every change.

    Returns:
        List of `(status, path)` pairs.
    """
    changes = git_changed_files(ROOT)
    return [c for c in changes if in_scope(c[1], prefixes)] if prefixes else changes


def scan_secrets_in_diff(diff_text: str) -> list[str]:
    """Find likely credentials on added lines of a unified diff.

    Args:
        diff_text: Output of `git diff`.

    Returns:
        Human-readable findings (the matched line is truncated).
    """
    findings: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, line):
                findings.append(f"疑似 {label}: {line[:60]}...")
                break
    return findings


def _classify(paths: list[str], config: dict) -> tuple[list[str], set[str]]:
    """Map changed paths to commit scopes and broad categories.

    Args:
        paths: Changed repo-relative paths.
        config: Loaded project configuration.

    Returns:
        Tuple of scope names (in order) and categories from {src, test, docs, tooling}.
    """
    rules = (
        (lambda p: p.startswith("docs/adr"), "adr", "docs"),
        (lambda p: p.startswith("docs/known-issues"), "issues", "docs"),
        (lambda p: p.startswith("docs/"), "docs", "docs"),
        (lambda p: p.startswith(("test/", "tests/")), "test", "test"),
        (lambda p: p.startswith(".agents/skills"), "skills", "tooling"),
        (lambda p: p in DEPENDENCY_FILES, "deps", "tooling"),
        (lambda p: p.startswith(("scripts/", "dev/", ".agents/")), "tooling", "tooling"),
    )
    scopes: list[str] = []
    kinds: set[str] = set()
    for p in paths:
        layer = detect_layer(p, config)
        if layer:
            scopes.append(layer)
            kinds.add("src")
            continue
        for matcher, scope, kind in rules:
            if matcher(p):
                scopes.append(scope)
                kinds.add(kind)
                break
    return list(dict.fromkeys(scopes)), kinds


def infer_commit_metadata(changes: list[tuple[str, str]], diff_text: str, config: dict) -> tuple[str, str, str, list[str], str]:
    """Infer a Conventional Commit type, scope, subject, body bullets and version bump.

    Args:
        changes: `(status, path)` pairs that will be committed.
        diff_text: Diff of those changes (used to spot fixes and ADR/ISSUE/TASK references).
        config: Loaded project configuration.

    Returns:
        Tuple `(commit_type, scope, summary, bullets, bump)`.
    """
    paths = [p for _, p in changes]
    added = [p for st, p in changes if "A" in st or "?" in st]
    meaningful = [p for p in paths if p not in ("CHANGELOG.md", *GENERATED_FILES) and not p.startswith(".agents/")]
    scopes, kinds = _classify(meaningful or paths, config)
    scope = scopes[0] if len(scopes) == 1 else ("/".join(scopes[:2]) if scopes else "project")
    refs = sorted(set(re.findall(r"\b(?:ADR|ISSUE|TASK)-\d{3}\b", diff_text + " " + " ".join(paths))))

    if "src" in kinds:
        if any(detect_layer(p, config) for p in added):
            commit_type, bump, action = "feat", "minor", f"add {scope} module"
        elif re.search(r"\b(fix|bug|error)\b|修復|修正", diff_text, re.I):
            commit_type, bump, action = "fix", "patch", f"fix {scope} logic"
        else:
            commit_type, bump, action = "feat", "patch", f"update {scope}"
    elif kinds == {"test"}:
        commit_type, bump, action = "test", "none", "update automated tests"
    elif "docs" in kinds and "tooling" not in kinds:
        commit_type, bump, action = "docs", "patch", f"update {scope} documentation"
    else:
        commit_type, bump, action = "chore", "patch", f"update {scope} tooling and config"
    if not meaningful:  # only handoff board / task cards / generated files: not a release note
        bump = "none"

    summary = f"{commit_type}({scope}): {action}" + (f" ({', '.join(refs)})" if refs else "")
    bullets = []
    for st, p in changes[:10]:
        if p in ("CHANGELOG.md", *GENERATED_FILES):
            continue
        label = "add" if ("A" in st or "?" in st) else ("delete" if "D" in st else "update")
        bullets.append(f"{label} `{p}`")
    if refs:
        bullets.append(f"refs: {', '.join(refs)}")
    return commit_type, scope, summary, bullets, bump


def update_changelog(plan: CommitPlan, snapshot: FileSnapshot) -> list[str]:
    """Add this commit as one line under `## [Unreleased]` in `CHANGELOG.md`.

    Args:
        plan: The commit plan (uses `bump`, `commit_type`, `summary`, `task`, `agent`).
        snapshot: Records the original changelog for rollback.

    Returns:
        `["CHANGELOG.md"]` when the file was updated, otherwise an empty list.
    """
    if plan.bump == "none" or not CHANGELOG_FILE.exists():
        return []
    snapshot.save(CHANGELOG_FILE)
    meta = ([f"`{plan.task}`"] if plan.task else []) + [f"by `@{plan.agent}`"]
    subject = re.sub(r"\s*\[agent:[^\]]+\]", "", plan.summary)
    line = f"{subject} ({', '.join(meta)})"
    section = SECTION_MAP.get(plan.commit_type, "Changed")
    CHANGELOG_FILE.write_text(add_unreleased_entry(CHANGELOG_FILE.read_text(encoding="utf-8"), section, line), encoding="utf-8")
    return ["CHANGELOG.md"]


def build_commit_message(plan: CommitPlan) -> str:
    """Compose the full commit message with body bullets and trailers.

    Args:
        plan: The commit plan.

    Returns:
        Commit message text.
    """
    agent_tag = f"[agent:{plan.agent}]"
    subject = plan.summary if agent_tag in plan.summary else f"{plan.summary} {agent_tag}"
    trailers = [f"Agent: {plan.agent}"]
    trailers += [f"Model: {plan.model}"] if plan.model else []
    trailers += [f"Task: {plan.task}"] if plan.task else []
    trailers.append(f"Version: v{plan.version}")
    safe_agent = re.sub(r"[^a-zA-Z0-9_.-]", "-", plan.agent)
    trailers.append(f"Co-Authored-By: {plan.agent} <agent+{safe_agent}@local>")
    body = "\n".join(f"- {b}" for b in plan.bullets)
    return "\n\n".join(part for part in (subject, body, "\n".join(trailers)) if part)


def unstage(paths: list[str]) -> None:
    """Remove paths from the index without touching the working tree.

    Args:
        paths: Repo-relative paths to unstage.
    """
    if has_head():
        run_git(["reset", "-q", "--", *paths], check=False)
    else:
        run_git(["rm", "-q", "-r", "--cached", "--ignore-unmatch", "--", *paths], check=False)


def stage_scan_commit(plan: CommitPlan, to_stage: list[str], snapshot: FileSnapshot) -> int:
    """Stage files, block on secrets, and create the commit (rolling back on failure).

    Args:
        plan: The commit plan.
        to_stage: Repo-relative paths to stage.
        snapshot: Files to restore if anything fails.

    Returns:
        Process exit code (0 when the commit was created).
    """
    staged = sorted(set(to_stage))
    add = subprocess.run(["git", "add", "-A", "--", *staged], cwd=ROOT, text=True, capture_output=True)
    if add.returncode == 0:
        hits = scan_secrets_in_diff(run_git(["diff", "--cached", "--", *staged], check=False))
        if hits:
            print("🚨 [SECURITY BLOCK] 偵測到疑似敏感金鑰，已中止 Commit：\n  - " + "\n  - ".join(hits), file=sys.stderr)
            add = subprocess.CompletedProcess(args=[], returncode=1, stderr="")
    result = add if add.returncode != 0 else subprocess.run(
        ["git", "commit", "-m", build_commit_message(plan)], cwd=ROOT, text=True, capture_output=True
    )
    if result.returncode != 0:
        unstage(staged)
        snapshot.restore()
        print(f"❌ Commit 未完成，已還原本工具修改的檔案。\n{(result.stderr or '') + (getattr(result, 'stdout', '') or '')}", file=sys.stderr)
        return 1
    print(f"✅ 已完成本機 Git Commit: [{run_git(['rev-parse', '--short', 'HEAD'])}] {plan.summary}")
    return 0


CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def warn_if_not_english(message: str) -> None:
    """Remind the agent that commit messages must be written in English.

    Args:
        message: Commit subject given with `-m`.
    """
    if CJK_RE.search(message):
        print("⚠️ Commit 訊息請使用英文（例如 `feat(services): add pricing module`）；文件內容可以用中文。", file=sys.stderr)


def push_with_permission() -> None:
    """Push to the remote; `ALLOW_PUSH=1` lets the version-controlled pre-push hook through.

    Only called with `--push`, which agents may use only after the user explicitly agreed.
    """
    subprocess.run(["git", "push"], cwd=ROOT, check=True, env={**os.environ, "ALLOW_PUSH": "1"})


def get_unpushed_commits() -> tuple[list[str], bool]:
    """List commits that are not on the upstream branch yet.

    Returns:
        Tuple of one-line commit descriptions and whether an upstream branch exists.
    """
    upstream = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
    rev_range = [f"{upstream}..HEAD"] if upstream else []
    log_out = run_git(["log", *rev_range, "--oneline"], check=False)
    return [line.strip() for line in log_out.splitlines() if line.strip()], bool(upstream)


def print_push_reminder(version: str, closeout: bool, threshold: int) -> None:
    """Print the closeout report or a push reminder when many commits are unpushed.

    Args:
        version: Version to display.
        closeout: Print the full end-of-session report.
        threshold: Number of unpushed commits that triggers a reminder.
    """
    unpushed, has_upstream = get_unpushed_commits()
    remote = run_git(["remote", "get-url", "origin"], check=False)
    if closeout:
        print("\n" + "=" * 64 + "\n🏁 【結束對話收尾報告 (Session Closeout Report)】\n" + "=" * 64)
        print(f"📌 目前版本       : v{version}")
        print(f"🌐 遠端儲存庫     : {remote or '尚未設定 (git remote add origin <URL>)'}")
        print(f"📦 未推送 Commit  : 共 {len(unpushed)} 個" + ("" if has_upstream else " (尚未綁定遠端分支)"))
        for c in unpushed[:10]:
            print(f"   • {c}")
        if unpushed:
            print(f"💡 [AI AGENT 行動指令] 請詢問使用者：目前累積 {len(unpushed)} 個未推送 Commit，是否要推送到 GitHub？")
        print("=" * 64)
        return
    if len(unpushed) >= threshold:
        print(f"\n💡 [GITHUB PUSH REMINDER] 本機已累積 {len(unpushed)} 個未推送 Commit (閾值: {threshold})，請詢問使用者是否要 `git push`。")


def build_plan(args: argparse.Namespace, config: dict, changes: list[tuple[str, str]]) -> CommitPlan:
    """Turn CLI arguments and the detected changes into a `CommitPlan`.

    Args:
        args: Parsed command-line arguments.
        config: Loaded project configuration.
        changes: `(status, path)` pairs to commit.

    Returns:
        A fully populated commit plan.
    """
    agent, model = resolve_agent_identity(args.agent, args.model, root=ROOT, task_id=args.task)
    diff_text = run_git(["diff", "HEAD"], check=False) if has_head() else ""
    commit_type, scope, auto_summary, bullets, bump = infer_commit_metadata(changes, diff_text, config)
    summary = args.message.strip() if args.message else auto_summary
    if args.message:
        warn_if_not_english(summary)
    typed = re.match(r"^(\w+)(?:\(([^)]+)\))?:", summary)
    if args.commit_type:
        commit_type = args.commit_type.strip()
        bump = "minor" if commit_type == "feat" and bump == "patch" else bump
    elif args.message and typed:
        commit_type = typed.group(1)
    task = args.task.upper()
    if task and task not in summary:
        summary = f"{summary} ({task})"
    bump = bump if args.bump == "auto" else args.bump
    return CommitPlan(agent, model, task, commit_type, scope, summary, bullets, bump, read_version(ROOT, config), changes)


def refresh_generated_docs() -> None:
    """Regenerate the directory tree before committing."""
    for script_name in ("update_tree.py",):
        s_path = ROOT / ".agents" / "bin" / script_name
        if s_path.exists():
            subprocess.run([sys.executable, str(s_path)], cwd=ROOT, check=False, capture_output=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Agent 署名、版本管理與秘密掃描的本機 Git Commit 工具")
    parser.add_argument("-m", "--message", help="自訂 Commit 標題 (建議 Conventional Commit 格式)")
    parser.add_argument("--type", dest="commit_type", default="", help="強制指定類型 (feat/fix/docs/refactor/test/chore)")
    parser.add_argument("--agent", default="", help="AI Agent 名稱 (如 claude-code / cursor)")
    parser.add_argument("--model", default="", help="AI 模型名稱 (如 claude-opus-5-5)")
    parser.add_argument("--bump", choices=["auto", "patch", "minor", "major", "none"], default="auto",
                        help="none = 不寫 CHANGELOG（交接、純文件）；版本號只在 finish --tag 時升級")
    parser.add_argument("--paths", nargs="+", default=[], help="只提交這些路徑")
    parser.add_argument("--task", default="", help="綁定任務編號 (如 TASK-001)，只提交該任務 paths 內的檔案")
    parser.add_argument("--dry-run", action="store_true", help="只預覽，不修改任何檔案")
    parser.add_argument("--closeout", action="store_true", help="輸出結束對話收尾報告")
    parser.add_argument("--push", action="store_true", help="Commit 後推送至遠端（只有使用者明確同意時才可使用）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the full commit pipeline.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    args = parse_args(argv)
    ensure_git_repo()
    config = load_config(ROOT)
    threshold = int(config["git"].get("push_reminder_threshold", 5))
    prefixes = list(args.paths) + (resolve_task_scopes(args.task) if args.task else [])
    if not args.dry_run:
        refresh_generated_docs()
    changes = collect_changes(prefixes)
    if not changes:
        print("ℹ️ 指定範圍內沒有未提交的變更。")
        if args.closeout:
            print_push_reminder(read_version(ROOT, config), True, threshold)
        return 0

    plan = build_plan(args, config, changes)
    print("=" * 64)
    print(f"🤖 執行 Agent : {plan.agent}" + (f" ({plan.model})" if plan.model else ""))
    print(f"📦 目前版本  : v{plan.version}（CHANGELOG: {'略過' if plan.bump == 'none' else 'Unreleased'}）")
    print(f"📝 Commit 標題: {plan.summary}")
    print(f"📂 提交檔案  : {len(changes)} 個")
    print("=" * 64)
    if args.dry_run:
        return 0

    snapshot = FileSnapshot()
    extra = update_changelog(plan, snapshot)
    rc = stage_scan_commit(plan, [p for _, p in changes] + extra, snapshot)
    if rc != 0:
        return rc
    if args.push:
        push_with_permission()
        print("🚀 已推送至遠端儲存庫 (git push)。")
    else:
        print_push_reminder(plan.version, args.closeout, threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
