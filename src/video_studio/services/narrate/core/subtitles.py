"""字幕：文字用讲稿（词汇表的「字幕显示」），时间用拼接时记录的每句位置，
句子里的细节时间用该句音档的 Whisper 逐字时间戳。一律转成繁体，无 BOM 的 UTF-8。

输出：
  subtitles_youtube.srt      YouTube 上传用
  subtitles_powerpoint.vtt   PowerPoint「插入字幕」用（没有编号、无 BOM）
  subtitles_vlc.srt / subtitles_vlc.ass   VLC 播放用（ASS 有字型和样式）
"""

from __future__ import annotations

import csv
import difflib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def is_char(c: str) -> bool:
    """判断是否为有效字元（字母或数字）。

    Args:
        c: 单一字元。

    Returns:
        若为字母或数字回传 True。
    """
    return c.isalnum()


def width(s: str) -> float:
    """计算字串排版宽度（半形 0.5，全形 1.0）。

    Args:
        s: 待测字串。

    Returns:
        总显示宽度。
    """
    return sum(0.5 if c.isascii() else 1.0 for c in s if is_char(c))


def char_times(text: str, words: list[tuple[str, float, float]]) -> tuple[list[float], list[float]]:
    """讲稿每个字在音档里的 (开始, 结束)：跟 Whisper 的字对齐，对不上的字用前后内插。

    Args:
        text: 讲稿文字。
        words: Whisper 词时间戳清单。

    Returns:
        (开始时间列表, 结束时间列表)。
    """
    ct: list[tuple[str, float, float]] = []
    for w, s, e in words:
        cs = [c.lower() for c in w if is_char(c)]
        for k, c in enumerate(cs):
            ct.append((c, s + (e - s) * k / len(cs), s + (e - s) * (k + 1) / len(cs)))
    chars = [c.lower() for c in text if is_char(c)]
    n = len(chars)
    ts, te, ok = [0.0] * n, [0.0] * n, [False] * n
    sm = difflib.SequenceMatcher(None, "".join(chars), "".join(c for c, _, _ in ct), autojunk=False)
    for i, j, size in sm.get_matching_blocks():
        for k in range(size):
            ts[i + k], te[i + k], ok[i + k] = ct[j + k][1], ct[j + k][2], True
    known = [k for k in range(n) if ok[k]]
    first = ct[0][1] if ct else 0.0
    last = ct[-1][2] if ct else 0.0
    for k in range(n):
        if not ok[k]:
            prev = max((x for x in known if x < k), default=None)
            nxt = min((x for x in known if x > k), default=None)
            a = te[prev] if prev is not None else first
            b = ts[nxt] if nxt is not None else last
            lo = prev if prev is not None else -1
            hi = nxt if nxt is not None else n
            ts[k] = te[k] = a + (b - a) * (k - lo) / (hi - lo)
    return ts, te


def _split_pause(
    piece: str,
    first: int,
    ts: list[float],
    te: list[float],
    max_w: float,
) -> list[tuple[str, int]]:
    """根据字元间隔停顿细切长句。

    Args:
        piece: 片段字串。
        first: 起始字元索引。
        ts: 字元开始时间。
        te: 字元结束时间。
        max_w: 单行最大排版宽度。

    Returns:
        (片段文字, 起始索引) 列表。
    """
    if width(piece) <= max_w + 2:
        return [(piece, first)]
    pos: list[tuple[int, int]] = []
    idx = first
    for m in re.finditer(r"[A-Za-z0-9]+|.", piece):
        cnt = sum(1 for c in m.group() if is_char(c))
        idx += cnt
        if cnt:
            pos.append((m.end(), idx - 1))
    total, best = width(piece), None
    for end, k in pos[:-1]:
        if 0.3 * total <= width(piece[:end]) <= 0.7 * total and k + 1 < len(ts):
            gap = ts[k + 1] - te[k]
            if best is None or gap > best[0]:
                best = (gap, end, k)
    if best is None:
        return [(piece, first)]
    _, end, k = best
    return _split_pause(piece[:end].strip(), first, ts, te, max_w) + _split_pause(
        piece[end:].strip(), k + 1, ts, te, max_w
    )


def split_line(text: str, ts: list[float], te: list[float], max_w: float) -> list[tuple[str, int]]:
    """一行讲稿 → 多条字幕：句号问号分号一定断；太长从逗号断；还太长从停顿最久处断。

    Args:
        text: 讲稿单行原文。
        ts: 字元开始时间列表。
        te: 字元结束时间列表。
        max_w: 单行最大排版宽度。

    Returns:
        (字幕分句文字, 起始字元索引) 列表。
    """
    pieces: list[tuple[str, int]] = []
    idx = 0
    for sent in re.findall(r"[^。！？；]+[。！？；]?", text):
        cur, cur_start = "", idx
        for part in re.findall(r"[^，、：]+[，、：]?", sent):
            n = sum(1 for c in part if is_char(c))
            if cur and width(cur + part) > max_w:
                pieces.append((cur.strip(), cur_start))
                cur, cur_start = part, idx
            else:
                cur += part
            idx += n
        if cur.strip():
            pieces.append((cur.strip(), cur_start))
    out: list[tuple[str, int]] = []
    for piece, start in pieces:
        out.extend(_split_pause(piece, start, ts, te, max_w))
    return out


def build_cues(lines: list[dict[str, Any]], cfg: dict[str, Any]) -> list[list[Any]]:
    """lines: [{text, words, start, end, trim_start}] → [[开始, 结束, 文字]]。

    Args:
        lines: 讲稿行时间及内容列表。
        cfg: 设定字典。

    Returns:
        字幕 cue 列表。
    """
    sc = cfg.get("subtitle", {})
    max_w = float(sc.get("max_width", 18.0))
    lead = float(sc.get("lead", 0.05))
    tail = float(sc.get("tail", 0.08))
    min_dur = float(sc.get("min_duration", 0.8))
    cues: list[list[Any]] = []
    for ln in lines:
        ts, te = char_times(str(ln["text"]), ln["words"])
        off = float(ln["start"]) - float(ln["trim_start"])
        for piece, k0 in split_line(str(ln["text"]), ts, te, max_w):
            n = sum(1 for c in piece if is_char(c))
            if not n:
                continue
            s = max(float(ln["start"]), ts[k0] + off) - lead
            e = min(float(ln["end"]), te[k0 + n - 1] + off) + tail
            cues.append([s, e, piece])
    for k, c in enumerate(cues):  # 不重叠、至少显示 min_duration
        nxt = cues[k + 1][0] if k + 1 < len(cues) else c[1] + 10
        c[1] = min(max(c[1], c[0] + min_dur), nxt - 0.02)
        c[0] = max(0.0, c[0])
    return cues


def to_traditional(
    cues: list[list[Any]],
    cfg: dict[str, Any],
    fixes_path: Path | str,
) -> list[tuple[float, float, str]]:
    """将字幕文字转为台湾繁体中文并套用自订修正表。

    Args:
        cues: 原始字幕列表 [[start, end, text], ...]。
        cfg: 设定字典。
        fixes_path: traditional_fixes.tsv 路径。

    Returns:
        转换后的字幕三元组列表 [(start, end, text), ...]。
    """
    from opencc import OpenCC

    opencc_mode = cfg.get("subtitle", {}).get("opencc", "s2tw")
    cc = OpenCC(opencc_mode)
    fixes: list[tuple[str, str]] = []
    f_path = Path(fixes_path)
    if f_path.exists():
        with open(f_path, encoding="utf-8") as f:
            fixes = [(r["wrong"], r["right"]) for r in csv.DictReader(f, delimiter="\t") if r.get("wrong")]
    out: list[tuple[float, float, str]] = []
    for s, e, t in cues:
        converted = cc.convert(str(t))
        for wrong, right in fixes:
            converted = converted.replace(wrong, right)
        out.append((float(s), float(e), re.sub(r"[。，；：、]$", "", converted)))
    return out


def _hms(t: float, sep: str) -> str:
    """将秒数转为 HH:MM:SS,mmm 格式。

    Args:
        t: 秒数。
        sep: 毫秒分隔符（',' 或 '.'）。

    Returns:
        格式化时间字串。
    """
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _ass_t(t: float) -> str:
    """将秒数转为 ASS 时间戳格式 H:MM:SS.cs。

    Args:
        t: 秒数。

    Returns:
        ASS 时间字串。
    """
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_all(
    cues: list[tuple[float, float, str]],
    out_dir: Path | str,
    cfg: dict[str, Any],
    title: str,
) -> list[str]:
    """写出 SRT, VTT, ASS 字幕档案至成品资料夹。

    Args:
        cues: 繁体字幕列表。
        out_dir: 输出目录。
        cfg: 设定字典。
        title: 简报/影片标题。

    Returns:
        产出的字幕档案名称列表。
    """
    sc = cfg.get("subtitle", {})
    font = sc.get("font", "PingFang TC")
    font_size = sc.get("font_size", 28)
    srt = "".join(f"{k}\n{_hms(s, ',')} --> {_hms(e, ',')}\n{t}\n\n" for k, (s, e, t) in enumerate(cues, 1))
    vtt = "WEBVTT\n\n" + "".join(f"{_hms(s, '.')} --> {_hms(e, '.')}\n{t}\n\n" for s, e, t in cues)
    ass_format_line = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    ass_style_line = (
        f"Style: Default,{font},{font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,60,1\n"
    )
    ass = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
{ass_format_line}{ass_style_line}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "".join(f"Dialogue: 0,{_ass_t(s)},{_ass_t(e)},Default,,0,0,0,,{t}\n" for s, e, t in cues)
    files = {
        "subtitles_youtube.srt": srt,
        "subtitles_powerpoint.vtt": vtt,
        "subtitles_vlc.srt": srt,
        "subtitles_vlc.ass": ass,
    }
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_path / name).write_text(text, encoding="utf-8")  # 无 BOM（PowerPoint 读不了 BOM）
    return list(files)
