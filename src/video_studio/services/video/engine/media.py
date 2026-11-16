"""ffmpeg 包装：合成影音（一定指定轨道）、烧字幕、检查成品、缩图总览。"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from video_studio.services.video.engine import overlay

logger = logging.getLogger(__name__)


def ff(*args: Any) -> subprocess.CompletedProcess[str]:
    """执行 ffmpeg 包装指令。

    Args:
        *args: ffmpeg 命令参数。

    Returns:
        CompletedProcess 结果物件。

    Raises:
        RuntimeError: 当 ffmpeg 返回代码不为 0 时。
    """
    cmd = ["ffmpeg", "-v", "error", "-y", *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = r.stderr.strip()[-800:]
        raise RuntimeError(f"ffmpeg 失败：{tail}")
    return r


def probe(path: Path | str) -> dict[str, Any]:
    """透过 ffprobe 获取多媒体档案详细资讯。

    Args:
        path: 档案路径。

    Returns:
        JSON 格式解析字典。
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    result: dict[str, Any] = json.loads(r.stdout)
    return result


def duration(path: Path | str) -> float:
    """取得媒体时长（秒）。

    Args:
        path: 媒体档案路径。

    Returns:
        时长秒数。
    """
    return float(probe(path)["format"]["duration"])


def read_srt(path: Path | str) -> list[tuple[float, float, str]]:
    """读取并解析 SRT 字幕档案。

    Args:
        path: SRT 档案路径。

    Returns:
        [(开始秒, 结束秒, 字幕文字), ...] 列表。
    """

    def sec(t: str) -> float:
        """解析 SRT 时间戳字串为总秒数。

        Args:
            t: 格式为 HH:MM:SS,mmm 的时间戳。

        Returns:
            秒数浮点数。
        """
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    cues: list[tuple[float, float, str]] = []
    content = Path(path).read_text(encoding="utf-8").strip()
    for block in content.split("\n\n"):
        rows = block.splitlines()
        if len(rows) >= 3 and "-->" in rows[1]:
            parts = [x.strip() for x in rows[1].split("-->")]
            a, b = sec(parts[0]), sec(parts[1])
            cues.append((a, b, " ".join(rows[2:])))
    return cues


@dataclass(frozen=True)
class MuxOptions:
    """影音合成设定参数。

    Attributes:
        target_duration: 目标总秒数。
        cfg: 设定字典。
    """

    target_duration: float
    cfg: dict[str, Any]


@dataclass(frozen=True)
class SubtitleBurnOptions:
    """字幕烧录设定参数。

    Attributes:
        cfg: 设定字典。
        work: 暂存处理资料夹。
        bottom_reserved: 底部保留高度。
    """

    cfg: dict[str, Any]
    work: Path | str
    bottom_reserved: int = 0


def mux(
    picture: Path | str,
    narration: Path | str,
    out: Path | str,
    options: MuxOptions,
) -> None:
    """画面 + 配音 → mp4。画面比配音短就停在最后一格补足，比较长就剪掉。

    Args:
        picture: 画面影片路径。
        narration: 配音音讯路径。
        out: 输出影片路径。
        options: 合成设定参数。
    """
    pd = duration(picture)
    vf = (
        [f"tpad=stop_mode=clone:stop_duration={options.target_duration - pd + 0.1:.3f}"]
        if pd < options.target_duration - 0.02
        else []
    )
    out_cfg = options.cfg.get("output", {})
    vf.append(f"fps={out_cfg.get('fps', 30)},format=yuv420p")
    cmd = [
        "-i",
        str(picture),
        "-i",
        str(narration),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        ",".join(vf),
        "-c:v",
        "libx264",
        "-crf",
        str(out_cfg.get("crf", "18")),
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{options.target_duration:.3f}",
        "-movflags",
        "+faststart",
        str(out),
    ]
    ff(*cmd)


def _render_subtitle_track(
    srt: Path | str, size: tuple[int, int], total: float, opts: SubtitleBurnOptions
) -> Path:
    """渲染透明字幕 PNG 序列并串接为 mov 轨道。

    Args:
        srt: SRT 字幕档案。
        size: 影片宽高。
        total: 影片总秒数。
        opts: 烧录设定参数。

    Returns:
        字幕透明轨道路径。
    """
    work_p = Path(opts.work)
    blank = work_p / "blank.png"
    Image.new("RGBA", size, (0, 0, 0, 0)).save(blank)
    entries: list[tuple[Path, float]] = []
    t = 0.0
    for k, (a, b, text) in enumerate(read_srt(srt)):
        if a > t + 0.001:
            entries.append((blank, a - t))
        png = work_p / f"sub_{k:04d}.png"
        overlay.subtitle(opts.cfg, text, size, opts.bottom_reserved).save(png)
        entries.append((png, b - a))
        t = b
    if total > t:
        entries.append((blank, total - t))
    if not entries:
        entries.append((blank, total))
    lst = work_p / "subs.txt"
    lst.write_text(
        "".join(f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in entries)
        + f"file '{entries[-1][0].resolve()}'\n",
        encoding="utf-8",
    )
    track = work_p / "subs.mov"
    fps = opts.cfg.get("output", {}).get("fps", 30)
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-r", str(fps), "-c:v", "png", str(track))
    return track


def burn_subtitles(
    video: Path | str,
    srt: Path | str,
    out: Path | str,
    options: SubtitleBurnOptions,
) -> None:
    """把字幕画成透明图层再叠到画面上。

    Args:
        video: 原始视讯档案。
        srt: SRT 字幕档案。
        out: 烧录字幕后的视讯输出路径。
        options: 烧录设定参数。
    """
    Path(options.work).mkdir(parents=True, exist_ok=True)
    info = probe(video)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    size = (int(vs["width"]), int(vs["height"]))
    track = _render_subtitle_track(srt, size, float(info["format"]["duration"]), options)
    crf = str(options.cfg.get("output", {}).get("crf", "18"))
    cmd = [
        "-i",
        str(video),
        "-i",
        str(track),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0:shortest=1[v]",
        "-map",
        "[v]",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-crf",
        crf,
        "-preset",
        "medium",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    ff(*cmd)


def _build_contact_sheet(
    video: Path | str, slides: list[Any], sheet: Path | str, work: Path | str
) -> str | None:
    """为每一页投影片抽一格做成缩图总览。

    Args:
        video: 检查影片。
        slides: 投影片资讯。
        sheet: 输出总览联络表路径。
        work: 暂存处理路径。

    Returns:
        缩图生成提示讯息，若无投影片则回传 None。
    """
    work_path = Path(work)
    work_path.mkdir(parents=True, exist_ok=True)
    thumbs: list[tuple[int, Path]] = []
    for s in slides:
        t = getattr(s, "start", 0.0) + min(getattr(s, "duration", 1.0) / 2.0, 3.0)
        thumb_path = work_path / f"thumb_{getattr(s, 'slide', 1):02d}.jpg"
        ff("-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=480:-1", thumb_path)
        thumbs.append((getattr(s, "slide", 1), thumb_path))
    if not thumbs or not thumbs[0][1].exists():
        return None
    cols = 4
    with Image.open(thumbs[0][1]) as first_img:
        w, h = first_img.size
    rows = (len(thumbs) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * w, rows * (h + 36)), "white")
    draw = ImageDraw.Draw(canvas)
    for k, (n, p) in enumerate(thumbs):
        x, y = (k % cols) * w, (k // cols) * (h + 36)
        with Image.open(p) as img:
            canvas.paste(img, (x, y + 36))
        draw.text((x + 8, y + 8), f"slide {n}", fill="black")
    Path(sheet).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(sheet, quality=85)
    return f"缩图总览：{sheet}（每一页抽一格，请用眼睛确认画面）"


def _check_audio_volume(video: Path | str, report: list[str]) -> bool:
    """检测影片音轨最大音量，判断是否静音。

    Args:
        video: 检查影片路径。
        report: 检查报告文字列表。

    Returns:
        音量是否正常（非静音）。
    """
    r = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    m = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", r.stderr)
    if not m:
        return True
    mv = float(m.group(1))
    report.append(f"最大音量 {mv:.1f} dBFS")
    if mv < -40.0:
        report.append("❌ 声音几乎是静音")
        return False
    return True


def check(
    video: Path | str,
    narration: Path | str,
    slides: list[Any],
    sheet_and_work: tuple[Path | str, Path | str],
) -> tuple[bool, list[str]]:
    """验收：有画面也有声音、长度对、声音不是静音；每一页抽一格做成缩图总览。

    Args:
        video: 检查影片。
        narration: 参考配音。
        slides: 投影片资讯。
        sheet_and_work: (输出总览联络表路径, 暂存处理路径) 元组。

    Returns:
        (是否合格, 检查报告文字列表)。
    """
    sheet, work = sheet_and_work
    info = probe(video)
    kinds = [s["codec_type"] for s in info["streams"]]
    report: list[str] = []
    ok = "video" in kinds and "audio" in kinds
    if not ok:
        report.append(f"❌ 轨道不完整：{kinds}（缺画面或缺声音）")
    vd, nd = float(info["format"]["duration"]), duration(narration)
    report.append(f"影片 {vd:.2f}s，配音 {nd:.2f}s")
    if vd < nd - 0.1:
        ok = False
        report.append("❌ 影片比配音短，结尾会被切掉")
    if not _check_audio_volume(video, report):
        ok = False
    sheet_msg = _build_contact_sheet(video, slides, sheet, work)
    if sheet_msg:
        report.append(sheet_msg)
    report.append("✅ 验收通过" if ok else "⚠️ 验收有项目未通过")
    return ok, report
