#!/usr/bin/env python3
"""API adapter scaffold: create an anti-corruption-layer adapter plus an offline test.

Purpose:
    When integrating an external API, the raw response format must not leak into the
    rest of the code. This tool creates, inside the project's Python package:
      - `<pkg>/adapters/<category>/<name>_adapter.py` : pure parser from raw JSON to an
        immutable DTO, raising `ProviderError` on malformed responses;
      - `tests/fixtures/<name>_sample.json`           : a saved sample response;
      - `tests/test_<name>_adapter.py`                : an offline unit test (no network).
    Every generated function is fully documented so it passes code-review-guard.

Usage:
    python3 .agents/skills/api-adapter-scaffold/scripts/scaffold_adapter.py --name brave_search --category search
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ADAPTER_TEMPLATE = '''"""Adapter for the {name} API: converts raw responses into internal DTOs.

Only this module knows the external response format. Other layers receive `{cls}Item`
objects and `ProviderError`, never raw JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
import json


class ProviderError(Exception):
    """Raised when the external provider returns an unusable response.

    Attributes:
        retryable: Whether retrying the request may succeed.
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        """Create the error.

        Args:
            message: Human-readable description.
            retryable: Whether retrying may succeed.
        """
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class {cls}Item:
    """One normalised result.

    Attributes:
        title: Result title.
        url: Result URL.
    """

    title: str
    url: str


def parse_{name}_payload(raw_text: str) -> list[{cls}Item]:
    """Parse a raw {name} response into DTOs (pure function, no I/O).

    Args:
        raw_text: Response body as returned by the API.

    Returns:
        Items that have both a title and a URL.

    Raises:
        ProviderError: When the body is not valid JSON.
    """
    try:
        data = json.loads(raw_text)
    except ValueError as exc:
        raise ProviderError("{name}: response is not valid JSON", retryable=True) from exc
    items = []
    for item in data.get("items", []):
        title, url = str(item.get("title", "")).strip(), str(item.get("url", "")).strip()
        if title and url:
            items.append({cls}Item(title=title, url=url))
    return items
'''

TEST_TEMPLATE = '''"""Offline tests for the {name} adapter (uses a saved fixture, no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from {module} import ProviderError, parse_{name}_payload  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "{name}_sample.json"


class {cls}AdapterTest(unittest.TestCase):
    """Behaviour of `parse_{name}_payload`."""

    def test_parses_fixture(self) -> None:
        """The saved sample response becomes one DTO."""
        items = parse_{name}_payload(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual([i.title for i in items], ["Sample Result"])

    def test_invalid_json_raises_provider_error(self) -> None:
        """Malformed responses are wrapped in ProviderError."""
        with self.assertRaises(ProviderError):
            parse_{name}_payload("not json")


if __name__ == "__main__":
    unittest.main()
'''

FIXTURE = '{\n  "items": [\n    {"title": "Sample Result", "url": "https://example.com"}\n  ]\n}\n'


def find_root() -> Path:
    """Locate the project root (folder containing `.agents/project.toml`).

    Returns:
        The project root, or the current working directory when none is found.
    """
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agents" / "project.toml").exists():
            return candidate
    return current


def find_package_dir(root: Path) -> Path:
    """Find the project's Python package directory under `src/`.

    Args:
        root: Project root.

    Returns:
        The first `src/<pkg>` folder that contains `__init__.py`.

    Raises:
        FileNotFoundError: When no Python package exists under `src/`.
    """
    for candidate in sorted((root / "src").glob("*/__init__.py")):
        return candidate.parent
    raise FileNotFoundError("No Python package found under src/ (expected src/<pkg>/__init__.py)")


def ensure_package(folder: Path, doc: str) -> None:
    """Create a package folder with a documented `__init__.py` if it does not exist.

    Args:
        folder: Package directory.
        doc: Module docstring for `__init__.py`.
    """
    folder.mkdir(parents=True, exist_ok=True)
    init = folder / "__init__.py"
    if not init.exists():
        init.write_text(f'"""{doc}"""\n', encoding="utf-8")


def scaffold_adapter(root: Path, category: str, name: str) -> list[Path]:
    """Create the adapter module, fixture and offline test.

    Args:
        root: Project root.
        category: Sub-folder under `adapters/`, e.g. `search` or `llm`.
        name: Adapter name, e.g. `brave_search`.

    Returns:
        Paths of the created files.

    Raises:
        FileExistsError: When the adapter already exists.
    """
    clean = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    cls = "".join(part.title() for part in clean.split("_"))
    pkg_dir = find_package_dir(root)
    adapter_dir = pkg_dir / "adapters" / category
    ensure_package(pkg_dir / "adapters", "Adapters layer: external APIs, databases, file and network I/O.")
    ensure_package(adapter_dir, f"{category.title()} adapters.")
    adapter_file = adapter_dir / f"{clean}_adapter.py"
    if adapter_file.exists():
        raise FileExistsError(f"{adapter_file.relative_to(root)} already exists")
    module = ".".join(adapter_file.relative_to(root / "src").with_suffix("").parts)
    tests_dir = root / "tests"
    files = {
        adapter_file: ADAPTER_TEMPLATE.format(name=clean, cls=cls),
        tests_dir / "fixtures" / f"{clean}_sample.json": FIXTURE,
        tests_dir / f"test_{clean}_adapter.py": TEST_TEMPLATE.format(name=clean, cls=cls, module=module),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return list(files)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="API Adapter 防腐層與離線測試產生器（Python）")
    parser.add_argument("--category", default="search", help="adapters 下的子資料夾，例如 search / llm / messaging")
    parser.add_argument("--name", required=True, help="Adapter 名稱，例如 brave_search")
    args = parser.parse_args(argv)
    root = find_root()
    try:
        created = scaffold_adapter(root, re.sub(r"[^a-z0-9_]+", "_", args.category.lower()), args.name)
    except (FileNotFoundError, FileExistsError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    for path in created:
        print(f"✅ 已建立 {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
