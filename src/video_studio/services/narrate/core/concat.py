"""拼接：每句切掉头尾静音，依停顿种类补静音，记录每句在成品里的起止时间（给字幕用）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_studio.services.narrate.core import audio

logger = logging.getLogger(__name__)

RATE = 24000


@dataclass(frozen=True)
class ConcatOptions:
    """音讯拼接设定。

    Attributes:
        pause: 停顿秒数字典。
        tmp: 暂存档资料夹。
        loudness: loudnorm 响度门槛（LUFS）。
        sample_rate: 最终取样率（预设 48000）。
    """

    pause: dict[str, float] = field(default_factory=dict)
    tmp: Path = Path("tmp")
    loudness: float = -16.0
    sample_rate: int = 48000
    lead_in: float = 0.0


def _ensure_gap_wav(tmp: Path, gap_sec: float) -> Path:
    """建立或重用指定秒数的静音 WAV 档。

    Args:
        tmp: 暂存档资料夹。
        gap_sec: 静音秒数。

    Returns:
        静音 WAV 路径。
    """
    gap = tmp / f"gap_{gap_sec:.2f}.wav"
    if not gap.exists():
        audio.ff(
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={RATE}:cl=mono",
            "-t",
            f"{gap_sec:.3f}",
            "-c:a",
            "pcm_s16le",
            gap,
        )
    return gap


def _collect_segments(
    items: list[dict[str, Any]],
    options: ConcatOptions,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """切割各句有效语音并插入句间静音档案。

    Args:
        items: 每句资讯 [{no, slide, clip, brk}]。
        options: 拼接与响度设定。

    Returns:
        (待串接 WAV 路径列表, timeline 时间轴清册) 元组。
    """
    listing: list[Path] = []
    timeline: list[dict[str, Any]] = []
    t = 0.0
    if options.lead_in > 0:
        lead_gap = _ensure_gap_wav(options.tmp, options.lead_in)
        listing.append(lead_gap)
        t += audio.duration(lead_gap)
    for k, it in enumerate(items):
        clip_path = Path(it["clip"])
        s, e = audio.speech_bounds(clip_path)
        piece = options.tmp / f"{it['no']:03d}.wav"
        audio.cut(clip_path, piece, audio.CutOptions(start=s, end=e, rate=RATE))
        d = audio.duration(piece)
        timeline.append(
            {"no": it["no"], "start": round(t, 3), "end": round(t + d, 3), "trim_start": round(s, 3)}
        )
        listing.append(piece)
        t += d
        if k + 1 < len(items):
            g = options.pause.get(it["brk"], options.pause.get("comma", 0.25))
            if items[k + 1]["slide"] != it["slide"]:
                g = max(g, options.pause.get("slide", 0.85))
            gap = _ensure_gap_wav(options.tmp, g)
            listing.append(gap)
            t += audio.duration(gap)
    return listing, timeline


def build(
    items: list[dict[str, Any]],
    out_wav: Path | str,
    options: ConcatOptions,
) -> list[dict[str, Any]]:
    """依序拼接所有句子的音讯并加入适当停顿。

    Args:
        items: 每句资讯 [{no, slide, clip, brk}]。
        out_wav: 最终输出的配音 WAV 路径。
        options: 拼接与响度设定。

    Returns:
        timeline 清单，包含每句起止时间。
    """
    options.tmp.mkdir(parents=True, exist_ok=True)
    listing, timeline = _collect_segments(items, options)
    lst = options.tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in listing), encoding="utf-8")
    audio.ff(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        lst,
        "-af",
        f"loudnorm=I={options.loudness}:TP=-1.5:LRA=11",
        "-ar",
        options.sample_rate,
        out_wav,
    )
    return timeline
