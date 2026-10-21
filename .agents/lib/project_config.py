"""Project configuration loader and shared helpers for every framework script.

Purpose:
    Every framework tool reads per-project settings from `.agents/project.toml`
    through this module, so each project decides its own layers, quality
    thresholds, commands and business rules without editing framework code.

Main features:
    - `load_config()`            : DEFAULT_CONFIG deep-merged with `.agents/project.toml`.
    - Layer helpers              : `layer_rank()`, `source_dirs()`, `detect_layer()`.
    - Version helpers            : `read_version()`, `write_version()`, `bump_semver()`.
    - `resolve_agent_identity()` : who is the active AI agent (CLI > env vars > task card).
    - `git_changed_files()`      : robust `git status` parser (handles spaces, CJK names, renames).
    - `md_cell()`                : escape text so it is safe inside a Markdown table cell.

Compatibility:
    Python 3.9+. Uses `tomllib` (3.11+) or `tomli` when available, otherwise a small
    built-in parser supporting the TOML subset used by `project.toml`.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

CONFIG_RELATIVE_PATH = Path(".agents") / "project.toml"
FRAMEWORK_VERSION = "3.3.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "framework": {"version": FRAMEWORK_VERSION},
    "project": {"name": "", "languages": [], "workspaces": []},
    "architecture": {
        "source_roots": ["src"],
        # Top -> bottom. A nested list means "same rank" (may not import each other upward).
        "layers": ["entrypoints", "core", ["adapters", "store"], "config", "shared"],
        "env_access_layers": ["config"],
    },
    "quality": {
        "max_function_lines": 30,
        "hard_max_function_lines": 50,
        "max_params": 4,
        "max_nesting": 3,
        "block_on_critical": True,
        # Every source file needs a header docstring/comment and every function a
        # description plus an `Args:` (Python) or `@param` (JS/TS) entry per parameter.
        "require_docstrings": True,
        "max_file_lines": 500,
        "hard_max_file_lines": 800,
        "max_commit_file_mb": 10,
        "block_data_files": True,
        # Only these layers may `print` (a CLI's real output); every other layer logs.
        "print_allowed_layers": ["entrypoints"],
    },
    "commands": {"test": "", "lint": "", "typecheck": "", "dbcheck": "", "evals": ""},
    "skills": {"enabled": []},  # empty list = every skill installed in .agents/skills
    "agents": {
        "adapters": ["claude", "gemini", "copilot", "cursor", "windsurf"],
        "skill_link_dirs": [".claude/skills"],
        "require_agent_attribution": True,
    },
    # Commits add a line under CHANGELOG `## [Unreleased]`; `agentctl finish --tag` releases.
    "git": {"push_reminder_threshold": 5},
    "release": {"version_files": []},  # empty list = auto-detect
    "tree": {"agents_md_depth": 2, "annotations": {}},
    "project_rules": {"paired_calls": [], "forbidden_imports": []},
}

AUTO_VERSION_FILES = ("pyproject.toml", "package.json", "Cargo.toml", "VERSION")

# (regex, label) pairs shared by auto_commit.py and review_guard.py; keep in sync with .agents/hooks/pre-commit
SECRET_PATTERNS = [
    (r"AIza[0-9A-Za-z_-]{20,}", "Google / Gemini API Key"),
    (r"[0-9]{8,10}:AA[0-9A-Za-z_-]{30,}", "Telegram Bot Token"),
    (r"gh[opsu]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}", "GitHub Token"),
    (r"sk-ant-[0-9A-Za-z_-]{20,}", "Anthropic API Key"),
    (r"sk-(?:proj-)?[0-9A-Za-z_-]{20,}", "OpenAI / Generic Secret Key"),
    (r"(?:AKIA|ASIA)[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"xox[abposr]-[0-9A-Za-z-]{10,}", "Slack Token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY", "Private Key"),
]

# (agent label, environment variable that the tool sets while it runs)
AGENT_ENV_MARKERS = (
    ("claude-code", "CLAUDECODE"),
    ("gemini-cli", "GEMINI_CLI"),
    ("antigravity", "ANTIGRAVITY_AGENT"),
    ("cursor", "CURSOR_TRACE_ID"),
    ("windsurf", "WINDSURF_SESSION"),
    ("github-copilot", "COPILOT_AGENT"),
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward until a directory containing `.agents/project.toml` or `.git` is found.

    Args:
        start: Directory to start searching from. Defaults to the current working directory.

    Returns:
        The first ancestor (including `start`) that looks like a project root, or
        `start` itself when nothing matches.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_RELATIVE_PATH).exists() or (candidate / ".git").exists():
            return candidate
    return current


def load_config(root: Path | None = None) -> dict[str, Any]:
    """Return DEFAULT_CONFIG deep-merged with the project's `.agents/project.toml`.

    Args:
        root: Project root directory. Auto-detected with `find_project_root()` when omitted.

    Returns:
        A new configuration dictionary; callers may mutate it freely.
    """
    project_root = root or find_project_root()
    config_path = project_root / CONFIG_RELATIVE_PATH
    user_config: dict[str, Any] = {}
    if config_path.exists():
        user_config = parse_toml(config_path.read_text(encoding="utf-8"))
    return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), user_config)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base` (dict values merge, other values replace).

    Args:
        base: Dictionary that receives the merged values (mutated in place).
        override: Dictionary whose values take precedence.

    Returns:
        The mutated `base` dictionary.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def parse_toml(text: str) -> dict[str, Any]:
    """Parse TOML text with the best parser available on this Python version.

    Args:
        text: Raw TOML document.

    Returns:
        Parsed TOML as nested dictionaries.
    """
    try:
        import tomllib  # type: ignore[import-not-found]

        return tomllib.loads(text)
    except ModuleNotFoundError:
        pass
    try:
        import tomli  # type: ignore[import-not-found]

        return tomli.loads(text)
    except ModuleNotFoundError:
        return _MiniToml(text).parse()


# ---------------------------------------------------------------------------
# Architecture helpers (layers / source roots)
# ---------------------------------------------------------------------------


def layer_rank(config: dict[str, Any]) -> dict[str, int]:
    """Map each layer name to its rank (0 = top layer). Nested lists share one rank.

    Args:
        config: Loaded project configuration.

    Returns:
        Dictionary of `layer name -> rank`.
    """
    ranks: dict[str, int] = {}
    for idx, entry in enumerate(config["architecture"]["layers"]):
        for name in entry if isinstance(entry, list) else [entry]:
            ranks[str(name)] = idx
    return ranks


def layer_names_top_down(config: dict[str, Any]) -> list[str]:
    """List layer names ordered from the top layer to the bottom layer.

    Args:
        config: Loaded project configuration.

    Returns:
        Layer names in rank order.
    """
    return list(layer_rank(config).keys())


def source_root_prefixes(config: dict[str, Any]) -> list[str]:
    """Return relative source roots, expanded for monorepo workspaces.

    Args:
        config: Loaded project configuration.

    Returns:
        Relative paths such as `src/my_app` or `packages/api/src`.
    """
    roots = [r.strip("/") for r in config["architecture"]["source_roots"]]
    workspaces = [w.strip("/") for w in config["project"].get("workspaces", []) if w.strip("/") not in ("", ".")]
    expanded = [f"{ws}/{r}" for ws in workspaces for r in roots]
    return expanded or roots


def source_dirs(root: Path, config: dict[str, Any]) -> list[Path]:
    """Return the source directories that actually exist on disk.

    Args:
        root: Project root directory.
        config: Loaded project configuration.

    Returns:
        Absolute paths of existing source roots.
    """
    return [root / p for p in source_root_prefixes(config) if (root / p).is_dir()]


def detect_layer(rel_path: str, config: dict[str, Any]) -> str | None:
    """Return the architectural layer that a repo-relative path belongs to.

    Args:
        rel_path: POSIX-style path relative to the project root, e.g. `src/app/services/x.py`.
        config: Loaded project configuration.

    Returns:
        The layer name, or None when the path is outside every configured layer.
    """
    ranks = layer_rank(config)
    for prefix in source_root_prefixes(config):
        if rel_path.startswith(prefix + "/"):
            first = rel_path[len(prefix) + 1 :].split("/", 1)[0]
            stem = Path(first).stem
            for cand in (first, stem, stem.lower()):
                if cand in ranks:
                    return cand
    return None


# ---------------------------------------------------------------------------
# Version helpers (language agnostic)
# ---------------------------------------------------------------------------

_TOML_VERSION_RE = re.compile(r'^(version\s*=\s*)"([^"]+)"', re.M)


def version_files(root: Path, config: dict[str, Any]) -> list[Path]:
    """Return the version files to read/write (configured list or auto-detected).

    Args:
        root: Project root directory.
        config: Loaded project configuration.

    Returns:
        Existing version files such as `pyproject.toml` or `package.json`.
    """
    configured = config["release"].get("version_files") or []
    names = configured or [n for n in AUTO_VERSION_FILES if (root / n).exists()]
    return [root / n for n in names if (root / n).exists()]


def read_version(root: Path, config: dict[str, Any]) -> str:
    """Read the current project version from the first version file that has one.

    Args:
        root: Project root directory.
        config: Loaded project configuration.

    Returns:
        A SemVer string; `0.1.0` when no version file exists.
    """
    for path in version_files(root, config):
        found = _read_version_from(path)
        if found:
            return found
    return "0.1.0"


def write_version(root: Path, config: dict[str, Any], new_version: str) -> list[Path]:
    """Write `new_version` into every version file (creates `VERSION` if none exist).

    Args:
        root: Project root directory.
        config: Loaded project configuration.
        new_version: SemVer string to write.

    Returns:
        The files that were written.
    """
    files = version_files(root, config) or [root / "VERSION"]
    for path in files:
        _write_version_to(path, new_version)
    return files


def bump_semver(current: str, bump: str) -> str:
    """Compute the next SemVer version.

    Args:
        current: Current version such as `1.4.2`.
        bump: One of `major`, `minor`, `patch` or `none`.

    Returns:
        The bumped version (unchanged when `bump` is `none`).
    """
    if bump == "none":
        return current
    parts = [int(x) if x.isdigit() else 0 for x in current.split(".")[:3]]
    major, minor, patch = (parts + [0, 0, 0])[:3]
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


UNRELEASED = "## [Unreleased]"
SECTION_ORDER = ("Added", "Changed", "Fixed", "Removed", "Documentation", "Testing", "Chore")


def _unreleased_span(text: str) -> tuple[int, int]:
    """Locate the body of the `## [Unreleased]` section, inserting the heading if missing.

    Args:
        text: CHANGELOG content (must already contain the heading; see `ensure_unreleased`).

    Returns:
        `(start, end)` offsets of the section body (after the heading line, before the next `## [`).
    """
    start = text.index(UNRELEASED) + len(UNRELEASED)
    nxt = re.search(r"^## \[", text[start:], flags=re.M)
    return start, (start + nxt.start() if nxt else len(text))


def ensure_unreleased(text: str) -> str:
    """Make sure the changelog has an `## [Unreleased]` heading above the first release.

    Args:
        text: CHANGELOG content.

    Returns:
        Content with the heading present.
    """
    if UNRELEASED in text:
        return text
    match = re.search(r"^## \[", text, flags=re.M)
    if match:
        return text[: match.start()] + UNRELEASED + "\n\n" + text[match.start() :]
    return text.rstrip() + "\n\n" + UNRELEASED + "\n"


def unreleased_entries(text: str) -> dict[str, list[str]]:
    """Read the pending entries under `## [Unreleased]`, grouped by `### Section`.

    Args:
        text: CHANGELOG content.

    Returns:
        Mapping of section name -> bullet lines (without the leading `- `); empty when nothing is pending.
    """
    if UNRELEASED not in text:
        return {}
    start, end = _unreleased_span(text)
    grouped: dict[str, list[str]] = {}
    section = "Changed"
    for line in text[start:end].splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        elif line.startswith("- "):
            grouped.setdefault(section, []).append(line[2:])
    return grouped


def _render_sections(grouped: dict[str, list[str]]) -> str:
    """Render grouped entries as `### Section` blocks in a stable order.

    Args:
        grouped: Mapping of section name -> bullet lines.

    Returns:
        Markdown text (empty when there are no entries).
    """
    names = [s for s in SECTION_ORDER if s in grouped] + [s for s in grouped if s not in SECTION_ORDER]
    return "\n\n".join(f"### {s}\n" + "\n".join(f"- {b}" for b in grouped[s]) for s in names)


def add_unreleased_entry(text: str, section: str, line: str) -> str:
    """Append one bullet under `## [Unreleased]` → `### section` (used by every commit).

    Args:
        text: CHANGELOG content.
        section: Keep-a-Changelog section such as `Added` or `Fixed`.
        line: Bullet text without the leading `- `.

    Returns:
        Updated CHANGELOG content; the version number is not touched.
    """
    text = ensure_unreleased(text)
    grouped = unreleased_entries(text)
    grouped.setdefault(section, []).append(line)
    start, end = _unreleased_span(text)
    return text[:start] + "\n\n" + _render_sections(grouped) + "\n\n" + text[end:].lstrip("\n")


def release_unreleased(text: str, version: str, day: str) -> str:
    """Turn the pending entries into a `## [version] - day` release and leave an empty Unreleased.

    Args:
        text: CHANGELOG content.
        version: New version such as `0.2.0`.
        day: Release date (`YYYY-MM-DD`).

    Returns:
        Updated CHANGELOG content.
    """
    text = ensure_unreleased(text)
    body = _render_sections(unreleased_entries(text)) or "### Changed\n- Maintenance release"
    start, end = _unreleased_span(text)
    return text[:start] + f"\n\n## [{version}] - {day}\n\n{body}\n\n" + text[end:].lstrip("\n")


def release_bump(grouped: dict[str, list[str]]) -> str:
    """Pick the SemVer bump for a release from its pending entries.

    Args:
        grouped: Entries from `unreleased_entries()`.

    Returns:
        `minor` when something was added, otherwise `patch`.
    """
    return "minor" if grouped.get("Added") else "patch"


def _read_version_from(path: Path) -> str | None:
    """Extract the version string from one version file.

    Args:
        path: `package.json`, a `.toml` file, or a plain `VERSION` file.

    Returns:
        The version string, or None when the file has no version.
    """
    text = path.read_text(encoding="utf-8")
    if path.name == "package.json":
        return str(json.loads(text).get("version") or "") or None
    if path.suffix == ".toml":
        match = _TOML_VERSION_RE.search(text)
        return match.group(2) if match else None
    return text.strip() or None


def _write_version_to(path: Path, new_version: str) -> None:
    """Replace the version inside one version file, preserving the rest of the file.

    Args:
        path: `package.json`, a `.toml` file, or a plain `VERSION` file.
        new_version: SemVer string to write.
    """
    if path.name == "package.json":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = new_version
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    elif path.suffix == ".toml":
        text = path.read_text(encoding="utf-8")
        path.write_text(_TOML_VERSION_RE.sub(rf'\g<1>"{new_version}"', text, count=1), encoding="utf-8")
    else:
        path.write_text(new_version + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------


def detect_agent_from_env() -> str:
    """Detect the running AI agent from environment variables.

    `AI_AGENT_NAME` (explicit) wins; otherwise known tool markers such as
    `CLAUDECODE=1` (set by Claude Code) are checked.

    Returns:
        The agent label, or an empty string when nothing is detected.
    """
    explicit = os.environ.get("AI_AGENT_NAME", "").strip()
    if explicit:
        return explicit
    for label, env_name in AGENT_ENV_MARKERS:
        if os.environ.get(env_name, "").strip():
            return label
    return ""


def resolve_agent_identity(
    cli_agent: str = "",
    cli_model: str = "",
    root: Path | None = None,
    task_id: str = "",
) -> tuple[str, str]:
    """Resolve `(agent_name, model_name)` for attribution.

    Priority: CLI argument > environment variables > the agent of `task_id` >
    the single agent that currently has an `in_progress` task.

    Args:
        cli_agent: Agent name passed on the command line (may be empty).
        cli_model: Model name passed on the command line (may be empty).
        root: Project root used to look up task cards. Auto-detected when omitted.
        task_id: Task card ID such as `TASK-001` used as a fallback source.

    Returns:
        Tuple of agent name (`unattributed-agent` when unknown) and model name.
    """
    agent = cli_agent.strip() or detect_agent_from_env()
    model = cli_model.strip() or os.environ.get("AI_MODEL_NAME", "").strip()
    if not agent:
        agent = _agent_from_tasks(root or find_project_root(), task_id)
    return (agent or "unattributed-agent", model)


def _agent_from_tasks(project_root: Path, task_id: str) -> str:
    """Infer the agent from task cards when no CLI/env identity is available.

    Args:
        project_root: Project root directory.
        task_id: Preferred task ID; its owner wins when it has one.

    Returns:
        The inferred agent name, or an empty string.
    """
    tasks_dir = project_root / ".agents" / "tasks"
    if not tasks_dir.exists():
        return ""
    in_progress_agents: list[str] = []
    for f in sorted(tasks_dir.glob("TASK-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if task_id and data.get("id", "").upper() == task_id.upper() and data.get("agent"):
            return str(data["agent"]).strip()
        if data.get("status") == "in_progress" and data.get("agent"):
            in_progress_agents.append(str(data["agent"]).strip())
    return in_progress_agents[0] if len(set(in_progress_agents)) == 1 else ""


# ---------------------------------------------------------------------------
# Git & Markdown helpers
# ---------------------------------------------------------------------------


def venv_moved(root: Path) -> bool:
    """Tell whether the project `.venv` was created in another folder (the project was moved or copied).

    Virtual environments store absolute paths in their launcher scripts (`.venv/bin/mypy`, ...),
    so after moving a project those tools fail with "No such file or directory" even though
    `uv run python` still works. The fix is to rebuild `.venv` from `uv.lock`.

    Args:
        root: Project root directory.

    Returns:
        True when a launcher in `.venv/bin` points to a different `.venv`.
    """
    bin_dir = root / ".venv" / "bin"
    if not bin_dir.is_dir():
        return False
    here = {str(root / ".venv"), str((root / ".venv").resolve())}
    for script in sorted(bin_dir.iterdir()):
        if script.is_symlink() or not script.is_file():
            continue
        try:
            head = script.read_bytes()[:600].decode("utf-8", errors="ignore")
        except OSError:
            continue
        if head.startswith("#!") and "/.venv/bin/python" in head:
            return not any(f"{h}/bin/python" in head for h in here)
    return False


def git_changed_files(root: Path) -> list[tuple[str, str]]:
    """List uncommitted changes as `(status, path)` pairs.

    Uses `git status --porcelain -z` so paths with spaces or CJK characters are
    returned verbatim (no quoting) and the first line is never mangled by stripping.
    Untracked directories are expanded into individual files.

    Args:
        root: Repository root directory.

    Returns:
        List of `(two-letter status with spaces removed, repo-relative path)`; empty
        when `root` is not a git repository.
    """
    res = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return []
    entries = res.stdout.split("\0")
    items: list[tuple[str, str]] = []
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        idx += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":
            idx += 1  # the next entry is the original path of a rename/copy
        items.append((status.replace(" ", "") or "M", path))
    return items


def md_cell(text: object) -> str:
    """Escape arbitrary text so it renders inside a single Markdown table cell.

    Args:
        text: Any value; converted with `str()`.

    Returns:
        Text with `|` escaped and line breaks converted to `<br/>`.
    """
    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("|", "\\|").replace("\n", "<br/>")


# ---------------------------------------------------------------------------
# Minimal TOML parser (fallback for Python < 3.11 without tomli)
# ---------------------------------------------------------------------------


class _MiniToml:
    """Line-based parser for the TOML subset used by `.agents/project.toml`."""

    def __init__(self, text: str) -> None:
        """Store the document lines.

        Args:
            text: Raw TOML document.
        """
        self.lines = text.splitlines()

    def parse(self) -> dict[str, Any]:
        """Parse tables, dotted keys and (multi-line) arrays.

        Returns:
            Parsed document as nested dictionaries.
        """
        data: dict[str, Any] = {}
        table = data
        pending = ""
        for raw in self.lines:
            line = _strip_comment(raw).strip()
            if pending:
                pending += " " + line
                if _brackets_balanced(pending):
                    self._assign(table, pending)
                    pending = ""
                continue
            if not line:
                continue
            if line.startswith("[") and not line.startswith("[["):
                table = data
                for part in _split_key(line[1:-1]):
                    table = table.setdefault(part, {})
                continue
            if _brackets_balanced(line):
                self._assign(table, line)
            else:
                pending = line
        return data

    @staticmethod
    def _assign(table: dict[str, Any], line: str) -> None:
        """Assign one `key = value` line into `table`.

        Args:
            table: Current TOML table (mutated in place).
            line: A complete assignment line (arrays already joined).
        """
        key_part, value_part = _split_assignment(line)
        keys = _split_key(key_part)
        for part in keys[:-1]:
            table = table.setdefault(part, {})
        table[keys[-1]] = _ValueParser(value_part.strip()).parse()


def _strip_comment(line: str) -> str:
    """Remove a trailing `#` comment that is not inside a quoted string.

    Args:
        line: One raw TOML line.

    Returns:
        The line without its comment.
    """
    quote = ""
    for idx, ch in enumerate(line):
        if quote:
            if ch == quote and line[idx - 1] != "\\":
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return line[:idx]
    return line


def _brackets_balanced(text: str) -> bool:
    """Check whether every `[` outside strings has a matching `]`.

    Args:
        text: Partial or complete TOML value text.

    Returns:
        True when the brackets are balanced (the value is complete).
    """
    depth, quote = 0, ""
    for idx, ch in enumerate(text):
        if quote:
            if ch == quote and text[idx - 1] != "\\":
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
    return depth <= 0


def _split_assignment(line: str) -> tuple[str, str]:
    """Split `key = value` at the first `=` outside quotes.

    Args:
        line: A TOML assignment line.

    Returns:
        Tuple of key text and value text.

    Raises:
        ValueError: When the line has no assignment.
    """
    quote = ""
    for idx, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "=":
            return line[:idx], line[idx + 1 :]
    raise ValueError(f"Invalid TOML line: {line}")


def _split_key(key: str) -> list[str]:
    """Split a dotted key (`a."b.c".d`) into its parts.

    Args:
        key: Raw key text, possibly quoted.

    Returns:
        Key parts with quotes removed.
    """
    parts, buf, quote = [], "", ""
    for ch in key.strip():
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf += ch
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ".":
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    parts.append(buf.strip())
    return parts


class _ValueParser:
    """Recursive-descent parser for TOML values (strings, arrays, scalars)."""

    _ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

    def __init__(self, text: str) -> None:
        """Prepare to parse one value.

        Args:
            text: The value text to the right of `=`.
        """
        self.s, self.i = text, 0

    def parse(self) -> Any:
        """Parse the value.

        Returns:
            The Python value (str, list, bool, int, float).
        """
        return self._value()

    def _skip_ws(self) -> None:
        """Advance past whitespace and newlines."""
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def _value(self) -> Any:
        """Parse the value at the current position.

        Returns:
            The parsed value.
        """
        self._skip_ws()
        ch = self.s[self.i]
        if ch in ('"', "'"):
            return self._string(ch)
        if ch == "[":
            return self._array()
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in ",]":
            self.i += 1
        return _scalar(self.s[start : self.i].strip())

    def _string(self, quote: str) -> str:
        """Parse a basic (`"`) or literal (`'`) string.

        Args:
            quote: The opening quote character.

        Returns:
            The unescaped string.
        """
        self.i += 1
        out = []
        while self.s[self.i] != quote:
            ch = self.s[self.i]
            if quote == '"' and ch == "\\":
                self.i += 1
                ch = self._ESCAPES.get(self.s[self.i], self.s[self.i])
            out.append(ch)
            self.i += 1
        self.i += 1
        return "".join(out)

    def _array(self) -> list[Any]:
        """Parse an array (possibly nested).

        Returns:
            The parsed list.
        """
        self.i += 1
        items: list[Any] = []
        while True:
            self._skip_ws()
            if self.s[self.i] == "]":
                self.i += 1
                return items
            items.append(self._value())
            self._skip_ws()
            if self.s[self.i] == ",":
                self.i += 1


def _scalar(token: str) -> Any:
    """Convert a bare TOML token into bool, int, float or string.

    Args:
        token: Unquoted token text.

    Returns:
        The converted value.
    """
    if token in ("true", "false"):
        return token == "true"
    cleaned = token.replace("_", "")
    for cast in (int, float):
        try:
            return cast(cleaned)
        except ValueError:
            continue
    return token
