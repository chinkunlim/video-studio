#!/usr/bin/env python3
"""Dependency graph and layer audit for agents (build_graph.py).

Purpose:
    Shows which module imports which, flags imports that go *up* the layer order
    (e.g. `domain` importing `services`), lists functions that exceed the size limits,
    and maps `ADR-NNN` / `ISSUE-NNN` references in code to files.

Reads `.agents/project.toml` for:
  - [architecture] source_roots / layers  -> which folders are layers, and allowed direction
  - [project] workspaces                  -> monorepo packages (each with its own source roots)
  - [quality] max_function_lines / max_params

Outputs:
  - docs/architecture/GRAPH_REPORT.md  (human / agent readable; on demand, git-ignored)
  - .agents/cache/graph.json           (machine queryable; git-ignored)
`agentctl check` runs it for the layer check; `agentctl graph` when you want to read the report.

Exit code 1 when an upward (reverse) layer import is found.

Usage:
    python3 scripts/agentctl.py graph
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import detect_layer, layer_names_top_down, layer_rank, load_config, source_dirs  # noqa: E402

REPORT_FILE = ROOT / "docs" / "architecture" / "GRAPH_REPORT.md"
GRAPH_JSON_FILE = ROOT / ".agents" / "cache" / "graph.json"
CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs"}
JS_IMPORT_RE = re.compile(r"""(?:require\(\s*|from\s+|import\s+)['"]([^'"]+)['"]|use\s+(?:crate|super)::([A-Za-z0-9_:]+)|"[^"]+/(internal/[A-Za-z0-9_/-]+)" """)
JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:pub\s+)?(?:async\s+)?(?:function|func|fn)\s+(?:\([^)]+\)\s*)?([A-Za-z0-9_$]+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)"
)
GO_IMPORT_RE = re.compile(r'"[^"]+/(internal/[A-Za-z0-9_/-]+)"')
RUST_USE_RE = re.compile(r"\buse\s+(?:crate|super)::([A-Za-z0-9_]+)")
REF_RE = re.compile(r"\b(?:ADR|ISSUE)-\d{3}\b")


def _symbol(name: str, kind: str, lineno: int, lines: int, args: int, quality: dict) -> dict:
    """Describe one top-level function or class for the symbol index.

    Args:
        name: Symbol name.
        kind: `function` or `class`.
        lineno: Line where the symbol starts.
        lines: Length in lines.
        args: Parameter count.
        quality: `[quality]` configuration (size thresholds).

    Returns:
        Symbol dict including `atomic_ok` (within thresholds).
    """
    ok = kind != "function" or (lines <= quality["max_function_lines"] and args <= quality["max_params"])
    return {"kind": kind, "name": name, "lineno": lineno, "lines": lines, "args": args, "atomic_ok": ok}


def parse_python(text: str, rel: str, quality: dict) -> tuple[list[str], list[dict]]:
    """Extract imports and top-level symbols from Python source.

    Args:
        text: File content.
        rel: Repo-relative path (for syntax error messages).
        quality: `[quality]` configuration.

    Returns:
        Tuple of import strings (relative imports keep their leading dots) and symbols.
    """
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return [], []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append("." * node.level + node.module)
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
            is_fn = not isinstance(node, ast.ClassDef)
            args = len(node.args.args) if is_fn else 0
            symbols.append(_symbol(node.name, "function" if is_fn else "class", node.lineno, length, args, quality))
    return imports, symbols


def _js_function_length(lines: list[str], start: int) -> int:
    """Count the lines of a brace-delimited function.

    Args:
        lines: File lines.
        start: 0-based index of the signature line.

    Returns:
        Number of lines until the matching closing brace.
    """
    depth, started = 0, False
    for idx in range(start, len(lines)):
        depth += lines[idx].count("{") - lines[idx].count("}")
        started = started or "{" in lines[idx]
        if started and depth <= 0:
            return idx - start + 1
    return len(lines) - start


def parse_js(text: str, quality: dict) -> tuple[list[str], list[dict]]:
    """Extract imports and functions from JS/TS/Go/Rust source with regular expressions.

    Args:
        text: File content.
        quality: `[quality]` configuration.

    Returns:
        Tuple of import strings and symbols.
    """
    lines = text.splitlines()
    symbols = []
    for idx, line in enumerate(lines):
        match = JS_FUNC_RE.match(line)
        if match:
            args = len([a for a in match.group(2).split(",") if a.strip()])
            symbols.append(_symbol(match.group(1), "function", idx + 1, _js_function_length(lines, idx), args, quality))
    js_imps = [m[1] for m in re.findall(r"""(?:require\(\s*|from\s+|import\s+)(['"])([^'"]+)\1""", text)]
    go_imps = GO_IMPORT_RE.findall(text)
    rs_imps = [f"./{mod}" for mod in RUST_USE_RE.findall(text)]
    return sorted(set(js_imps + go_imps + rs_imps)), symbols


def resolve_import(src_rel: str, imp: str) -> str | None:
    """Resolve an import string to a file inside the repository.

    Args:
        src_rel: Repo-relative path of the importing file.
        imp: Import string (dotted Python module, relative JS path, Go `internal/...`, Rust `./mod`).

    Returns:
        Repo-relative path of the imported file, or None for third-party/unresolvable imports.
    """
    candidates: list[Path] = []
    if imp.startswith("."):
        base = (ROOT / src_rel).parent
        if "/" in imp or imp in (".", ".."):
            stem = (base / imp).resolve()
        else:
            dots = len(imp) - len(imp.lstrip("."))
            stem = base.joinpath(*([".."] * (dots - 1)), *imp.lstrip(".").split(".")).resolve()
        candidates = [Path(str(stem) + ext) for ext in ("", ".py", ".js", ".ts", ".tsx", ".rs", ".go")]
        candidates += [stem / "index.js", stem / "index.ts", stem / "__init__.py", stem / "mod.rs"]
    elif "/" in imp:
        stem = ROOT / imp
        candidates = [Path(str(stem) + ext) for ext in ("", ".go", ".js", ".ts", ".rs")]
        if stem.is_dir():
            candidates.extend(sorted(stem.glob("*.go")))
    else:
        parts = imp.split(".")
        for search_base in (ROOT, ROOT / "src"):
            stem = search_base.joinpath(*parts)
            candidates.extend([Path(str(stem) + ".py"), stem / "__init__.py", Path(str(stem) + ".rs")])
    for cand in candidates:
        if cand.is_file():
            try:
                return cand.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                return None
    return None


def collect_modules(config: dict) -> list[dict]:
    """Parse every code file under the source roots and test folders.

    Args:
        config: Loaded project configuration.

    Returns:
        Module dicts with `path`, `layer`, `imports`, `symbols`, `refs`.
    """
    quality = config["quality"]
    folders = source_dirs(ROOT, config) + [ROOT / "test", ROOT / "tests"]
    modules = []
    seen: set[str] = set()
    for base in folders:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in CODE_SUFFIXES or not path.is_file() or "node_modules" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            text = path.read_text(encoding="utf-8", errors="replace")
            imports, symbols = parse_python(text, rel, quality) if path.suffix == ".py" else parse_js(text, quality)
            modules.append({
                "path": rel,
                "layer": detect_layer(rel, config),
                "imports": sorted(set(imports)),
                "symbols": symbols,
                "refs": sorted(set(REF_RE.findall(text))),
            })
    return modules


def build_edges(modules: list[dict], config: dict) -> tuple[list[dict], list[str]]:
    """Turn imports into graph edges and detect upward (reverse) layer imports.

    Args:
        modules: Output of `collect_modules()`.
        config: Loaded project configuration.

    Returns:
        Tuple of edge dicts and human-readable violation messages.
    """
    ranks = layer_rank(config)
    edges, violations = [], []
    for mod in modules:
        for imp in mod["imports"]:
            target = resolve_import(mod["path"], imp)
            if not target:
                continue
            edges.append({"source": mod["path"], "target": target, "type": "IMPORTS", "confidence": "EXTRACTED"})
            src_layer, tgt_layer = mod["layer"], detect_layer(target, config)
            if src_layer and tgt_layer and ranks[src_layer] > ranks[tgt_layer]:
                violations.append(f"❌ 逆向依賴：`{mod['path']}` ({src_layer}) 不可引用上層 `{target}` ({tgt_layer})")
    return edges, violations


def render_report(modules: list[dict], edges: list[dict], violations: list[str], config: dict) -> str:
    """Render `docs/architecture/GRAPH_REPORT.md`.

    Args:
        modules: Parsed modules.
        edges: Import edges.
        violations: Layer violation messages.
        config: Loaded project configuration.

    Returns:
        Markdown text.
    """
    quality = config["quality"]
    layer_chain = " ➔ ".join(layer_names_top_down(config))
    mermaid = ["flowchart TD"]
    for e in edges[:200]:
        s_id, t_id = (re.sub(r"[^A-Za-z0-9_]", "_", e[k]) for k in ("source", "target"))
        mermaid.append(f'    {s_id}["{e["source"]}"] --> {t_id}["{e["target"]}"]')
    if len(mermaid) == 1:
        mermaid.append('    Empty["(尚無內部 import 邊)"]')

    sym_rows = [
        f"| `{m['path']}` | `{s['name']}` ({s['kind']}) | L{s['lineno']} | {s['lines']} | {s['args']} | "
        f"{'✅' if s['atomic_ok'] else '⚠️ 需拆分'} |"
        for m in modules for s in m["symbols"]
    ] or ["| (無) | - | - | - | - | - |"]

    trace: dict[str, list[str]] = {}
    for m in modules:
        for ref in m["refs"]:
            trace.setdefault(ref, []).append(m["path"])
    trace_rows = [f"| **{k}** | {', '.join(f'`{p}`' for p in v)} |" for k, v in sorted(trace.items())]
    trace_rows = trace_rows or ["| (尚無標記) | 在程式碼註解寫 `ADR-001` / `ISSUE-001` 即可自動連結 |"]

    violation_text = "\n".join(violations) if violations else f"✅ 0 個逆向依賴（分層：`{layer_chain}`）"
    nl = "\n"
    return f"""# 專案 AST 知識圖譜與架構合規報告 (GRAPH_REPORT)

> ⚠️ 由 `python3 scripts/agentctl.py graph` 自動產生，請勿手動編輯。分層與門檻設定於 `.agents/project.toml`。

## 1. 模組依賴圖 (前 200 條邊)

```mermaid
{nl.join(mermaid)}
```

## 2. 分層依賴審計

{violation_text}

## 3. 符號索引與 Atomic 檢核 (函式 ≤ {quality['max_function_lines']} 行、參數 ≤ {quality['max_params']} 個)

| 檔案 | 符號 | 起始行 | 行數 | 參數 | 狀態 |
|---|---|---|---|---|---|
{nl.join(sym_rows)}

## 4. ADR / ISSUE 溯源

| 編號 | 關聯檔案 |
|---|---|
{nl.join(trace_rows)}
"""


def main() -> int:
    """Build the graph, write the report and JSON, and exit 1 on layer violations.

    Returns:
        Process exit code.
    """
    config = load_config(ROOT)
    modules = collect_modules(config)
    edges, violations = build_edges(modules, config)
    graph = {"generator": "build_graph", "nodes": modules, "edges": edges, "layer_violations": violations}

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(render_report(modules, edges, violations, config), encoding="utf-8")
    GRAPH_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_JSON_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print(f"✅ 知識圖譜已更新：{len(modules)} 個模組、{len(edges)} 條依賴邊")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
