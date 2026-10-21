"""工具一：从影片提取音档。只需要 ffmpeg。

uv run extract_audio/extract.py 影片.mp4                       # → 影片.wav（单声道 48kHz）
uv run extract_audio/extract.py 影片.mp4 --out voice.wav
# 另外依停顿切成 10–20 秒的样本，给 Voicebox 建复制声音：
uv run extract_audio/extract.py 影片.mp4 --samples samples/
uv run extract_audio/extract.py 影片.mp4 --start 1:30 --end 2:10   # 只取一段
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIN_LEN, MAX_LEN = 10.0, 20.0  # 样本长度范围（秒）
NOISE, MIN_SIL = "-40dB", 0.35  # 低于此音量、持续超过此秒数才算停顿


def run(*args: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
    """执行外部子行程并检查返回值。

    Args:
        *args: 命令列参数。
        **kw: 传给 subprocess.run 的关键字参数。

    Returns:
        CompletedProcess 结果物件。
    """
    return subprocess.run(list(map(str, args)), check=True, **kw)


def duration(f: Path | str) -> float:
    """透过 ffprobe 查询音讯或影片长度（秒）。

    Args:
        f: 媒体档案路径。

    Returns:
        长度的秒数浮点数。
    """
    r = run(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        f,
        capture_output=True,
        text=True,
    )
    return float(r.stdout.strip())


def pause_points(f: Path | str) -> list[float]:
    """找出每个停顿的中点（秒）。

    Args:
        f: 音讯档案路径。

    Returns:
        停顿点秒数列表。
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(f),
        "-af",
        f"silencedetect=noise={NOISE}:d={MIN_SIL}",
        "-f",
        "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    return [(s + e) / 2 for s, e in zip(starts, ends, strict=False)]


def split_samples(wav: Path | str, out_dir: Path | str) -> list[Path]:
    """依停顿切成 10–20 秒的声音样本。

    Args:
        wav: 输入 wav 音讯路径。
        out_dir: 样本输出资料夹。

    Returns:
        切割完成的样本档案路径列表。
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    total, segs, start = duration(wav), [], 0.0
    for cut in pause_points(wav) + [total]:
        if cut - start >= MIN_LEN:  # 超过 MAX_LEN 也收下：中间没有够长的停顿可切
            segs.append((start, cut))
            start = cut
    sample_files: list[Path] = []
    for k, (s, e) in enumerate(segs, 1):
        target = out_path / f"sample_{k:02d}_{e - s:.1f}s.wav"
        run(
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            wav,
            "-ss",
            f"{s:.3f}",
            "-to",
            f"{e:.3f}",
            "-c:a",
            "pcm_s16le",
            target,
        )
        sample_files.append(target)
    logger.info("样本：%d 段 → %s/", len(segs), out_path)
    return sample_files


def extract_audio(
    video: Path | str,
    out: Path | str | None = None,
    rate: int = 48000,
    start: str | None = None,
    end: str | None = None,
    samples_dir: Path | str | None = None,
) -> Path:
    """从影片提取音档并可选择性产生声音样本。

    Args:
        video: 来源影片档案路径。
        out: 输出 WAV 路径，预设与影片同名。
        rate: 取样率（预设 48000）。
        start: 起始时间字串。
        end: 结束时间字串。
        samples_dir: 切割样本的储存目录。

    Returns:
        产出的 WAV 档案路径。
    """
    video_p = Path(video)
    out_p = Path(out) if out else video_p.with_suffix(".wav")
    rng: list[str] = []
    if start:
        rng.extend(["-ss", start])
    if end:
        rng.extend(["-to", end])
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(video_p),
        *rng,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(rate),
        "-c:a",
        "pcm_s16le",
        str(out_p),
    ]
    run(*cmd)
    logger.info("完成：%s（%.1f 秒）", out_p, duration(out_p))
    if samples_dir:
        split_samples(out_p, Path(samples_dir))
    return out_p


def main(argv: list[str] | None = None) -> int:
    """命令列执行进入点。

    Args:
        argv: 命令列参数清册。

    Returns:
        0 代表成功。
    """
    p = argparse.ArgumentParser(description="从影片提取音档")
    p.add_argument("video", help="影片档案路径")
    p.add_argument("--out", help="输出 wav（预设与影片同名）")
    p.add_argument("--rate", type=int, default=48000, help="取样率")
    p.add_argument("--start", help="开始时间，例如 1:30 或 90")
    p.add_argument("--end", help="结束时间")
    p.add_argument("--samples", help="另外切成声音样本的资料夹")
    a = p.parse_args(argv)
    extract_audio(
        video=a.video,
        out=a.out,
        rate=a.rate,
        start=a.start,
        end=a.end,
        samples_dir=a.samples,
    )
    return 0


if __name__ == "__main__":
    main()
