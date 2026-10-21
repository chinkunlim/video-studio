"""工具三：配音 + 画面 → 完整影片。先用 narrate.py build 产生配音（output/vN/）。

<job> = 工作名称（例如 bart-risk-taking）。素材由 job.toml 的 [inputs] 指定（pptx、poster、scenes）。

  uv run video/video.py timing  <job>                 # 每一页的起止时间与长度
  # 起草分镜到 review/scenes.toml + review/scenes_preview.jpg
  uv run video/video.py scenes  <job>
  uv run video/video.py preview <job> [--review]      # 把每一幕的区域画在海报上
  uv run video/video.py poster  <job>                 # 海报影片：渲染 → 合成配音 → 烧字幕 → 验收
  uv run video/video.py pptx    <job>                 # PowerPoint 汇出
  uv run video/video.py mux     <job> --video x.mp4   # 外部画面 + 配音
  uv run video/video.py check   <job>                 # 验收最新的 video.mp4
"""

from __future__ import annotations

import csv
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.narrate.core import script, vocab
from video_studio.services.video.engine import media, poster, storyboard, timing

logger = logging.getLogger(__name__)


def load_video_config() -> dict[str, Any]:
    """载入影片模组基础设定。

    Returns:
        包含 output, camera, callout, font 等设定的字典。
    """
    app_cfg = load_app_config()
    fixes_path = Path(__file__).resolve().parents[1] / "narrate" / "traditional_fixes.tsv"
    return {
        "output": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "crf": 18,
            "tail": 1.0,
        },
        "camera": {
            "raster_width": 3840,
            "background": "#F0EFEB",
            "move": 0.8,
            "hold_end": 0.5,
        },
        "callout": {
            "height": 140,
            "color": "#D9692E",
            "text_color": "#FFFFFF",
            "font_size": 34,
            "bullet_x": 80,
            "text_x": 130,
            "prefix": "✓",
            "fade": 0.3,
        },
        "subtitle": {
            "font_size": 34,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 3,
            "margin_bottom": 40,
        },
        "font": {
            "path": "/System/Library/Fonts/STHeiti Light.ttc",
            "index": 1,
        },
        "fixes_path": str(fixes_path),
        "voicebox_url": app_cfg.voicebox_url,
    }


def get_job(name: str) -> J.Job:
    """透过名称取得 Job 实例。

    Args:
        name: 工作名称。

    Returns:
        Job 物件。
    """
    return J.find(name)


def video_context(
    job_name: str,
    version: str | None = None,
) -> tuple[dict[str, Any], J.Job, Path, float, list[timing.Slide]]:
    """建立影片处理环境与读取时间轴。

    Args:
        job_name: 工作名称。
        version: 指定版本。

    Returns:
        (设定字典, Job, 版本路径, 配音秒数, Slide 列表) 元组。
    """
    cfg = load_video_config()
    job = get_job(job_name)
    v = timing.latest_version(job.output, version)
    nd = media.duration(v / "narration.wav")
    tail = float(cfg.get("output", {}).get("tail", 1.0))
    slides = timing.slides(v, nd, tail)
    return cfg, job, v, nd, slides


def need_input(job: J.Job, key: str, label: str) -> Path:
    """确保必要的 input 档案存在。

    Args:
        job: 工作物件。
        key: inputs 栏位。
        label: 显示名称。

    Returns:
        档案路径。
    """
    p = job.input_file(key)
    if not p:
        raise RuntimeError(f"job.toml 的 [inputs] {key} 是空的：请把{label}放进 input/")
    if not p.exists():
        raise RuntimeError(f"找不到{label}：{p}")
    return p


def write_timing_tsv(v: Path, slides: list[timing.Slide]) -> None:
    """输出投影片时间表至 TSV。

    Args:
        v: 版本目录。
        slides: Slide 列表。
    """
    with open(v / "slide_timing.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["slide", "start", "end", "duration", "lines", "clicks_from_slide_start"])
        for s in slides:
            clicks_str = " ".join(f"{c:.2f}" for c in s.clicks)
            w.writerow(
                [
                    s.slide,
                    f"{s.start:.2f}",
                    f"{s.end:.2f}",
                    f"{s.duration:.2f}",
                    len(s.lines),
                    clicks_str,
                ]
            )


def calc_timing(job_name: str, version: str | None = None) -> str:
    """计算并输出投影片在配音里的起止时间与长度。

    Args:
        job_name: 工作名称。
        version: 指定版本。

    Returns:
        时间表摘要文字。
    """
    _, _, v, nd, slides = video_context(job_name, version)
    write_timing_tsv(v, slides)
    rows: list[str] = [
        f"配音：{v / 'narration.wav'}（{nd:.2f} 秒）\n",
        "投影片  开始     结束    长度(秒)  句数  [click] 在页内第几秒",
    ]
    for s in slides:
        clicks_str = ", ".join(f"{c:.2f}" for c in s.clicks) or "-"
        rows.append(
            f"{s.slide:>4}  {s.start:7.2f}  {s.end:7.2f}  {s.duration:7.2f}  {len(s.lines):>4}  {clicks_str}"
        )
    rows.append(f"\n已存成 {v / 'slide_timing.tsv'}")
    return "\n".join(rows)


def script_slides_text(job: J.Job) -> dict[int, list[str]]:
    """读取讲稿每一页的字幕文字。

    Args:
        job: 工作物件。

    Returns:
        {投影片页码: [句子列表]} 字典。
    """
    if not job.script or not job.script.exists():
        raise RuntimeError("还没有讲稿 input/script.md：先写讲稿")
    voc = vocab.load(J.vocabulary_path())
    texts: dict[int, list[str]] = {}
    for ln in script.parse(job.script.read_text(encoding="utf-8")):
        texts.setdefault(ln.slide, []).append(vocab.expand(ln.raw, voc, "subtitle"))
    return texts


def draft_scenes(job_name: str, source: str = "auto", force: bool = False) -> str:
    """起草分镜到 review/scenes.toml + review/scenes_preview.jpg。

    Args:
        job_name: 工作名称。
        source: 来源模式 ('auto', 'pptx', 'text', 'even')。
        force: 是否强制覆盖已存在档案。

    Returns:
        起草完成报告文字。
    """
    cfg = load_video_config()
    job = get_job(job_name)
    texts = script_slides_text(job)
    slides = [SimpleNamespace(slide=n) for n in sorted(texts)]
    dst = job.review / "scenes.toml"
    job.review.mkdir(exist_ok=True)
    if dst.exists() and not force:
        raise RuntimeError(f"{dst} 已经存在，不会覆盖（要重做请加 force=True）")
    p = job.input_file("pptx")
    job.input_file("poster")
    src_mode = source
    if src_mode == "auto":
        if p and p.exists() and storyboard.read(p).get("storyboard_like"):
            src_mode = "pptx"
        else:
            src_mode = "even"
    if src_mode == "pptx":
        p_path = need_input(job, "pptx", "pptx")
        info = storyboard.read(p_path)
        if len(info.get("pages", [])) != len(slides):
            raise RuntimeError(f"pptx 有 {len(info.get('pages', []))} 页，讲稿有 {len(slides)} 页，要一样多")
        storyboard.write_scenes(info, dst, p_path.name)
        msg = f"已从 {p_path.name} 读出 {len(info.get('pages', []))} 幕的镜头位置与提示栏 → {dst}"
    else:
        pf_path = need_input(job, "poster", "海报")
        img = poster.load_poster(pf_path, cfg["camera"]["raster_width"])
        poster.write_template(dst, slides, img.size)
        msg = f"已起草 {dst}（{len(slides)} 幕，先把海报由上到下平均分配）"
    preview_path = job.review / "scenes_preview.jpg"
    pf_preview = need_input(job, "poster", "海报")
    img_preview = poster.load_poster(pf_preview, cfg["camera"]["raster_width"])
    scenes_map, _ = poster.read_scenes(dst)
    poster_scenes = {n: s for n, s in scenes_map.items() if s.get("visual") == "poster"}
    poster.preview(img_preview, poster_scenes, preview_path)
    return f"{msg}\n区域预览已产生：{preview_path}"


def render_poster_video(job_name: str, version: str | None = None) -> str:
    """海报影片渲染流程。

    Args:
        job_name: 工作名称。
        version: 指定版本。

    Returns:
        产生完成文字说明。
    """
    cfg, job, v, _, slides = video_context(job_name, version)
    sp = job.input_file("scenes") or (job.input / "scenes.toml")
    scenes, style = poster.read_scenes(sp)
    pf = need_input(job, "poster", "海报")
    img = poster.load_poster(pf, cfg["camera"]["raster_width"])
    o = cfg["output"]
    cfg = poster.apply_style(cfg, style, (o["width"], o["height"]))
    work = job.work / "video"
    work.mkdir(parents=True, exist_ok=True)
    picture = work / "picture.mp4"
    poster.render(cfg, img, scenes, slides, picture)
    has_bar = any(s.get("callout") for s in scenes.values())
    bottom_res = cfg.get("callout", {}).get("height", 0) if has_bar else 0
    out = v / "video.mp4"
    media.mux(picture, v / "narration.wav", out, slides[-1].end, cfg)
    burn = job.cfg.get("subtitles", {}).get("burn_in", True)
    if burn:
        sub_srt = v / "subtitles_vlc.srt"
        if sub_srt.exists():
            media.burn_subtitles(out, sub_srt, v / "video_subtitled.mp4", cfg, work / "subs", bottom_res)
    ok, report = media.check(out, v / "narration.wav", slides, v / "video_contact_sheet.jpg", work / "thumbs")
    write_timing_tsv(v, slides)
    shutil.rmtree(work, ignore_errors=True)
    report_text = "\n".join(report)
    status_str = "完成" if ok else "完成（但验收有项目未通过）"
    return f"{status_str}：{v}/\n{report_text}"
