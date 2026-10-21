"""画面上的文字：底部重点提示栏、烧进画面的字幕。用 Pillow 画（这台的 ffmpeg 没有 drawtext / libass）。"""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=16)
def font(path, index, size):
    return ImageFont.truetype(path, size, index=index)


def _fit_lines(draw, text, fnt, max_w):
    """太宽就从中间断成两行（中文没有空格，逐字找断点）"""
    if draw.textlength(text, font=fnt) <= max_w:
        return [text]
    best = None
    for k in range(1, len(text)):
        a, b = text[:k], text[k:]
        w = max(draw.textlength(a, font=fnt), draw.textlength(b, font=fnt))
        if best is None or w < best[0]:
            best = (w, a, b)
    return [best[1], best[2]]


def to_traditional(text, fixes_path=None):
    """中文一律繁体（OpenCC 台湾标准，再套用 narrate/traditional_fixes.tsv）"""
    from opencc import OpenCC
    out = OpenCC("s2tw").convert(text)
    if fixes_path:
        import csv
        from pathlib import Path
        if Path(fixes_path).exists():
            with open(fixes_path, encoding="utf-8") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("wrong"):
                        out = out.replace(r["wrong"], r["right"])
    return out


FONT_DIRS = ["/System/Library/Fonts", "/Library/Fonts", str(__import__("pathlib").Path.home() / "Library/Fonts"),
             "/System/Library/AssetsV2"]


@lru_cache(maxsize=1)
def _font_index():
    """系统字型档：正规化的档名 → 路径（例如 weibeitcbold → …/WeibeiTC-Bold.otf）"""
    import os
    import re
    idx = {}
    for d in FONT_DIRS:
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    idx.setdefault(re.sub(r"[^a-z0-9]", "", f.rsplit(".", 1)[0].lower()), os.path.join(root, f))
    return idx


def find_font(name, cfg):
    """依 pptx 的字型名称找系统字型档；找不到就用 config 的预设字型（黑体-繁）"""
    import re
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    path = _font_index().get(key) if key else None
    return (path, 0) if path else (cfg["font"]["path"], cfg["font"]["index"])


def _tick(d, x, cy, fs, color):
    d.line([(x, cy), (x + fs * 0.3, cy + fs * 0.3), (x + fs * 0.8, cy - fs * 0.35)],
           fill=color, width=max(3, fs // 9), joint="curve")


def callout(cfg, text, size):
    """底部重点提示栏（RGBA），没有文字就回传 None。文字会转成繁体；用换行分开的每一段各有一个 ✓。
    样式来自 cfg["callout"]（scenes.toml 的 [style] 会先换算成像素覆盖进来）。"""
    if not text:
        return None
    text = to_traditional(text, cfg.get("fixes_path"))
    c, f = cfg["callout"], cfg["font"]
    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = H - c["height"]
    d.rectangle([0, top, W, H], fill=hex_rgb(c["color"]) + (255,))
    fs = int(c["font_size"])
    fnt = font(f["path"], f["index"], fs)
    color = hex_rgb(c["text_color"]) + (255,)
    prefix = c.get("prefix", "")
    tick = prefix.strip() == "✓"               # 黑体-繁没有 ✓ 这个字，改用线条画
    bullet_x = c.get("bullet_x", 80)
    text_x = c.get("text_x", bullet_x + int(fs * 1.2) if tick else bullet_x)
    rows = []                                  # (这一行是不是段落开头, 文字)
    for para in [p for p in text.split("\n") if p.strip()]:
        label = para if tick or not prefix else prefix + para
        for k, line in enumerate(_fit_lines(d, label, fnt, W - text_x - 60)):
            rows.append((k == 0, line))
    lh = fs * 1.3
    y = top + c["height"] / 2 - lh * len(rows) / 2
    for first, line in rows:
        if tick and first:
            _tick(d, bullet_x, y + lh / 2 - fs * 0.05, fs, color)
        d.text((text_x, y + (lh - fs) / 2 - fs * 0.1), line, font=fnt, fill=color)
        y += lh
    return img


def frame(size, inset, color):
    """外框：四边内缩 inset = [左, 上, 右, 下]（占画面比例）以外的地方填上颜色"""
    W, H = size
    img = Image.new("RGBA", size, hex_rgb(color) + (255,))
    l, t, r, b = inset
    ImageDraw.Draw(img).rectangle([round(l * W), round(t * H), round(W - r * W) - 1, round(H - b * H) - 1],
                                  fill=(0, 0, 0, 0))
    return img


def overlay_text(cfg, text, box, font_size, font_name, color, size):
    """画面上的大字（例如结尾的「匯報完畢」）：box = [x, y, 宽, 高] 占画面比例，置中；字级是占画面高度的比例"""
    if not text:
        return None
    text = to_traditional(text, cfg.get("fixes_path"))
    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    path, index = find_font(font_name, cfg)
    fnt = font(path, index, max(8, int(font_size * H)))
    x, y, w, h = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    lines = text.split("\n")
    lh = font_size * H * 1.2
    ty = y + h / 2 - lh * len(lines) / 2
    for line in lines:
        bb = d.textbbox((0, 0), line, font=fnt)
        d.text((x + w / 2 - (bb[2] - bb[0]) / 2 - bb[0], ty + (lh - (bb[3] - bb[1])) / 2 - bb[1]), line,
               font=fnt, fill=hex_rgb(color) + (255,))
        ty += lh
    return img


def subtitle(cfg, text, size, bottom_reserved=0):
    """一条字幕（RGBA）：白字黑边，置中，在 bottom_reserved（例如提示栏）上方"""
    s, f = cfg["subtitle"], cfg["font"]
    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = font(f["path"], f["index"], s["font_size"])
    lines = _fit_lines(d, text, fnt, W - 200)
    lh = s["font_size"] * 1.3
    y = H - bottom_reserved - s["margin_bottom"] - lh * len(lines)
    for line in lines:
        w = d.textlength(line, font=fnt)
        d.text(((W - w) / 2, y), line, font=fnt, fill=hex_rgb(s["color"]) + (255,),
               stroke_width=s["stroke_width"], stroke_fill=hex_rgb(s["stroke_color"]) + (255,))
        y += lh
    return img
