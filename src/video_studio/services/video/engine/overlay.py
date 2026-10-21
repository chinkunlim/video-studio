"""画面上的文字：底部重点提示栏、烧进画面的字幕。用 Pillow 画（这台的 ffmpeg 没有 drawtext / libass）。"""

from __future__ import annotations

import csv
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def hex_rgb(h: str) -> tuple[int, int, int]:
    """16 进位色码转 RGB 三元组。

    Args:
        h: 色码字串（例如 '#D9692E' 或 'D9692E'）。

    Returns:
        (R, G, B) 整数元组。
    """
    clean_hex = h.lstrip("#")
    if len(clean_hex) < 6:
        clean_hex = clean_hex.ljust(6, "0")
    return tuple(int(clean_hex[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@lru_cache(maxsize=16)
def font(path: str, index: int, size: int) -> ImageFont.FreeTypeFont:
    """快取载入字型物件。

    Args:
        path: 字型档案路径。
        index: TTC 字型集合索引。
        size: 字级像素。

    Returns:
        Pillow FreeTypeFont 物件。
    """
    return ImageFont.truetype(path, size, index=index)


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    """太宽就从中间断成两行（中文没有空格，逐字找断点）。

    Args:
        draw: Pillow 绘图物件。
        text: 待排版文字。
        fnt: 使用字型。
        max_w: 最大行宽限制。

    Returns:
        断行后的文字列表。
    """
    if draw.textlength(text, font=fnt) <= max_w:
        return [text]
    best: tuple[float, str, str] | None = None
    for k in range(1, len(text)):
        a, b = text[:k], text[k:]
        w = max(draw.textlength(a, font=fnt), draw.textlength(b, font=fnt))
        if best is None or w < best[0]:
            best = (w, a, b)
    return [best[1], best[2]] if best else [text]


def to_traditional(text: str, fixes_path: Path | str | None = None) -> str:
    """中文一律繁体（OpenCC 台湾标准，再套用 narrate/traditional_fixes.tsv）。

    Args:
        text: 简体或混合中文文字。
        fixes_path: traditional_fixes.tsv 路径。

    Returns:
        繁体中文文字。
    """
    from opencc import OpenCC

    out = OpenCC("s2tw").convert(text)
    if fixes_path and Path(fixes_path).exists():
        with open(fixes_path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("wrong"):
                    out = out.replace(r["wrong"], r.get("right", ""))
    return str(out)


FONT_DIRS = [
    "/System/Library/Fonts",
    "/Library/Fonts",
    str(Path.home() / "Library/Fonts"),
    "/System/Library/AssetsV2",
]


@lru_cache(maxsize=1)
def _font_index() -> dict[str, str]:
    """系统字型档：正规化的档名 → 路径。

    Returns:
        字型名称与绝对路径对应字典。
    """
    idx: dict[str, str] = {}
    for d in FONT_DIRS:
        if not os.path.exists(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    key = re.sub(r"[^a-z0-9]", "", f.rsplit(".", 1)[0].lower())
                    idx.setdefault(key, os.path.join(root, f))
    return idx


def find_font(name: str, cfg: dict[str, Any]) -> tuple[str, int]:
    """依 pptx 的字型名称找系统字型档；找不到就用 config 的预设字型（黑体-繁）。

    Args:
        name: 目标字型名称。
        cfg: 设定字典。

    Returns:
        (字型档案路径, 集合索引) 元组。
    """
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    path = _font_index().get(key) if key else None
    default_font = cfg.get("font", {})
    return (
        (path, 0)
        if path
        else (
            str(default_font.get("path", "/System/Library/Fonts/STHeiti Light.ttc")),
            int(default_font.get("index", 1)),
        )
    )


def _tick(d: ImageDraw.ImageDraw, x: float, cy: float, fs: int, color: tuple[int, int, int, int]) -> None:
    """绘制提示栏打勾符号。

    Args:
        d: 绘图物件。
        x: X 坐标。
        cy: Y 中心点。
        fs: 字级。
        color: RGBA 颜色。
    """
    d.line(
        [(x, cy), (x + fs * 0.3, cy + fs * 0.3), (x + fs * 0.8, cy - fs * 0.35)],
        fill=color,
        width=max(3, fs // 9),
        joint="curve",
    )


def callout(cfg: dict[str, Any], text: str, size: tuple[int, int]) -> Image.Image | None:
    """底部重点提示栏（RGBA），没有文字就回传 None。

    Args:
        cfg: 设定字典。
        text: 提示栏多行文字。
        size: 画面 (宽, 高) 像素。

    Returns:
        包含提示栏的 RGBA 透明图片，或 None。
    """
    if not text:
        return None
    text = to_traditional(text, cfg.get("fixes_path"))
    c = cfg.get("callout", {})
    f = cfg.get("font", {})
    width, height = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c_height = int(c.get("height", 140))
    top = height - c_height
    d.rectangle([0, top, width, height], fill=hex_rgb(str(c.get("color", "#D9692E"))) + (255,))
    fs = int(c.get("font_size", 34))
    fnt = font(
        str(f.get("path", "/System/Library/Fonts/STHeiti Light.ttc")),
        int(f.get("index", 1)),
        fs,
    )
    color = hex_rgb(str(c.get("text_color", "#FFFFFF"))) + (255,)
    prefix = str(c.get("prefix", ""))
    tick = prefix.strip() == "✓"
    bullet_x = float(c.get("bullet_x", 80))
    text_x = float(c.get("text_x", bullet_x + int(fs * 1.2) if tick else bullet_x))
    rows: list[tuple[bool, str]] = []
    for para in [p for p in text.split("\n") if p.strip()]:
        label = para if tick or not prefix else prefix + para
        for k, line in enumerate(_fit_lines(d, label, fnt, width - text_x - 60)):
            rows.append((k == 0, line))
    lh = fs * 1.3
    y = top + c_height / 2.0 - lh * len(rows) / 2.0
    for first, line in rows:
        if tick and first:
            _tick(d, bullet_x, y + lh / 2.0 - fs * 0.05, fs, color)
        d.text((text_x, y + (lh - fs) / 2.0 - fs * 0.1), line, font=fnt, fill=color)
        y += lh
    return img


def frame(size: tuple[int, int], inset: list[float], color: str) -> Image.Image:
    """外框：四边内缩 inset = [左, 上, 右, 下]（占画面比例）以外的地方填上颜色。

    Args:
        size: 画面 (宽, 高) 像素。
        inset: [左, 上, 右, 下] 内缩比例。
        color: 外框色码。

    Returns:
        包含边框的 RGBA 图片。
    """
    width, height = size
    img = Image.new("RGBA", size, hex_rgb(color) + (255,))
    left, top, right, bottom = inset
    ImageDraw.Draw(img).rectangle(
        [
            round(left * width),
            round(top * height),
            round(width - right * width) - 1,
            round(height - bottom * height) - 1,
        ],
        fill=(0, 0, 0, 0),
    )
    return img


def overlay_text(
    cfg: dict[str, Any],
    text: str,
    box: list[float],
    font_size: float,
    font_name: str,
    color: str,
    size: tuple[int, int],
) -> Image.Image | None:
    """画面上的大字（例如结尾的「匯報完畢」）。

    Args:
        cfg: 设定字典。
        text: 画面文字。
        box: [x, y, 宽, 高] 占画面比例。
        font_size: 字级占画面高度比例。
        font_name: 字体名称。
        color: 色码。
        size: 画面总尺寸。

    Returns:
        图层图片或 None。
    """
    if not text:
        return None
    text = to_traditional(text, cfg.get("fixes_path"))
    width, height = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    path, index = find_font(font_name, cfg)
    fnt = font(path, index, max(8, int(font_size * height)))
    x, y, w, h = box[0] * width, box[1] * height, box[2] * width, box[3] * height
    lines = text.split("\n")
    lh = font_size * height * 1.2
    ty = y + h / 2.0 - lh * len(lines) / 2.0
    for line in lines:
        bb = d.textbbox((0, 0), line, font=fnt)
        d.text(
            (
                x + w / 2.0 - (bb[2] - bb[0]) / 2.0 - bb[0],
                ty + (lh - (bb[3] - bb[1])) / 2.0 - bb[1],
            ),
            line,
            font=fnt,
            fill=hex_rgb(color) + (255,),
        )
        ty += lh
    return img


def subtitle(
    cfg: dict[str, Any],
    text: str,
    size: tuple[int, int],
    bottom_reserved: int = 0,
) -> Image.Image:
    """绘制单一字幕条（白字黑边置中）。

    Args:
        cfg: 设定字典。
        text: 字幕文字。
        size: 画面总尺寸。
        bottom_reserved: 底部避让高度。

    Returns:
        包含字幕的透明 RGBA 图片。
    """
    s = cfg.get("subtitle", {})
    f = cfg.get("font", {})
    width, height = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = int(s.get("font_size", 34))
    fnt = font(
        str(f.get("path", "/System/Library/Fonts/STHeiti Light.ttc")),
        int(f.get("index", 1)),
        fs,
    )
    lines = _fit_lines(d, text, fnt, width - 200)
    lh = fs * 1.3
    margin_bottom = int(s.get("margin_bottom", 40))
    y = height - bottom_reserved - margin_bottom - lh * len(lines)
    for line in lines:
        w = d.textlength(line, font=fnt)
        d.text(
            ((width - w) / 2.0, y),
            line,
            font=fnt,
            fill=hex_rgb(str(s.get("color", "#FFFFFF"))) + (255,),
            stroke_width=int(s.get("stroke_width", 3)),
            stroke_fill=hex_rgb(str(s.get("stroke_color", "#000000"))) + (255,),
        )
        y += lh
    return img
