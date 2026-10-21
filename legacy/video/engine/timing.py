"""每一页（每一幕）在配音里的时间：先配音、量时长，再决定每页多长（PDF 第三节）。"""
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

# 直接载入 narrate 的讲稿解析器，确保每一行跟配音一一对应
_spec = importlib.util.spec_from_file_location(
    "narrate_script", Path(__file__).resolve().parents[2] / "narrate" / "core" / "script.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
parse = _mod.parse


@dataclass
class Slide:
    slide: int
    start: float
    end: float
    lines: list = field(default_factory=list)      # [{no, start, end, click}]

    @property
    def duration(self):
        return self.end - self.start

    @property
    def clicks(self):
        """这一页每个 [click] 在页内第几秒发生"""
        return [round(ln["start"] - self.start, 3) for ln in self.lines if ln["click"]]


def latest_version(out_dir, version=None):
    """output/vN：有 narration.wav 和 timeline.json 的最新版本（或指定版本）"""
    out = Path(out_dir)
    if version:
        v = out / version
        if not (v / "narration.wav").exists():
            raise FileNotFoundError(f"{v} 里没有 narration.wav")
        return v
    vs = sorted((d for d in out.glob("v*") if (d / "narration.wav").exists() and (d / "timeline.json").exists()),
                key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else -1)
    if not vs:
        raise FileNotFoundError(f"{out} 里还没有配音。请先执行 narrate.py build。")
    return vs[-1]


def slides(version_dir, narration_duration, tail=1.0):
    """依 timeline.json 和当次的 script.md，算出每一页的起止时间"""
    v = Path(version_dir)
    timeline = json.loads((v / "timeline.json").read_text(encoding="utf-8"))
    lines = parse((v / "script.md").read_text(encoding="utf-8"))
    if len(lines) != len(timeline):
        raise ValueError(f"script.md 有 {len(lines)} 行，timeline.json 有 {len(timeline)} 行，对不上")
    out = []
    for ln, tl in zip(lines, timeline):
        if not out or out[-1].slide != ln.slide:
            out.append(Slide(ln.slide, tl["start"], 0.0))
        out[-1].lines.append({"no": ln.no, "start": tl["start"], "end": tl["end"], "click": ln.click})
    out[0].start = 0.0
    for a, b in zip(out, out[1:]):
        a.end = b.start
    out[-1].end = narration_duration + tail
    return out
