"""辅助检查：PPTX、cues.tsv 与 brief.md 格式校验。"""

from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from typing import Protocol


class ReportSink(Protocol):
    """检查报告记录介面。"""

    def err(self, where: str, msg: str) -> None:
        """记录错误讯息。

        Args:
            where: 错误发生位置。
            msg: 错误说明文字。
        """
        ...

    def note(self, msg: str) -> None:
        """记录提示讯息。

        Args:
            msg: 提示说明文字。
        """
        ...


BRIEF_HEADINGS = ("主题", "观众", "长度", "用途", "语气", "一定要讲的重点", "资料来源")


def pptx_info(path: Path) -> dict[str, int]:
    """页数，以及有几个会自动播放的内嵌音档。

    Args:
        path: PPTX 档案路径。

    Returns:
        包含 pages 与 media_calls 次数的字典。
    """
    with zipfile.ZipFile(path) as z:
        slides = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        media_calls = sum(
            z.read(n).decode("utf-8", "ignore").count('presetClass="mediacall"') for n in slides
        )
        return {"pages": len(slides), "media_calls": media_calls}


def check_pptx(path: Path, script_slides: list[int], r: ReportSink) -> int:
    """检查 PPTX 是否有效并与讲稿比对页数。

    Args:
        path: PPTX 档案路径。
        script_slides: 讲稿投影片页码清册。
        r: 报告收集物件。

    Returns:
        PPTX 总页数。
    """
    where = f"input/{path.name}"
    try:
        info = pptx_info(path)
    except zipfile.BadZipFile:
        r.err(where, "不是有效的 pptx 档案")
        return 0
    n = info["pages"]
    if script_slides and n != len(script_slides):
        r.err(where, f"pptx 有 {n} 页，讲稿有 {len(script_slides)} 页；两者要一样多")
    if info["media_calls"]:
        r.note(f"pptx 有 {info['media_calls']} 个内嵌音档会自动播放；汇出时会先移除")
    return n


def _sec(t: str) -> float:
    """时间字串转秒数。

    Args:
        t: 秒数字串或「分:秒」字串。

    Returns:
        浮点数秒数。
    """
    t = t.strip()
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    return float(t)


def check_cues(path: Path, n_lines: int, r: ReportSink) -> None:
    """检查配音时间标记 cues.tsv。

    Args:
        path: cues.tsv 路径。
        n_lines: 讲稿总句数。
        r: 报告收集物件。
    """
    where = f"input/{path.name}"
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows or rows[0][:2] != ["line", "start"]:
        r.err(where, "第 1 行（表头）要是 line、start、note，用 Tab 分隔")
        return
    prev = -1.0
    for i, row in enumerate(rows[1:], 2):
        if not row or not row[0].strip():
            continue
        try:
            no, t = int(row[0]), _sec(row[1])
        except (ValueError, IndexError):
            r.err(where, f"第 {i} 行：line 要是整数、start 要是秒数或「分:秒」")
            continue
        if t <= prev:
            r.err(where, f"第 {i} 行：时间 {row[1]} 没有比上一行晚")
        prev = t
        if n_lines and not 1 <= no <= n_lines:
            r.err(where, f"第 {i} 行：line = {no}，讲稿只有 {n_lines} 句")


def check_brief(path: Path, r: ReportSink) -> None:
    """检查大纲 brief.md 是否包含必要标题。

    Args:
        path: brief.md 路径。
        r: 报告收集物件。
    """
    where = f"input/{path.name}"
    text = path.read_text(encoding="utf-8")
    heads = {m.group(1).strip(): m.end() for m in re.finditer(r"^##\s*(.+)$", text, re.M)}
    for h in BRIEF_HEADINGS:
        if h not in heads:
            r.err(where, f"少了「## {h}」这一节")
