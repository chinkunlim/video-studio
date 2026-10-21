#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""工具一：从影片提取音档。只需要 ffmpeg。

  uv run extract_audio/extract.py 影片.mp4                       # → 影片.wav（单声道 48kHz）
  uv run extract_audio/extract.py 影片.mp4 --out voice.wav
  uv run extract_audio/extract.py 影片.mp4 --samples samples/    # 另外依停顿切成 10–20 秒的样本，给 Voicebox 建复制声音
  uv run extract_audio/extract.py 影片.mp4 --start 1:30 --end 2:10   # 只取一段
"""
import argparse, re, subprocess
from pathlib import Path

MIN_LEN, MAX_LEN = 10.0, 20.0      # 样本长度范围（秒）
NOISE, MIN_SIL = "-40dB", 0.35     # 低于此音量、持续超过此秒数才算停顿


def run(*args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def duration(f):
    r = run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f,
            capture_output=True, text=True)
    return float(r.stdout.strip())


def pause_points(f):
    """每个停顿的中点（秒）"""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-af",
                        f"silencedetect=noise={NOISE}:d={MIN_SIL}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    return [(s + e) / 2 for s, e in zip(starts, ends)]


def split_samples(wav, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    total, segs, start = duration(wav), [], 0.0
    for cut in pause_points(wav) + [total]:
        if cut - start >= MIN_LEN:                # 超过 MAX_LEN 也收下：中间没有够长的停顿可切
            segs.append((start, cut))
            start = cut
    for k, (s, e) in enumerate(segs, 1):
        run("ffmpeg", "-v", "error", "-y", "-i", wav, "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
            "-c:a", "pcm_s16le", out_dir / f"sample_{k:02d}_{e - s:.1f}s.wav")
    print(f"样本：{len(segs)} 段 → {out_dir}/")


def main():
    p = argparse.ArgumentParser(description="从影片提取音档")
    p.add_argument("video")
    p.add_argument("--out", help="输出 wav（预设与影片同名）")
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--start", help="开始时间，例如 1:30 或 90")
    p.add_argument("--end", help="结束时间")
    p.add_argument("--samples", help="另外切成声音样本的资料夹")
    a = p.parse_args()
    video = Path(a.video)
    out = Path(a.out) if a.out else video.with_suffix(".wav")
    rng = (["-ss", a.start] if a.start else []) + (["-to", a.end] if a.end else [])
    run("ffmpeg", "-v", "error", "-y", "-i", video, *rng, "-vn", "-ac", 1, "-ar", a.rate,
        "-c:a", "pcm_s16le", out)
    print(f"完成：{out}（{duration(out):.1f} 秒）")
    if a.samples:
        split_samples(out, Path(a.samples))


if __name__ == "__main__":
    main()
