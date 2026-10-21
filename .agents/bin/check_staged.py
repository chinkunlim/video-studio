#!/usr/bin/env python3
"""Pre-commit data guard: keep data files and very large files out of git.

Purpose:
    Data belongs in `DATA_DIR` (outside the project), never in the repository. This check
    runs from the pre-commit hook and blocks staged files that
      - have a data extension (PDF, EPUB, archives, media, databases, notebooks' big
        outputs …) — small samples under `tests/fixtures/` or `evals/cases/` are allowed;
      - are larger than `[quality] max_commit_file_mb` (default 10 MB) anywhere.
    Document projects whose deliverables ARE documents (e.g. course materials in .docx / .pdf)
    can set `[quality] block_data_files = false`; the size limit still applies.

Usage:
    python3 .agents/bin/check_staged.py    # exit 1 when something should not be committed
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]  # .agents/bin/<script> -> project root
sys.path.insert(0, str(ROOT / ".agents" / "lib"))

from project_config import load_config  # noqa: E402

DATA_EXTENSIONS = {
    ".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a", ".flac",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".feather", ".h5", ".pkl", ".npy", ".npz",
}
SAMPLE_DIRS = ("tests/fixtures/", "evals/cases/")
SAMPLE_MAX_BYTES = 1_000_000


def staged_files() -> list[str]:
    """List added or modified files in the index.

    Returns:
        Repo-relative paths.
    """
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    return [p for p in out.split("\0") if p]


def staged_size(path: str) -> int:
    """Return the size of the staged version of a file.

    Args:
        path: Repo-relative path.

    Returns:
        Size in bytes (0 when unknown).
    """
    res = subprocess.run(["git", "cat-file", "-s", f":{path}"], cwd=ROOT, capture_output=True, text=True, check=False)
    return int(res.stdout.strip() or 0) if res.returncode == 0 else 0


def problems(paths: list[str], max_bytes: int, block_data: bool = True) -> list[str]:
    """Find staged files that should not be committed.

    Args:
        paths: Staged repo-relative paths.
        max_bytes: Size limit for any file.
        block_data: Block data extensions outside the sample folders.

    Returns:
        Human-readable problem lines.
    """
    found = []
    for path in paths:
        size = staged_size(path)
        is_sample = path.startswith(SAMPLE_DIRS) and size <= SAMPLE_MAX_BYTES
        if block_data and Path(path).suffix.lower() in DATA_EXTENSIONS and not is_sample:
            found.append(f"{path}：資料檔不進 git，請放到 DATA_DIR（小型測試樣本放 tests/fixtures/，≤ 1 MB）")
        elif size > max_bytes:
            found.append(f"{path}：{size / 1_000_000:.1f} MB 超過 {max_bytes / 1_000_000:.0f} MB 上限")
    return found


def main() -> int:
    """Check the index and print problems.

    Returns:
        1 when a file should not be committed, otherwise 0.
    """
    quality = load_config(ROOT)["quality"]
    limit_mb = float(quality.get("max_commit_file_mb", 10))
    found = problems(staged_files(), int(limit_mb * 1_000_000), bool(quality.get("block_data_files", True)))
    for line in found:
        print(f"❌ {line}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
