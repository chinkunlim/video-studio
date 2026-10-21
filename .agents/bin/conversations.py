#!/usr/bin/env python3
"""Local conversation records: one transcript + one summary per conversation (never in git).

Purpose:
    Every conversation leaves two Markdown files in `.agents/conversations/` (git-ignored):
      - `YYYY-MM-DD-HHMM-<agent>-transcript.md` : the full conversation, with secrets,
        tokens, passwords and e-mail addresses masked;
      - `YYYY-MM-DD-HHMM-<agent>-summary.md`    : goal, work & decisions, errors & root
        causes, next steps, changed files (written by `closeout`).
    They help the next agent and debugging on this computer and can be deleted when the
    project ends (`prune`). Anything that must survive across computers goes to git instead:
    the handoff board, ADRs and known issues.

Transcript sources (automatic, newest first; the agent's own tool is tried first):
    - Claude Code: `~/.claude/projects/<encoded project path>/*.jsonl`.
    - Antigravity: `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript.jsonl`
      (only conversations that mention this project's path).
    - Any other tool (Codex, Cursor…): pass an exported file with `--transcript`
      (Claude / Antigravity `.jsonl`, or plain text / Markdown).

Usage:
    python3 scripts/agentctl.py conversations list
    python3 scripts/agentctl.py conversations prune --before 2026-12-31
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import SECRET_PATTERNS  # noqa: E402

FOLDER = ROOT / ".agents" / "conversations"
EXTRA_REDACTIONS = [
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]"),
    (r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)\S+", r"\1\2[REDACTED]"),
    (r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}", "Bearer [REDACTED]"),
]
TOOL_TEXT_LIMIT = 400
ANTIGRAVITY_BRAIN = Path.home() / ".gemini" / "antigravity" / "brain"
PROJECT_SCAN_BYTES = 300_000


def redact(text: str) -> str:
    """Mask secrets, tokens, passwords and e-mail addresses.

    Args:
        text: Raw text.

    Returns:
        Text with sensitive values replaced by `[REDACTED]` / `[EMAIL]`.
    """
    for pattern, _label in SECRET_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    for pattern, replacement in EXTRA_REDACTIONS:
        text = re.sub(pattern, replacement, text)
    return text


def claude_project_dir(root: Path = ROOT) -> Path:
    """Return where Claude Code stores this project's conversations.

    Args:
        root: Project root.

    Returns:
        `~/.claude/projects/<path with every non-alphanumeric character replaced by '-'>`.
    """
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))


def latest_claude_transcript(root: Path = ROOT) -> Path | None:
    """Find the most recently updated Claude Code conversation of this project.

    Args:
        root: Project root.

    Returns:
        Path of the `.jsonl` file, or None when there is none.
    """
    folder = claude_project_dir(root)
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    return files[-1] if files else None


def latest_antigravity_transcript(root: Path = ROOT) -> Path | None:
    """Find the newest Antigravity conversation that belongs to this project.

    Args:
        root: Project root (a conversation belongs to it when its log mentions the path).

    Returns:
        Path of `transcript.jsonl`, or None when there is none.
    """
    if not ANTIGRAVITY_BRAIN.is_dir():
        return None
    marker = str(root.resolve())
    logs = sorted(ANTIGRAVITY_BRAIN.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in logs:
        with path.open(encoding="utf-8", errors="replace") as handle:
            if marker in handle.read(PROJECT_SCAN_BYTES):
                return path
    return None


def antigravity_to_markdown(path: Path) -> str:
    """Convert an Antigravity `transcript.jsonl` into readable Markdown.

    Truncated steps are taken from the sibling `transcript_full.jsonl` when it exists.

    Args:
        path: The `transcript.jsonl` file.

    Returns:
        Markdown with user turns, agent replies, tool calls and shortened tool output.
    """
    def load(file: Path) -> list[dict]:
        """Parse a JSON-lines file, skipping broken lines.

        Args:
            file: File to read.

        Returns:
            Parsed records.
        """
        if not file.exists():
            return []
        rows = []
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    steps, full = load(path), load(path.with_name("transcript_full.jsonl"))
    parts = []
    for idx, step in enumerate(steps):
        step = full[idx] if step.get("truncated_fields") and idx < len(full) else step
        kind, content = step.get("type"), str(step.get("content") or "").strip()
        when = str(step.get("created_at", ""))[:19]
        if kind == "USER_INPUT":
            parts.append(f"### 👤 User — {when}\n\n{content}")
        elif kind == "PLANNER_RESPONSE":
            calls = [f"> 🔧 `{c.get('name', 'tool')}` {str(c.get('args', ''))[:TOOL_TEXT_LIMIT]}" for c in step.get("tool_calls") or []]
            body = "\n\n".join([*calls, content] if content else calls)
            if body:
                parts.append(f"### 🤖 Assistant — {when}\n\n{body}")
        elif kind == "GENERIC" and content:
            parts.append(f"> 📎 結果：{content[:TOOL_TEXT_LIMIT]}")
    return "\n\n".join(parts)


def _block_text(block: object) -> str:
    """Render one message content block as Markdown.

    Args:
        block: A string or a content block dict (`text`, `tool_use`, `tool_result`, `thinking`).

    Returns:
        Markdown text (thinking blocks and empty blocks give an empty string).
    """
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    kind = block.get("type")
    if kind == "text":
        return str(block.get("text", ""))
    if kind == "tool_use":
        args = json.dumps(block.get("input", {}), ensure_ascii=False)
        return f"> 🔧 `{block.get('name', 'tool')}` {args[:TOOL_TEXT_LIMIT]}"
    if kind == "tool_result":
        content = block.get("content", "")
        body = content if isinstance(content, str) else " ".join(_block_text(c) for c in content or [])
        return f"> 📎 結果：{body.strip()[:TOOL_TEXT_LIMIT]}" if body.strip() else ""
    return ""


def jsonl_to_markdown(path: Path) -> str:
    """Convert a Claude-format `.jsonl` conversation into readable Markdown.

    Args:
        path: The `.jsonl` file.

    Returns:
        Markdown with one section per user / assistant message (sub-agent traffic skipped).
    """
    parts = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") not in ("user", "assistant") or record.get("isSidechain"):
            continue
        content = (record.get("message") or {}).get("content", "")
        blocks = content if isinstance(content, list) else [content]
        body = "\n\n".join(t for t in (_block_text(b).strip() for b in blocks) if t)
        if body:
            only_tools = bool(blocks) and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
            who = "📎 Tool result" if only_tools else ("👤 User" if record["type"] == "user" else "🤖 Assistant")
            parts.append(f"### {who} — {str(record.get('timestamp', ''))[:19]}\n\n{body}")
    return "\n\n".join(parts)


def is_antigravity_file(path: Path) -> bool:
    """Tell whether a `.jsonl` file uses the Antigravity step format.

    Args:
        path: File to inspect.

    Returns:
        True when the first record has an Antigravity step type.
    """
    with path.open(encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
    try:
        return json.loads(first).get("type") in ("USER_INPUT", "PLANNER_RESPONSE", "GENERIC")
    except (ValueError, AttributeError):
        return False


def detect_transcript(agent: str = "") -> Path | None:
    """Find this conversation's transcript automatically.

    Args:
        agent: Agent name; Antigravity / Gemini agents look in Antigravity's storage first.

    Returns:
        The newest matching transcript file, or None.
    """
    finders = [latest_claude_transcript, latest_antigravity_transcript]
    if any(word in agent.lower() for word in ("antigravity", "gemini", "agy")):
        finders.reverse()
    return next((p for p in (f() for f in finders) if p), None)


def read_transcript(source: Path | None, agent: str = "") -> tuple[str, str]:
    """Load a transcript from a file (any tool) or detect it automatically.

    Args:
        source: Explicit file, or None to auto-detect (Claude Code, Antigravity).
        agent: Agent name, used to decide which tool's storage to check first.

    Returns:
        Tuple of (Markdown text, description of the source); empty text when nothing was found.
    """
    path = source or detect_transcript(agent)
    if path is None or not path.is_file():
        return "", "未取得（請用 --transcript 指定匯出的對話檔）"
    if path.suffix != ".jsonl":
        return path.read_text(encoding="utf-8", errors="replace"), f"`{path.name}`"
    text = antigravity_to_markdown(path) if is_antigravity_file(path) else jsonl_to_markdown(path)
    return text, f"`{path.parent.parent.parent.name if is_antigravity_file(path) else path.name}`"


def record_paths(agent: str, when: datetime | None = None) -> tuple[Path, Path]:
    """Choose new transcript / summary file names for one conversation.

    Args:
        agent: Agent name (sanitised for the file name).
        when: Timestamp of the conversation end (default: now).

    Returns:
        Tuple of (transcript path, summary path); a numeric suffix avoids overwriting.
    """
    stamp = (when or datetime.now()).strftime("%Y-%m-%d-%H%M")
    base = f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '-', agent)}"
    counter, candidate = 2, base
    while (FOLDER / f"{candidate}-summary.md").exists():
        candidate, counter = f"{base}-{counter}", counter + 1
    return FOLDER / f"{candidate}-transcript.md", FOLDER / f"{candidate}-summary.md"


def write_record(agent: str, summary_md: str, transcript_source: Path | None = None) -> tuple[Path, Path]:
    """Write the transcript + summary pair for one conversation.

    Args:
        agent: Agent name.
        summary_md: Summary Markdown (secrets are masked before writing).
        transcript_source: Exported transcript file; None auto-detects Claude Code.

    Returns:
        Tuple of (transcript path, summary path).
    """
    FOLDER.mkdir(parents=True, exist_ok=True)
    transcript_path, summary_path = record_paths(agent)
    text, source = read_transcript(transcript_source, agent)
    header = f"# Transcript — `{agent}`\n\n- **來源**：{source}\n- **配對摘要**：[`{summary_path.name}`]({summary_path.name})\n\n---\n\n"
    transcript_path.write_text(header + redact(text or "（沒有取得對話內容）") + "\n", encoding="utf-8")
    summary_path.write_text(redact(summary_md).rstrip() + f"\n\n- **完整逐字稿**：[`{transcript_path.name}`]({transcript_path.name})\n", encoding="utf-8")
    return transcript_path, summary_path


def list_summaries(limit: int | None = None) -> list[Path]:
    """List summary files, newest first.

    Args:
        limit: Maximum number of results (None = all).

    Returns:
        Summary paths.
    """
    files = sorted(FOLDER.glob("*-summary.md"), reverse=True) if FOLDER.exists() else []
    return files[:limit] if limit else files


def prune(before: str) -> int:
    """Delete conversation records dated before `before` (e.g. when the project is finished).

    Args:
        before: Date `YYYY-MM-DD`; files whose name starts with an earlier date are removed.

    Returns:
        Number of deleted files.
    """
    removed = 0
    for path in sorted(FOLDER.glob("*.md")) if FOLDER.exists() else []:
        if path.name[:10] < before:
            path.unlink()
            removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="本機對話紀錄（逐字稿 + 摘要，不進 git）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出摘要（新的在前）")
    p_prune = sub.add_parser("prune", help="刪除某日期之前的對話紀錄")
    p_prune.add_argument("--before", required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    if args.cmd == "prune":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.before):
            print("❌ --before 必須是 YYYY-MM-DD", file=sys.stderr)
            return 1
        print(f"🗑️ 已刪除 {prune(args.before)} 個對話紀錄檔")
        return 0
    for path in list_summaries():
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
