"""ffmpeg 包装：合成影音（一定指定轨道）、烧字幕、检查成品、缩图总览。"""
import json
import re
import subprocess
from pathlib import Path

from PIL import Image

from . import overlay


def ff(*args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{r.stderr.strip()[-800:]}")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def duration(path):
    return float(probe(path)["format"]["duration"])


def read_srt(path):
    """[(开始, 结束, 文字)]"""
    def sec(t):
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    cues = []
    for block in Path(path).read_text(encoding="utf-8").strip().split("\n\n"):
        rows = block.splitlines()
        if len(rows) >= 3 and "-->" in rows[1]:
            a, b = (sec(x.strip()) for x in rows[1].split("-->"))
            cues.append((a, b, " ".join(rows[2:])))
    return cues


def mux(picture, narration, out, target_duration, cfg):
    """画面 + 配音 → mp4。画面比配音短就停在最后一格补足，比较长就剪掉。
    一定要 -map 0:v:0 -map 1:a:0（PDF：不加可能做出没有声音的影片，而且不会报错）。"""
    pd = duration(picture)
    vf = []
    if pd < target_duration - 0.02:
        vf.append(f"tpad=stop_mode=clone:stop_duration={target_duration - pd + 0.1:.3f}")
    vf.append(f"fps={cfg['output']['fps']},format=yuv420p")
    ff("-i", picture, "-i", narration, "-map", "0:v:0", "-map", "1:a:0",
       "-vf", ",".join(vf), "-c:v", "libx264", "-crf", cfg["output"]["crf"], "-preset", "medium",
       "-c:a", "aac", "-b:a", "192k", "-t", f"{target_duration:.3f}", "-movflags", "+faststart", out)


def burn_subtitles(video, srt, out, cfg, work, bottom_reserved=0):
    """把字幕画成透明图层（每条字幕一张 PNG，用 concat 接成一条有透明度的影片），再叠到画面上"""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    size = (vs["width"], vs["height"])
    total = float(info["format"]["duration"])
    blank = work / "blank.png"
    Image.new("RGBA", size, (0, 0, 0, 0)).save(blank)
    entries, t = [], 0.0
    for k, (a, b, text) in enumerate(read_srt(srt)):
        if a > t + 0.001:
            entries.append((blank, a - t))
        png = work / f"sub_{k:04d}.png"
        overlay.subtitle(cfg, text, size, bottom_reserved).save(png)
        entries.append((png, b - a))
        t = b
    if total > t:
        entries.append((blank, total - t))
    lst = work / "subs.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in entries)
                   + f"file '{entries[-1][0].resolve()}'\n")
    track = work / "subs.mov"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-r", cfg["output"]["fps"], "-c:v", "png", track)
    ff("-i", video, "-i", track, "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[v]",
       "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-crf", cfg["output"]["crf"], "-preset", "medium",
       "-c:a", "copy", "-movflags", "+faststart", out)


def check(video, narration, slides, sheet, work):
    """验收：有画面也有声音、长度对、声音不是静音；每一页抽一格做成缩图总览，给人眼检查"""
    info = probe(video)
    kinds = [s["codec_type"] for s in info["streams"]]
    report, ok = [], True
    if "video" not in kinds or "audio" not in kinds:
        ok = False
        report.append(f"❌ 轨道不完整：{kinds}（缺画面或缺声音）")
    vd, nd = float(info["format"]["duration"]), duration(narration)
    report.append(f"影片 {vd:.2f}s，配音 {nd:.2f}s")
    if vd < nd - 0.1:
        ok = False
        report.append("❌ 影片比配音短，结尾会被切掉")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-map", "0:a:0", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    if not m or float(m.group(1)) < -45:
        ok = False
        report.append(f"❌ 声音几乎是静音（mean {m.group(1) if m else '?'} dB）")
    else:
        report.append(f"声音正常（平均 {m.group(1)} dB）")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for s in slides:
        t = s.start + min(s.duration / 2, 3.0)
        p = work / f"thumb_{s.slide:02d}.jpg"
        ff("-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=480:-1", p)
        thumbs.append((s.slide, p))
    cols = 4
    w, h = Image.open(thumbs[0][1]).size
    rows = (len(thumbs) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * w, rows * (h + 36)), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    for k, (n, p) in enumerate(thumbs):
        x, y = (k % cols) * w, (k // cols) * (h + 36)
        canvas.paste(Image.open(p), (x, y + 36))
        d.text((x + 8, y + 8), f"slide {n}", fill="black")
    canvas.save(sheet, quality=85)
    report.append(f"缩图总览：{sheet}（每一页抽一格，请用眼睛确认画面）")
    return ok, report
