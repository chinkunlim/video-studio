"""字幕：文字用讲稿（词汇表的「字幕显示」），时间用拼接时记录的每句位置，
句子里的细节时间用该句音档的 Whisper 逐字时间戳。一律转成繁体，无 BOM 的 UTF-8。

输出：
  subtitles_youtube.srt      YouTube 上传用
  subtitles_powerpoint.vtt   PowerPoint「插入字幕」用（没有编号、无 BOM）
  subtitles_vlc.srt / subtitles_vlc.ass   VLC 播放用（ASS 有字型和样式）
"""
import csv, difflib, re
from pathlib import Path

from .whisper import norm


def is_char(c):
    return c.isalnum()


def width(s):
    return sum(0.5 if c.isascii() else 1 for c in s if is_char(c))


def char_times(text, words):
    """讲稿每个字在音档里的 (开始, 结束)：跟 Whisper 的字对齐，对不上的字用前后内插"""
    ct = []
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


def split_line(text, ts, te, max_w):
    """一行讲稿 → 多条字幕：句号问号分号一定断；太长从逗号断；还太长从停顿最久处断"""
    pieces, idx = [], 0
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
    out = []
    for piece, start in pieces:
        out += _split_pause(piece, start, ts, te, max_w)
    return out


def _split_pause(piece, first, ts, te, max_w):
    if width(piece) <= max_w + 2:
        return [(piece, first)]
    pos, idx = [], first
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
    return _split_pause(piece[:end].strip(), first, ts, te, max_w) + \
        _split_pause(piece[end:].strip(), k + 1, ts, te, max_w)


def build_cues(lines, cfg):
    """lines: [{text, words, start, end, trim_start}] → [(开始, 结束, 文字)]"""
    sc = cfg["subtitle"]
    cues = []
    for ln in lines:
        ts, te = char_times(ln["text"], ln["words"])
        off = ln["start"] - ln["trim_start"]
        for piece, k0 in split_line(ln["text"], ts, te, sc["max_width"]):
            n = sum(1 for c in piece if is_char(c))
            if not n:
                continue
            s = max(ln["start"], ts[k0] + off) - sc["lead"]
            e = min(ln["end"], te[k0 + n - 1] + off) + sc["tail"]
            cues.append([s, e, piece])
    for k, c in enumerate(cues):                       # 不重叠、至少显示 min_duration
        nxt = cues[k + 1][0] if k + 1 < len(cues) else c[1] + 10
        c[1] = min(max(c[1], c[0] + sc["min_duration"]), nxt - 0.02)
        c[0] = max(0.0, c[0])
    return cues


def to_traditional(cues, cfg, fixes_path):
    from opencc import OpenCC
    cc = OpenCC(cfg["subtitle"]["opencc"])
    fixes = []
    if Path(fixes_path).exists():
        with open(fixes_path, encoding="utf-8") as f:
            fixes = [(r["wrong"], r["right"]) for r in csv.DictReader(f, delimiter="\t") if r.get("wrong")]
    out = []
    for s, e, t in cues:
        t = cc.convert(t)
        for wrong, right in fixes:
            t = t.replace(wrong, right)
        out.append((s, e, re.sub(r"[。，；：、]$", "", t)))
    return out


def _hms(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _ass_t(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_all(cues, out_dir, cfg, title):
    sc = cfg["subtitle"]
    srt = "".join(f"{k}\n{_hms(s, ',')} --> {_hms(e, ',')}\n{t}\n\n" for k, (s, e, t) in enumerate(cues, 1))
    vtt = "WEBVTT\n\n" + "".join(f"{_hms(s, '.')} --> {_hms(e, '.')}\n{t}\n\n" for s, e, t in cues)
    ass = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{sc['font']},{sc['font_size']},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "".join(f"Dialogue: 0,{_ass_t(s)},{_ass_t(e)},Default,,0,0,0,,{t}\n" for s, e, t in cues)
    files = {"subtitles_youtube.srt": srt, "subtitles_powerpoint.vtt": vtt,
             "subtitles_vlc.srt": srt, "subtitles_vlc.ass": ass}
    for name, text in files.items():
        (Path(out_dir) / name).write_text(text, encoding="utf-8")   # 无 BOM（PowerPoint 读不了 BOM）
    return list(files)
