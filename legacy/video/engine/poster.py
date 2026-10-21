"""海报影片：镜头在海报上移动／卷动，加上外框、画面大字、底部提示栏（照 pptx 分镜或原始影片的样式）。

每一幕的设定在工作的 input/scenes.toml（格式见 templates/generate/input/scenes.toml）；
海报档案由 job.toml 的 [inputs] poster 指定。

  [style]   从 pptx 读出的样式（选填）：callout_height、callout_color、callout_text_color、callout_font_size、
            callout_text_x、callout_bullet_x、frame_inset、frame_color（数字都是占画面宽／高的比例）
  [[scene]] slide、visual = "poster"、region = [x, y, 宽, 高]、callout、overlay_text（画面大字）…

区域比画面宽：整块放进画面。区域比画面高（16:9 放不下）：宽度对齐，从区域顶端卷到底端。
渲染是确定的：同样的设定每次跑出来的每一格都一样（不用随机数、不用当前时间）。
"""
import math
import subprocess
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw

from . import overlay

Image.MAX_IMAGE_PIXELS = None          # 海报可能很大


def load_poster(path, raster_width):
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import fitz                     # PyMuPDF
        doc = fitz.open(path)
        page = doc[0]
        zoom = raster_width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Image.open(path).convert("RGB")


def read_scenes(path):
    """回传 (scenes {slide: scene}, style)；每一幕都已套用 [defaults]"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到 {p}。先用 `video.py scenes <工作>` 起草到 review/，确认后 `sv.py approve <工作> scenes.toml`。")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    scenes = {}
    for s in data.get("scene", []):
        merged = {"visual": defaults.get("visual", "poster"), **s}
        scenes[int(merged["slide"])] = merged
    style = dict(data.get("style", {}))
    if "callout_prefix" in defaults:
        style["callout_prefix"] = defaults["callout_prefix"]
    return scenes, style


def apply_style(cfg, style, size):
    """把 [style]（比例）换算成像素，覆盖 cfg 的提示栏设定；回传新的 cfg"""
    import copy
    W, H = size
    c = copy.deepcopy(cfg)
    cc = c["callout"]
    if "callout_height" in style:
        cc["height"] = round(style["callout_height"] * H)
    for k in ("color", "text_color"):
        if f"callout_{k}" in style:
            cc[k] = style[f"callout_{k}"]
    if "callout_font_size" in style:
        cc["font_size"] = round(style["callout_font_size"] * H)
    if "callout_prefix" in style:
        cc["prefix"] = style["callout_prefix"]
    if "callout_bullet_x" in style:
        cc["bullet_x"] = round(style["callout_bullet_x"] * W)
    if "callout_text_x" in style:
        cc["text_x"] = round(style["callout_text_x"] * W)
    if "frame_inset" in style:
        c["frame"] = {"inset": style["frame_inset"], "color": style.get("frame_color", "#FFFFFF")}
    return c


def write_template(path, slides, poster_size):
    """产生 scenes.toml 草稿：把海报由上到下平均分给每一页（只是起点，需要调整）"""
    W, H = poster_size
    n = len(slides)
    view_h = min(1.0, (W * 9 / 16) / H)          # 一个画面在海报上的高度（比例）
    rows = ["# 每一幕要看海报的哪一块（自动起草：海报由上到下平均分配）。规则见 templates/generate/input/scenes.toml",
            "# 改完执行 video.py preview 看框线位置；确认后 sv.py approve <工作> scenes.toml", "",
            "[defaults]", 'visual = "poster"', 'callout_prefix = "✓"', ""]
    for k, s in enumerate(slides):
        y = 0.0 if n == 1 else (1 - view_h) * k / (n - 1)
        rows.append(f'[[scene]]\nslide = {s.slide}\nintent = ""\nregion = [0.0, {y:.4f}, 1.0, {view_h:.4f}]\ncallout = ""\n')
    Path(path).write_text("\n".join(rows), encoding="utf-8")


def preview(poster_img, scenes, out):
    """把每一幕的区域画在海报上，方便检查"""
    img = poster_img.copy()
    W, H = img.size
    scale = 1600 / W
    img = img.resize((1600, int(H * scale)))
    d = ImageDraw.Draw(img)
    colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6"]
    for k, (n, s) in enumerate(sorted(scenes.items())):
        x, y, w, h = s["region"]
        box = [x * 1600, y * H * scale, (x + w) * 1600, (y + h) * H * scale]
        c = colors[k % len(colors)]
        d.rectangle(box, outline=c, width=5)
        d.rectangle([box[0], box[1], box[0] + 120, box[1] + 36], fill=c)
        d.text((box[0] + 8, box[1] + 6), f"slide {n}", fill="white")
    img.save(out, quality=85)


def _ease(t):
    t = min(1.0, max(0.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _views(region, poster_size, aspect):
    """一幕的镜头：(开始框, 结束框)，框 = (x0, y0, x1, y1) 海报像素"""
    W, H = poster_size
    x, y, w, h = region[0] * W, region[1] * H, region[2] * W, region[3] * H
    if w / h >= aspect:                          # 够宽：整块放进画面
        vw, vh = w, w / aspect
        cy = y + h / 2
        start = end = (x, cy - vh / 2, x + w, cy + vh / 2)
    else:                                        # 太高：宽度对齐，从上卷到下
        vw, vh = w, w / aspect
        start = (x, y, x + vw, y + vh)
        end = (x, y + h - vh, x + vw, y + h)
    return start, end


def _lerp(a, b, t):
    return tuple(p + (q - p) * t for p, q in zip(a, b))


def render(cfg, poster_img, scenes, slides, out_mp4):
    """逐格渲染，直接送进 ffmpeg 编码（没有声音；声音之后由 media.mux 合成）"""
    o, cam = cfg["output"], cfg["camera"]
    size, fps = (o["width"], o["height"]), o["fps"]
    aspect = size[0] / size[1]
    bg = overlay.hex_rgb(cam["background"])
    missing = [s.slide for s in slides if s.slide not in scenes]
    if missing:
        raise ValueError(f"scenes.toml 少了这些投影片：{missing}")
    not_poster = [s.slide for s in slides if scenes[s.slide].get("visual", "poster") != "poster"]
    if not_poster:
        raise ValueError(f"这些投影片的 visual 不是 poster，海报渲染还不能处理：{not_poster}")
    border = overlay.frame(size, cfg["frame"]["inset"], cfg["frame"]["color"]) if cfg.get("frame") else None
    plan = []
    for s in slides:
        sc = scenes[s.slide]
        a, b = _views(sc["region"], poster_img.size, aspect)
        bar = overlay.callout(cfg, sc.get("callout", ""), size)
        big = overlay.overlay_text(cfg, sc.get("overlay_text", ""), sc.get("overlay_box", [0, 0, 1, 1]),
                                   sc.get("overlay_font_size", 0.1), sc.get("overlay_font", ""),
                                   sc.get("overlay_color", "#000000"), size)
        static = None                              # 外框 + 画面大字（每一幕固定，先合成一次）
        if border or big:
            static = Image.new("RGBA", size, (0, 0, 0, 0))
            for layer in (border, big):
                if layer:
                    static.alpha_composite(layer)
        plan.append((s, a, b, bar, static))
    total = slides[-1].end
    frames = int(math.ceil(total * fps))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
                             "-c:v", "libx264", "-crf", str(o["crf"]), "-preset", "medium",
                             "-pix_fmt", "yuv420p", str(out_mp4)], stdin=subprocess.PIPE)
    prev_end = plan[0][1]
    k, last_key, last_bytes = 0, None, None
    try:
        for idx, (s, a, b, bar, static) in enumerate(plan):
            src = prev_end
            n0, n1 = int(round(s.start * fps)), int(round(s.end * fps))
            move = cam["move"] if idx else 0.0
            scroll_end = max(s.start + move, s.end - cam["hold_end"])
            for n in range(n0, n1):
                t = n / fps
                if t < s.start + move:
                    box = _lerp(src, a, _ease((t - s.start) / move))
                elif a != b and scroll_end > s.start + move:
                    box = _lerp(a, b, _ease((t - s.start - move) / (scroll_end - s.start - move)))
                else:
                    box = b
                alpha = 1.0 if not bar else min(1.0, (t - s.start) / cfg["callout"]["fade"]) if cfg["callout"]["fade"] else 1.0
                key = (tuple(round(v, 2) for v in box), idx, round(alpha, 2))
                if key != last_key:
                    frame = poster_img.resize(size, Image.Resampling.BICUBIC, box=box, reducing_gap=None) \
                        if _inside(box, poster_img.size) else _render_outside(poster_img, box, size, bg)
                    if static or bar:
                        frame = frame.convert("RGBA")
                        if static:
                            frame.alpha_composite(static)
                        if bar:
                            frame.alpha_composite(bar if alpha >= 1 else _fade(bar, alpha))
                        frame = frame.convert("RGB")
                    last_key, last_bytes = key, frame.tobytes()
                proc.stdin.write(last_bytes)
                k += 1
            prev_end = b
        while k < frames:
            proc.stdin.write(last_bytes)
            k += 1
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg 编码失败")
    return k


def _inside(box, size):
    return box[0] >= 0 and box[1] >= 0 and box[2] <= size[0] and box[3] <= size[1]


def _render_outside(img, box, size, bg):
    """镜头超出海报边界（海报太窄或太矮）：超出的部分补底色"""
    x0, y0, x1, y1 = box
    sx, sy = size[0] / (x1 - x0), size[1] / (y1 - y0)
    canvas = Image.new("RGB", size, bg)
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(img.size[0], x1), min(img.size[1], y1)
    if cx1 > cx0 and cy1 > cy0:
        part = img.resize((max(1, round((cx1 - cx0) * sx)), max(1, round((cy1 - cy0) * sy))),
                          Image.Resampling.BICUBIC, box=(cx0, cy0, cx1, cy1))
        canvas.paste(part, (round((cx0 - x0) * sx), round((cy0 - y0) * sy)))
    return canvas


def _fade(layer, alpha):
    r, g, b, a = layer.split()
    a = a.point(lambda v: int(v * alpha))
    return Image.merge("RGBA", (r, g, b, a))
