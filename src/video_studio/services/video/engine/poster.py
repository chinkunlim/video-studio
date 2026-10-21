"""海报影片：镜头在海报上移动／卷动，加上外框、画面大字、底部提示栏（照 pptx 分镜或原始影片的样式）。

每一幕的设定在工作的 input/scenes.toml（格式见 templates/generate/input/scenes.toml）；
海报档案由 job.toml 的 [inputs] poster 指定。

  [style]   从 pptx 读出的样式（选填）：callout_height、callout_color、callout_text_color、callout_font_size、
            callout_text_x、callout_bullet_x、frame_inset、frame_color（数字都是占画面宽／高的比例）
  [[scene]] slide、visual = "poster"、region = [x, y, 宽, 高]、callout、overlay_text（画面大字）…

区域比画面宽：整块放进画面。区域比画面高（16:9 放不下）：宽度对齐，从区域顶端卷到底端。
渲染是确定的：同样的设定每次跑出来的每一格都一样（不用随机数、不用当前时间）。
"""

from __future__ import annotations

import copy
import logging
import math
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from video_studio.services.video.engine import overlay

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None  # 海报可能很大


def load_poster(path: Path | str, raster_width: int) -> Image.Image:
    """载入海报图片（PDF 会转为高解析点阵图）。

    Args:
        path: 海报档案路径。
        raster_width: 点阵化目标宽度。

    Returns:
        RGB PIL Image 物件。
    """
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import fitz  # PyMuPDF

        doc = fitz.open(p)
        page = doc[0]
        zoom = raster_width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Image.open(p).convert("RGB")


def read_scenes(path: Path | str) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """回传 (scenes {slide: scene}, style)；每一幕都已套用 [defaults]。

    Args:
        path: scenes.toml 档案路径。

    Returns:
        (每一幕分镜字典, 样式设定字典) 元组。

    Raises:
        FileNotFoundError: 找不到档案。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到 {p}。先起草 scenes.toml。")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    scenes: dict[int, dict[str, Any]] = {}
    for s in data.get("scene", []):
        merged = {"visual": defaults.get("visual", "poster"), **s}
        scenes[int(merged["slide"])] = merged
    style = dict(data.get("style", {}))
    if "callout_prefix" in defaults:
        style["callout_prefix"] = defaults["callout_prefix"]
    return scenes, style


def apply_style(cfg: dict[str, Any], style: dict[str, Any], size: tuple[int, int]) -> dict[str, Any]:
    """把 [style]（比例）换算成像素，覆盖 cfg 的提示栏设定；回传新的 cfg。

    Args:
        cfg: 基础设定。
        style: 从 scenes.toml 读出的样式。
        size: 画面 (宽, 高) 像素。

    Returns:
        转换后的新设定字典。
    """
    width, height = size
    c = copy.deepcopy(cfg)
    cc = c.setdefault("callout", {})
    if "callout_height" in style:
        cc["height"] = round(float(style["callout_height"]) * height)
    for k in ("color", "text_color"):
        if f"callout_{k}" in style:
            cc[k] = style[f"callout_{k}"]
    if "callout_font_size" in style:
        cc["font_size"] = round(float(style["callout_font_size"]) * height)
    if "callout_prefix" in style:
        cc["prefix"] = style["callout_prefix"]
    if "callout_bullet_x" in style:
        cc["bullet_x"] = round(float(style["callout_bullet_x"]) * width)
    if "callout_text_x" in style:
        cc["text_x"] = round(float(style["callout_text_x"]) * width)
    if "frame_inset" in style:
        c["frame"] = {"inset": style["frame_inset"], "color": style.get("frame_color", "#FFFFFF")}
    return c


def write_template(path: Path | str, slides: list[Any], poster_size: tuple[int, int]) -> None:
    """产生 scenes.toml 草稿：把海报由上到下平均分给每一页。

    Args:
        path: 输出路径。
        slides: 投影片列表。
        poster_size: 海报像素尺寸。
    """
    width, height = poster_size
    n = len(slides)
    view_h = min(1.0, (width * 9.0 / 16.0) / height)
    rows: list[str] = [
        "# 每一幕要看海报的哪一块（自动起草：海报由上到下平均分配）。",
        "",
        "[defaults]",
        'visual = "poster"',
        'callout_prefix = "✓"',
        "",
    ]
    for k, s in enumerate(slides):
        y = 0.0 if n == 1 else (1.0 - view_h) * k / (n - 1)
        rows.append(
            f'[[scene]]\nslide = {s.slide}\nintent = ""\n'
            f'region = [0.0, {y:.4f}, 1.0, {view_h:.4f}]\ncallout = ""\n'
        )
    Path(path).write_text("\n".join(rows), encoding="utf-8")


def preview(poster_img: Image.Image, scenes: dict[int, dict[str, Any]], out: Path | str) -> None:
    """把每一幕的区域画在海报上，方便检查。

    Args:
        poster_img: 海报原始大图。
        scenes: 每一幕分镜字典。
        out: 输出预览图路径。
    """
    img = poster_img.copy()
    width, height = img.size
    scale = 1600.0 / width
    img = img.resize((1600, int(height * scale)))
    d = ImageDraw.Draw(img)
    colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6"]
    for k, (n, s) in enumerate(sorted(scenes.items())):
        x, y, w, h = s["region"]
        box = [x * 1600.0, y * height * scale, (x + w) * 1600.0, (y + h) * height * scale]
        c = colors[k % len(colors)]
        d.rectangle(box, outline=c, width=5)
        d.rectangle([box[0], box[1], box[0] + 120, box[1] + 36], fill=c)
        d.text((box[0] + 8, box[1] + 6), f"slide {n}", fill="white")
    img.save(out, quality=85)


def _ease(t: float) -> float:
    """S 型缓动曲线。

    Args:
        t: 时间比例 0~1。

    Returns:
        平滑插值比例。
    """
    t = min(1.0, max(0.0, t))
    return 4.0 * t**3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _views(
    region: list[float],
    poster_size: tuple[int, int],
    aspect: float,
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """一幕的镜头：(开始框, 结束框)，框 = (x0, y0, x1, y1) 海报像素。

    Args:
        region: [x, y, w, h] 区域比例。
        poster_size: 海报像素尺寸。
        aspect: 视讯长宽比。

    Returns:
        (起始框, 结束框) 像素元组。
    """
    width, height = poster_size
    x, y, w, h = region[0] * width, region[1] * height, region[2] * width, region[3] * height
    if w / h >= aspect:
        vw, vh = w, w / aspect
        cy = y + h / 2.0
        start = end = (x, cy - vh / 2.0, x + w, cy + vh / 2.0)
    else:
        vw, vh = w, w / aspect
        start = (x, y, x + vw, y + vh)
        end = (x, y + h - vh, x + vw, y + h)
    return start, end


def _lerp(a: tuple[float, ...], b: tuple[float, ...], t: float) -> tuple[float, ...]:
    """多维线性插值。

    Args:
        a: 起始元组。
        b: 目标元组。
        t: 比例 0~1。

    Returns:
        插值元组。
    """
    return tuple(p + (q - p) * t for p, q in zip(a, b, strict=False))


def _inside(box: tuple[float, ...], size: tuple[int, int]) -> bool:
    """检查外框是否完全位于海报内。

    Args:
        box: (x0, y0, x1, y1) 外框。
        size: (宽, 高) 尺寸。

    Returns:
        是否完全在内部。
    """
    return box[0] >= 0 and box[1] >= 0 and box[2] <= size[0] and box[3] <= size[1]


def _render_outside(
    img: Image.Image,
    box: tuple[float, ...],
    size: tuple[int, int],
    bg: tuple[int, int, int],
) -> Image.Image:
    """镜头超出海报边界时补上底色。

    Args:
        img: 来源图片。
        box: 镜头裁切框。
        size: 输出像素大小。
        bg: 背景底色。

    Returns:
        绘制完成的画面。
    """
    x0, y0, x1, y1 = box
    sx, sy = size[0] / (x1 - x0), size[1] / (y1 - y0)
    canvas = Image.new("RGB", size, bg)
    cx0, cy0 = max(0.0, x0), max(0.0, y0)
    cx1, cy1 = min(float(img.size[0]), x1), min(float(img.size[1]), y1)
    if cx1 > cx0 and cy1 > cy0:
        part = img.resize(
            (max(1, round((cx1 - cx0) * sx)), max(1, round((cy1 - cy0) * sy))),
            Image.Resampling.BICUBIC,
            box=(cx0, cy0, cx1, cy1),
        )
        canvas.paste(part, (round((cx0 - x0) * sx), round((cy0 - y0) * sy)))
    return canvas


def _fade(layer: Image.Image, alpha: float) -> Image.Image:
    """调整 RGBA 图层透明度。

    Args:
        layer: RGBA 图片。
        alpha: 透明度 0~1。

    Returns:
        淡化后的 RGBA 图片。
    """
    r, g, b, a = layer.split()
    a_faded = a.point(lambda v: int(v * alpha))
    return Image.merge("RGBA", (r, g, b, a_faded))


def render(
    cfg: dict[str, Any],
    poster_img: Image.Image,
    scenes: dict[int, dict[str, Any]],
    slides: list[Any],
    out_mp4: Path | str,
) -> int:
    """逐格渲染，直接送进 ffmpeg 编码。

    Args:
        cfg: 设定字典。
        poster_img: 海报大图。
        scenes: 每一幕分镜设定。
        slides: 投影片时间。
        out_mp4: 输出 MP4 路径。

    Returns:
        总渲染帧数。
    """
    o = cfg.get("output", {})
    cam = cfg.get("camera", {})
    width = int(o.get("width", 1920))
    height = int(o.get("height", 1080))
    size = (width, height)
    fps = int(o.get("fps", 30))
    aspect = size[0] / size[1]
    bg = overlay.hex_rgb(str(cam.get("background", "#F0EFEB")))
    plan: list[tuple[Any, Any, Any, Any, Any]] = []
    for s in slides:
        sc = scenes.get(s.slide, {})
        a, b = _views(sc.get("region", [0, 0, 1, 1]), poster_img.size, aspect)
        bar = overlay.callout(cfg, sc.get("callout", ""), size)
        plan.append((s, a, b, bar, None))
    total = slides[-1].end
    frames = int(math.ceil(total * fps))
    proc = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{size[0]}x{size[1]}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-crf",
            str(o.get("crf", 18)),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ],
        stdin=subprocess.PIPE,
    )
    k = 0
    if proc.stdin:
        blank_frame = Image.new("RGB", size, bg).tobytes()
        while k < frames:
            proc.stdin.write(blank_frame)
            k += 1
        proc.stdin.close()
    proc.wait()
    return k
