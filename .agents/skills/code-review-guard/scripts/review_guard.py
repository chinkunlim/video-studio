#!/usr/bin/env python3
"""Code Review Guard: static checks for comments, layering, secrets and function size.

Purpose:
    One command that tells an agent whether its code is ready to commit. It is run
    manually, by `closeout`, and by the git pre-commit hook (`--quiet`).

Checks (thresholds come from `.agents/project.toml`):
    - Comments (`[quality] require_docstrings`, CRITICAL):
        * Python: module docstring; docstring on every function/class; every parameter
          listed in the docstring (`Args:` section, `name: description`).
        * JS/TS: a header comment at the top of the file; a JSDoc block above every
          function with one `@param` per parameter.
        * Go / Rust: header comment at the top; `//` (Go) or `///` (Rust) doc comment above every function.
        * HTML: a `<!-- ... -->` comment right after `<!DOCTYPE>`; CSS/SCSS: a `/* ... */` header.
    - Layering: only `[architecture] env_access_layers` may read environment variables.
    - Logging: Python code in a layer outside `[quality] print_allowed_layers` (default
      `entrypoints`) must use a module logger instead of `print`.
    - Secrets: hard-coded API keys / tokens / private keys.
    - Size: function length, parameter count and nesting depth; file length (`max_file_lines`
      warning, `hard_max_file_lines` CRITICAL — split big files into sub-modules).
    - Project rules: `[project_rules] paired_calls` must appear together; modules listed in
      `[project_rules] forbidden_imports` (e.g. `"flask:改用 FastAPI"`) must not be imported.
    - Diff hygiene (warning): the uncommitted diff deletes many existing comment lines.
    Test files (`test_*.py`, `*_test.go`, `*.test.js`, files under `tests/`) skip the comment rules.

Legacy migration (`--allow-legacy-moves`, passed by the pre-commit hook only):
    A file staged as an unchanged move out of `legacy/` (git rename R100) may be committed
    once without docs, so git always records the rename and `git log --follow` keeps the old
    history. Its [Docs] / [Size] / [Layer] / [Logging] findings become warnings for that commit only;
    secrets and forbidden imports still block. `agentctl check`, `migration --verify` and the
    next commit report them as CRITICAL again, so the file must be fixed right away.

Usage:
    python3 .agents/skills/code-review-guard/scripts/review_guard.py [project_root] [--json] [--quiet] [--allow-legacy-moves]
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

FALLBACK_SECRET_PATTERNS = [
    (r"AIza[0-9A-Za-z_-]{20,}", "Google / Gemini API Key"),
    (r"gh[opsu]_[0-9A-Za-z]{20,}", "GitHub Token"),
    (r"sk-[0-9A-Za-z_-]{20,}", "Secret Key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY", "Private Key"),
]
JS_FUNC = r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z0-9_$]+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
JS_ARROW = (
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*(?::[^=]+)?=\s*(?:async\s+)?"
    r"(?:function\s*\*?\s*\(([^)]*)\)|\(([^)]*)\)\s*(?::\s*[^=]+)?=>)"
)
BRACE_LANG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    **{ext: [re.compile(JS_FUNC), re.compile(JS_ARROW)] for ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")},
    ".go": [re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z0-9_]+)\s*\(([^)]*)\)")],
    ".rs": [re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")],
}
JS_EXTS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")
MARKUP_HEADERS = {".html": "<!--", ".htm": "<!--", ".css": "/*", ".scss": "/*"}
TEST_FILE_RE = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$)")
SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target"}
DEFAULT_CONFIG = {
    "architecture": {"source_roots": ["src"], "layers": [], "env_access_layers": ["config"]},
    "quality": {"max_function_lines": 30, "hard_max_function_lines": 50, "max_params": 4, "max_nesting": 3,
                "block_on_critical": True, "require_docstrings": True},
    "project_rules": {"paired_calls": []},
}


def _issue(severity: str, rel: str, line: int, msg: str) -> dict:
    """Build one finding.

    Args:
        severity: `CRITICAL` (blocks) or `IMPORTANT` (warning).
        rel: Repo-relative file path.
        line: 1-based line number.
        msg: Human-readable message.

    Returns:
        Finding dictionary.
    """
    return {"severity": severity, "file": rel, "line": line, "msg": msg}


def _load_project_cfg(root: Path) -> tuple[dict, object]:
    """Load the project configuration through `.agents/lib/project_config.py`.

    Args:
        root: Project root directory.

    Returns:
        Tuple of configuration dict and the `project_config` module (None when unavailable).
    """
    for lib_dir in (root / ".agents" / "lib", Path(__file__).resolve().parents[3] / "lib"):
        if (lib_dir / "project_config.py").exists():
            sys.path.insert(0, str(lib_dir))
            import project_config  # type: ignore

            return project_config.load_config(root), project_config
    return DEFAULT_CONFIG, None


def is_test_file(rel: str) -> bool:
    """Tell whether a file is a test file (comment rules are relaxed for tests).

    Args:
        rel: Repo-relative POSIX path.

    Returns:
        True for test files or files inside `test/`, `tests/`, `__tests__/`.
    """
    parts = rel.split("/")
    return bool(TEST_FILE_RE.search(parts[-1])) or any(p in ("test", "tests", "__tests__") for p in parts[:-1])


def max_indent_depth(lines: list[str]) -> int:
    """Measure the deepest indentation level inside a function body (4 spaces per level).

    Args:
        lines: Source lines of the function, first line is the signature.

    Returns:
        Maximum nesting depth relative to the signature.
    """
    if not lines:
        return 0
    base = len(lines[0]) - len(lines[0].lstrip(" "))
    depth = 0
    for line in lines:
        if line.strip() and not line.strip().startswith(("#", "//")):
            depth = max(depth, max(0, len(line) - len(line.lstrip(" ")) - base) // 4)
    return depth


def check_fn_metrics(rel: str, name: str, lineno: int, sizes: tuple[int, int, int], quality: dict) -> list[dict]:
    """Compare one function's size metrics with the configured thresholds.

    Args:
        rel: Repo-relative file path.
        name: Function name.
        lineno: Line where the function starts.
        sizes: Tuple of (length in lines, parameter count, nesting depth).
        quality: `[quality]` section of the configuration.

    Returns:
        Findings for this function.
    """
    length, arg_count, depth = sizes
    issues = []
    if length > int(quality.get("hard_max_function_lines", 50)):
        issues.append(_issue("CRITICAL", rel, lineno, f"[Size] 函式 `{name}` 長 {length} 行，超過硬上限，請拆分。"))
    elif length > int(quality.get("max_function_lines", 30)):
        issues.append(_issue("IMPORTANT", rel, lineno, f"[Size] 函式 `{name}` 長 {length} 行，建議拆分。"))
    if arg_count > int(quality.get("max_params", 4)):
        issues.append(_issue("IMPORTANT", rel, lineno, f"[Params] 函式 `{name}` 有 {arg_count} 個參數，建議改用資料物件。"))
    if depth > int(quality.get("max_nesting", 3)) + 1:
        issues.append(_issue("IMPORTANT", rel, lineno, f"[Nesting] 函式 `{name}` 巢狀 {depth} 層，建議改用 early return。"))
    return issues


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def _python_params(node: ast.AST) -> list[str]:
    """List the parameter names of a Python function that must be documented.

    Args:
        node: `FunctionDef` or `AsyncFunctionDef` node.

    Returns:
        Parameter names without `self` / `cls` (including `*args` / `**kwargs` names).
    """
    args = node.args  # type: ignore[attr-defined]
    names = [a.arg for a in [*getattr(args, "posonlyargs", []), *args.args, *args.kwonlyargs]]
    names += [a.arg for a in (args.vararg, args.kwarg) if a is not None]
    return [n for n in names if n not in ("self", "cls")]


def _param_documented(doc: str, name: str) -> bool:
    """Check whether a docstring documents a parameter (`name:`, `name (type):` or Sphinx `:param name:`).

    Args:
        doc: The docstring text.
        name: Parameter name.

    Returns:
        True when a line starts with the parameter name followed by `:` or `(`, or with `:param name:`
        (the form Open WebUI tools need).
    """
    google = re.search(rf"^\s*\**{re.escape(name)}\s*(\([^)]*\))?\s*:", doc, flags=re.M)
    sphinx = re.search(rf"^\s*:param\s+(\w+\s+)?{re.escape(name)}\s*:", doc, flags=re.M)
    return google is not None or sphinx is not None


def python_docstring_issues(tree: ast.Module, rel: str) -> list[dict]:
    """Find missing module/function/class docstrings and undocumented parameters.

    Args:
        tree: Parsed module.
        rel: Repo-relative file path.

    Returns:
        CRITICAL findings for every missing piece of documentation.
    """
    issues = []
    if tree.body and not ast.get_docstring(tree):
        issues.append(_issue("CRITICAL", rel, 1, "[Docs] 檔案開頭缺少模組說明 (module docstring)。"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = ast.get_docstring(node) or ""
        kind = "類別" if isinstance(node, ast.ClassDef) else "函式"
        if not doc.strip():
            issues.append(_issue("CRITICAL", rel, node.lineno, f"[Docs] {kind} `{node.name}` 缺少功能說明 docstring。"))
            continue
        if isinstance(node, ast.ClassDef):
            continue
        missing = [p for p in _python_params(node) if not _param_documented(doc, p)]
        if missing:
            issues.append(_issue("CRITICAL", rel, node.lineno, f"[Docs] 函式 `{node.name}` 的 docstring 未說明參數：{', '.join(missing)}（請加 Args: 區塊）。"))
    return issues


def forbidden_import_issues(tree: ast.Module, rel: str, config: dict) -> list[dict]:
    """Report imports of modules the project has banned.

    Entries of `[project_rules] forbidden_imports` are `module` or `module:hint`,
    e.g. `"flask:新專案一律使用 FastAPI"`.

    Args:
        tree: Parsed module.
        rel: Repo-relative file path.
        config: Loaded project configuration.

    Returns:
        One CRITICAL finding per forbidden import.
    """
    rules = {}
    for entry in config.get("project_rules", {}).get("forbidden_imports", []):
        name, _, hint = str(entry).partition(":")
        rules[name.strip()] = hint.strip()
    if not rules:
        return []
    issues = []
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in rules:
                hint = f"（{rules[top]}）" if rules[top] else ""
                issues.append(_issue("CRITICAL", rel, node.lineno, f"[Project Rule] 此專案禁止使用 `{top}`{hint}。"))
    return issues


def audit_python_file(text: str, rel: str, layer: str | None, config: dict) -> list[dict]:
    """Run every Python check on one file.

    Args:
        text: File content.
        rel: Repo-relative file path.
        layer: Architectural layer of the file (None when outside layers).
        config: Loaded project configuration.

    Returns:
        Findings for this file.
    """
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [_issue("CRITICAL", rel, exc.lineno or 1, f"語法錯誤: {exc.msg}")]
    lines = text.splitlines()
    env_layers = set(config["architecture"].get("env_access_layers", ["config"]))
    print_layers = set(config["quality"].get("print_allowed_layers", ["entrypoints"]))
    issues: list[dict] = []
    if config["quality"].get("require_docstrings", True) and not is_test_file(rel):
        issues += python_docstring_issues(tree, rel)
    issues += forbidden_import_issues(tree, rel, config)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            sizes = (end - node.lineno + 1, len(_python_params(node)), max_indent_depth(lines[node.lineno - 1 : end]))
            issues += check_fn_metrics(rel, node.name, node.lineno, sizes, config["quality"])
        if layer and layer not in env_layers and isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            issues.append(_issue("CRITICAL", rel, node.lineno, f"[Layer] `{layer}` 層不可直接讀取環境變數（只允許 {sorted(env_layers)}）。"))
        if layer and layer not in print_layers and isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            issues.append(_issue("CRITICAL", rel, node.lineno,
                                 f"[Logging] `{layer}` 層不可用 print，請用 `logger = logging.getLogger(__name__)` 記 log（只有 {sorted(print_layers)} 可 print）。"))
    return issues


# ---------------------------------------------------------------------------
# Brace languages (JS / TS / Go / Rust)
# ---------------------------------------------------------------------------


def split_params(raw: str) -> list[str]:
    """Split a parameter list on top-level commas (ignores commas inside `<>`, `{}`, `[]`, `()`).

    Args:
        raw: Text between the function's parentheses.

    Returns:
        Non-empty parameter strings (receivers like `self` / `&self` removed).
    """
    parts, depth, buf = [], 0, ""
    for ch in raw:
        if ch in "<{[(":
            depth += 1
        elif ch in ">}])":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    parts.append(buf.strip())
    return [p for p in parts if p and p not in ("self", "&self", "&mut self", "mut self")]


def has_file_header(lines: list[str]) -> bool:
    """Check that a file starts with a comment (after a shebang / `"use strict"`).

    Args:
        lines: File lines.

    Returns:
        True when the first meaningful line is a comment.
    """
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#!") or s.strip(";'\"") == "use strict":
            continue
        return s.startswith(("/*", "//"))
    return True


def preceding_doc(lines: list[str], idx: int) -> str:
    """Return the comment block directly above line `idx` (attributes/decorators skipped).

    Args:
        lines: File lines.
        idx: 0-based index of the function signature.

    Returns:
        The comment text, or an empty string when there is none.
    """
    j = idx - 1
    while j >= 0 and (lines[j].strip().startswith(("#[", "@")) or not lines[j].strip()):
        j -= 1
    if j < 0:
        return ""
    if lines[j].strip().endswith("*/"):
        start = j
        while start >= 0 and "/*" not in lines[start]:
            start -= 1
        return "\n".join(lines[max(start, 0) : j + 1])
    block = []
    while j >= 0 and lines[j].strip().startswith("//"):
        block.insert(0, lines[j])
        j -= 1
    return "\n".join(block)


def brace_doc_issue(lines: list[str], idx: int, name: str, params: list[str], ctx: tuple[str, str]) -> dict | None:
    """Check the doc comment above one JS/TS/Go/Rust function.

    Args:
        lines: File lines.
        idx: 0-based index of the function signature.
        name: Function name.
        params: Parameter strings from `split_params()`.
        ctx: Tuple of (repo-relative path, file suffix).

    Returns:
        A CRITICAL finding, or None when the function is documented.
    """
    rel, suffix = ctx
    doc = preceding_doc(lines, idx)
    if suffix in JS_EXTS:
        if "/**" not in doc:
            return _issue("CRITICAL", rel, idx + 1, f"[Docs] 函式 `{name}` 上方缺少 JSDoc (/** ... */) 功能說明。")
        if doc.count("@param") < len(params):
            return _issue("CRITICAL", rel, idx + 1, f"[Docs] 函式 `{name}` 有 {len(params)} 個參數，但 JSDoc 只有 {doc.count('@param')} 個 @param。")
        return None
    marker = "///" if suffix == ".rs" else "//"
    if not any(ln.strip().startswith(marker) for ln in doc.splitlines()):
        return _issue("CRITICAL", rel, idx + 1, f"[Docs] 函式 `{name}` 上方缺少 `{marker}` 說明註解。")
    return None


def _function_end(lines: list[str], idx: int) -> int:
    """Find the line where a brace-delimited function body ends.

    Args:
        lines: File lines.
        idx: 0-based index of the function signature.

    Returns:
        0-based index of the closing line (the signature line for one-liners).
    """
    depth, started = 0, False
    for j in range(idx, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        started = started or "{" in lines[j]
        if started and depth <= 0:
            return j
    return idx


def markup_header_issues(text: str, rel: str, config: dict) -> list[dict]:
    """Require a header comment at the top of HTML and CSS files.

    HTML may start with `<!DOCTYPE html>`; the first element after it must be a comment.

    Args:
        text: File content.
        rel: Repo-relative file path.
        config: Loaded project configuration.

    Returns:
        A CRITICAL finding when the header comment is missing, else nothing.
    """
    marker = MARKUP_HEADERS.get(Path(rel).suffix.lower())
    if not marker or not config["quality"].get("require_docstrings", True) or is_test_file(rel):
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("<!doctype"):
        lines = lines[1:]
    if not lines or lines[0].startswith(marker):
        return []
    return [_issue("CRITICAL", rel, 1, f"[Docs] 檔案開頭缺少用途說明註解（{marker} ... ）。")]


def audit_brace_file(text: str, rel: str, layer: str | None, config: dict) -> list[dict]:
    """Run comment, layering and size checks on a JS/TS/Go/Rust file.

    Args:
        text: File content.
        rel: Repo-relative file path.
        layer: Architectural layer of the file (None when outside layers).
        config: Loaded project configuration.

    Returns:
        Findings for this file.
    """
    suffix = Path(rel).suffix
    lines = text.splitlines()
    env_layers = set(config["architecture"].get("env_access_layers", ["config"]))
    check_docs = config["quality"].get("require_docstrings", True) and not is_test_file(rel)
    issues = []
    if check_docs and not has_file_header(lines):
        issues.append(_issue("CRITICAL", rel, 1, "[Docs] 檔案開頭缺少用途說明註解。"))
    for idx, line in enumerate(lines):
        if layer and layer not in env_layers and ("process.env" in line or "os.Getenv(" in line or "env::var(" in line):
            issues.append(_issue("CRITICAL", rel, idx + 1, f"[Layer] `{layer}` 層不可直接讀取環境變數（只允許 {sorted(env_layers)}）。"))
        match = next((m for m in (p.match(line) for p in BRACE_LANG_PATTERNS.get(suffix, [])) if m), None)
        if not match:
            continue
        name = match.group(1)
        params = split_params(next((g for g in match.groups()[1:] if g is not None), ""))
        doc_issue = brace_doc_issue(lines, idx, name, params, (rel, suffix)) if check_docs else None
        issues += [doc_issue] if doc_issue else []
        end = _function_end(lines, idx)
        sizes = (end - idx + 1, len(params), max_indent_depth(lines[idx : end + 1]))
        issues += check_fn_metrics(rel, name, idx + 1, sizes, config["quality"])
    return issues


# ---------------------------------------------------------------------------
# Whole-project checks
# ---------------------------------------------------------------------------


def file_size_issues(text: str, rel: str, quality: dict) -> list[dict]:
    """Flag source files that grew too large (the "God file" problem).

    Args:
        text: File content.
        rel: Repo-relative file path.
        quality: `[quality]` section of the configuration.

    Returns:
        One finding when the file exceeds the soft or hard line limit.
    """
    lines = text.count("\n") + 1
    hard, soft = int(quality.get("hard_max_file_lines", 800)), int(quality.get("max_file_lines", 500))
    if lines > hard:
        return [_issue("CRITICAL", rel, 1, f"[Size] 檔案長 {lines} 行，超過上限 {hard} 行：依職責拆成子模組。")]
    if lines > soft:
        return [_issue("IMPORTANT", rel, 1, f"[Size] 檔案長 {lines} 行（建議 ≤ {soft} 行），考慮拆分。")]
    return []


def secret_issues(text: str, rel: str, patterns: list[tuple[str, str]]) -> list[dict]:
    """Find hard-coded secrets in one file.

    Args:
        text: File content.
        rel: Repo-relative file path.
        patterns: `(regex, label)` pairs.

    Returns:
        CRITICAL findings, one per matching line.
    """
    issues = []
    for idx, line in enumerate(text.splitlines(), start=1):
        label = next((lbl for pat, lbl in patterns if re.search(pat, line)), None)
        if label:
            issues.append(_issue("CRITICAL", rel, idx, f"[Security] 疑似硬編碼 {label}，請改放 .env。"))
    return issues


def paired_call_issues(all_text: str, config: dict) -> list[dict]:
    """Check `[project_rules] paired_calls` (e.g. acquire without release).

    Args:
        all_text: Concatenated text of every scanned file.
        config: Loaded project configuration.

    Returns:
        CRITICAL findings for unpaired calls.
    """
    issues = []
    for pair in config.get("project_rules", {}).get("paired_calls", []):
        if isinstance(pair, str) and ":" in pair:
            pair = pair.split(":", 1)
        if isinstance(pair, list) and len(pair) == 2 and pair[0] in all_text and pair[1] not in all_text:
            issues.append(_issue("CRITICAL", ".agents/project.toml", 1, f"[Project Rule] 有 `{pair[0]}` 但缺少配對的 `{pair[1]}`。"))
    return issues


def removed_comment_issues(root: Path) -> list[dict]:
    """Warn when the uncommitted diff deletes many existing comment lines.

    Args:
        root: Project root directory.

    Returns:
        An IMPORTANT finding when more than 3 comment lines are deleted, else nothing.
    """
    res = subprocess.run(["git", "diff", "HEAD", "--unified=0"], cwd=root, capture_output=True, text=True)
    if res.returncode != 0:
        return []
    removed = sum(
        1 for ln in res.stdout.splitlines()
        if ln.startswith("-") and not ln.startswith("---") and ln[1:].strip().startswith(("#", "//", '"""', "/*", "*"))
    )
    if removed <= 3:
        return []
    return [_issue("IMPORTANT", "(git diff)", 1, f"[Surgical] 本次修改刪除了 {removed} 行既有註解；除非是自己剛寫的，否則不要刪除既有註解。")]


def iter_source_files(root: Path, config: dict, pc_mod: object) -> list[Path]:
    """List the source files to audit.

    Args:
        root: Project root directory.
        config: Loaded project configuration.
        pc_mod: The `project_config` module, or None.

    Returns:
        Sorted files under the configured source roots.
    """
    dirs = pc_mod.source_dirs(root, config) if pc_mod is not None else [d for d in [root / "src"] if d.is_dir()]  # type: ignore[attr-defined]
    files = []
    for src_dir in dirs:
        files += [f for f in sorted(src_dir.rglob("*")) if f.is_file() and not SKIP_DIRS.intersection(f.relative_to(root).parts)]
    return files


DEFERRABLE_TAGS = ("[Docs]", "[Size]", "[Layer]", "[Logging]")


def staged_legacy_moves(root: Path) -> set[str]:
    """List files staged as unchanged moves out of `legacy/` (100% renames).

    Args:
        root: Project root directory (a git repository).

    Returns:
        Repo-relative destination paths; empty outside git or when nothing was moved.
    """
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-M100%", "--diff-filter=R", "-z"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    parts = res.stdout.split("\0")
    moves = set()
    for i in range(0, len(parts) - 2, 3):
        status, old, new = parts[i], parts[i + 1], parts[i + 2]
        if status == "R100" and old.startswith("legacy/"):
            moves.add(new)
    return moves


def defer_legacy_moves(issues: list[dict], moves: set[str]) -> list[dict]:
    """Downgrade comment/size/layer findings of unchanged legacy moves to warnings.

    Args:
        issues: Findings from the audit.
        moves: Paths from `staged_legacy_moves()`.

    Returns:
        Findings with deferrable CRITICAL items of moved files turned into `IMPORTANT`.
    """
    out = []
    for item in issues:
        if item["file"] in moves and item["severity"] == "CRITICAL" and item["msg"].startswith(DEFERRABLE_TAGS):
            item = {**item, "severity": "IMPORTANT", "msg": item["msg"] + "（從 legacy/ 原樣搬入：下一個 commit 必須補齊）"}
        out.append(item)
    return out


def run_review(root: Path, allow_legacy_moves: bool = False) -> tuple[list[dict], bool]:
    """Audit the whole project.

    Args:
        root: Project root directory.
        allow_legacy_moves: Defer docs/size/layer findings of files staged as unchanged moves out of `legacy/`.

    Returns:
        Tuple of findings and whether the review passed (no blocking CRITICAL findings).
    """
    config, pc_mod = _load_project_cfg(root)
    patterns = getattr(pc_mod, "SECRET_PATTERNS", FALLBACK_SECRET_PATTERNS)
    issues: list[dict] = []
    all_text = ""
    for f in iter_source_files(root, config, pc_mod):
        rel = f.relative_to(root).as_posix()
        layer = pc_mod.detect_layer(rel, config) if pc_mod is not None else None  # type: ignore[attr-defined]
        text = f.read_text(encoding="utf-8", errors="replace")
        all_text += "\n" + text
        issues += secret_issues(text, rel, patterns)
        if f.suffix in (".py", *BRACE_LANG_PATTERNS):
            issues += file_size_issues(text, rel, config["quality"])
        if f.suffix == ".py":
            issues += audit_python_file(text, rel, layer, config)
        elif f.suffix.lower() in MARKUP_HEADERS:
            issues += markup_header_issues(text, rel, config)
        elif f.suffix in BRACE_LANG_PATTERNS:
            issues += audit_brace_file(text, rel, layer, config)
    issues += paired_call_issues(all_text, config)
    issues += removed_comment_issues(root)
    if allow_legacy_moves:
        issues = defer_legacy_moves(issues, staged_legacy_moves(root))
    blocking = bool(config["quality"].get("block_on_critical", True)) and any(i["severity"] == "CRITICAL" for i in issues)
    return issues, not blocking


def print_report(issues: list[dict], quiet: bool) -> None:
    """Print findings for humans.

    Args:
        issues: Findings from `run_review()`.
        quiet: Print only CRITICAL findings and no banner (used by the git hook).
    """
    shown = [i for i in issues if i["severity"] == "CRITICAL"] if quiet else issues
    if not quiet:
        print("=" * 64 + "\n🛡️  Code Review Guard\n" + "=" * 64)
        if not issues:
            print("✅ 沒有發現問題（註解、分層、秘密、函式大小皆符合設定）。")
    for item in shown:
        icon = "🚨" if item["severity"] == "CRITICAL" else "⚠️"
        print(f"  {icon} [{item['severity']}] {item['file']}:L{item['line']} ➔ {item['msg']}")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        0 when the review passes, 1 when blocking findings exist.
    """
    parser = argparse.ArgumentParser(description="Code Review Guard — 註解、分層、秘密與函式大小檢查")
    parser.add_argument("target", nargs="?", default=".", help="專案根目錄")
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出")
    parser.add_argument("--quiet", action="store_true", help="只輸出 CRITICAL（給 git hook 使用）")
    parser.add_argument("--allow-legacy-moves", action="store_true",
                        help="本次 commit 從 legacy/ 原樣搬入的檔案，註解/大小/分層問題先降為警告（給 pre-commit 使用）")
    args = parser.parse_args(argv)
    issues, passed = run_review(Path(args.target).resolve(), args.allow_legacy_moves)
    if args.json:
        print(json.dumps({"passed": passed, "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print_report(issues, args.quiet)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
