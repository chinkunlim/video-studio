"""拼接：每句切掉头尾静音，依停顿种类补静音，记录每句在成品里的起止时间（给字幕用）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from video_studio.services.narrate.core import audio

logger = logging.getLogger(__name__)

RATE = 24000


def build(
    items: list[dict[str, Any]],
    pause: dict[str, float],
    out_wav: Path | str,
    tmp: Path,
    loudness: float = -16.0,
    sample_rate: int = 48000,
) -> list[dict[str, Any]]:
    """依序拼接所有句子的音讯并加入适当停顿。

    Args:
        items: 每句资讯 [{no, slide, clip, brk}]。
        pause: 停顿秒数字典。
        out_wav: 最终输出的配音 WAV 路径。
        tmp: 暂存档资料夹。
        loudness: loudnorm 响度门槛（LUFS）。
        sample_rate: 最终取样率（预设 48000）。

    Returns:
        timeline 清单，包含每句起止时间。
    """
    tmp.mkdir(parents=True, exist_ok=True)
    listing: list[Path] = []
    timeline: list[dict[str, Any]] = []
    t = 0.0
    for k, it in enumerate(items):
        clip_path = Path(it["clip"])
        s, e = audio.speech_bounds(clip_path)
        piece = tmp / f"{it['no']:03d}.wav"
        audio.cut(clip_path, piece, s, e, RATE)
        d = audio.duration(piece)
        timeline.append(
            {
                "no": it["no"],
                "start": round(t, 3),
                "end": round(t + d, 3),
                "trim_start": round(s, 3),
            }
        )
        listing.append(piece)
        t += d
        if k + 1 < len(items):
            g = pause.get(it["brk"], pause.get("comma", 0.25))
            if items[k + 1]["slide"] != it["slide"]:
                g = max(g, pause.get("slide", 0.85))
            gap = tmp / f"gap_{g:.2f}.wav"
            if not gap.exists():
                audio.ff(
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={RATE}:cl=mono",
                    "-t",
                    f"{g:.3f}",
                    "-c:a",
                    "pcm_s16le",
                    gap,
                )
            listing.append(gap)
            t += audio.duration(gap)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in listing), encoding="utf-8")
    audio.ff(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        lst,
        "-af",
        f"loudnorm=I={loudness}:TP=-1.5:LRA=11",
        "-ar",
        sample_rate,
        out_wav,
    )
    return timeline
