"""每一页（每一幕）在配音里的时间：先配音、量时长，再决定每页多长（PDF 第三节）。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_studio.services.narrate.core.script import parse

logger = logging.getLogger(__name__)


@dataclass
class Slide:
    """每一页投影片对应的配音与时间区段。"""

    slide: int
    start: float
    end: float
    lines: list[dict[str, Any]] = field(default_factory=list)  # [{no, start, end, click}]

    @property
    def duration(self) -> float:
        """本页总秒数。

        Returns:
            秒数浮点数。
        """
        return self.end - self.start

    @property
    def clicks(self) -> list[float]:
        """这一页每个 [click] 在页内第几秒发生。

        Returns:
            点击动画发生时间点（相对本页起始秒数）。
        """
        return [round(float(ln["start"]) - self.start, 3) for ln in self.lines if ln.get("click")]


def latest_version(out_dir: Path | str, version: str | None = None) -> Path:
    """寻找 output/vN：有 narration.wav 和 timeline.json 的最新版本（或指定版本）。

    Args:
        out_dir: output/ 资料夹路径。
        version: 指定版本名称（如 'v1'）。

    Returns:
        版本资料夹 Path。

    Raises:
        FileNotFoundError: 找不到合格版本。
    """
    out = Path(out_dir)
    if version:
        v = out / version
        if not (v / "narration.wav").exists():
            raise FileNotFoundError(f"{v} 里没有 narration.wav")
        return v
    vs = sorted(
        (d for d in out.glob("v*") if (d / "narration.wav").exists() and (d / "timeline.json").exists()),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else -1,
    )
    if not vs:
        raise FileNotFoundError(f"{out} 里还没有配音。请先执行 narrate.py build。")
    return vs[-1]


def slides(version_dir: Path | str, narration_duration: float, tail: float = 1.0) -> list[Slide]:
    """依 timeline.json 和当次的 script.md，算出每一页的起止时间。

    Args:
        version_dir: 版本输出目录。
        narration_duration: 配音总长度（秒）。
        tail: 结尾预留时间。

    Returns:
        Slide 清单。
    """
    v = Path(version_dir)
    timeline: list[dict[str, Any]] = json.loads((v / "timeline.json").read_text(encoding="utf-8"))
    lines = parse((v / "script.md").read_text(encoding="utf-8"))
    if len(lines) != len(timeline):
        raise ValueError(f"script.md 有 {len(lines)} 行，timeline.json 有 {len(timeline)} 行，对不上")
    out: list[Slide] = []
    for ln, tl in zip(lines, timeline, strict=False):
        if not out or out[-1].slide != ln.slide:
            out.append(Slide(ln.slide, float(tl["start"]), 0.0))
        out[-1].lines.append(
            {
                "no": ln.no,
                "start": float(tl["start"]),
                "end": float(tl["end"]),
                "click": ln.click,
            }
        )
    out[0].start = 0.0
    for a, b in zip(out, out[1:], strict=False):
        a.end = b.start
    out[-1].end = narration_duration + tail
    return out
