"""音讯处理：ffmpeg 包装、音量分析、找静音、检查头尾残留。"""

from __future__ import annotations

import array
import logging
import math
import subprocess
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FRAME = 0.01  # 分析单位：10ms
QUIET_DB = -45.0  # 低于这个音量才算静音
QUIET_MIN = 0.03  # 静音至少要这么长才能下刀
EDGE_DB = -40.0  # 片段头尾的音量上限
BLOB_MAX = 0.14  # 头尾短于这个长度的孤立声音，视为残留的「始」「结」


def ff(*args: Any) -> subprocess.CompletedProcess[str]:
    """执行 ffmpeg 包装指令。

    Args:
        *args: ffmpeg 命令参数。

    Returns:
        执行完成物件。
    """
    cmd = ["ffmpeg", "-v", "error", "-y", *map(str, args)]
    return subprocess.run(cmd, check=True, text=True)


def duration(path: Path | str) -> float:
    """透过 ffprobe 取得音讯秒数。

    Args:
        path: 音讯档案路径。

    Returns:
        音讯长度（秒）。
    """
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def cut(
    src: Path | str,
    dst: Path | str,
    start: float | None = None,
    end: float | None = None,
    rate: int = 24000,
) -> None:
    """切割音讯片段并转为单声道 PCM。

    Args:
        src: 来源音档路径。
        dst: 输出目标路径。
        start: 起始秒数。
        end: 结束秒数。
        rate: 取样率。
    """
    rng: list[str] = []
    if start is not None:
        rng.extend(["-ss", f"{start:.3f}"])
    if end is not None:
        rng.extend(["-to", f"{end:.3f}"])
    ff("-i", src, *rng, "-ar", rate, "-ac", 1, "-c:a", "pcm_s16le", dst)


def frames_db(path: Path | str) -> list[float]:
    """计算每 10ms 的音量分贝值（dBFS）。

    Args:
        path: WAV 音讯档案路径。

    Returns:
        分贝值列表。
    """
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        pcm = array.array("h", w.readframes(w.getnframes()))
    n = max(1, int(sr * FRAME))
    out: list[float] = []
    for k in range(len(pcm) // n):
        chunk = pcm[k * n : (k + 1) * n]
        rms_sq = sum(x * x for x in chunk) / n
        ratio = (rms_sq or 1e-9) / (32768**2)
        out.append(10 * math.log10(ratio))
    return out


def quiet_runs(db: list[float], lo: float, hi: float) -> list[tuple[float, float]]:
    """找出 [lo, hi] 秒之间的静音段 [(开始, 结束)]。

    Args:
        db: 分贝值列表。
        lo: 起始秒数。
        hi: 结束秒数。

    Returns:
        静音区间元组列表。
    """
    runs: list[tuple[float, float]] = []
    start: int | None = None
    a = max(0, int(lo / FRAME))
    b = min(len(db), int(hi / FRAME))
    for k in range(a, b):
        if db[k] < QUIET_DB:
            start = k if start is None else start
        else:
            if start is not None and (k - start) * FRAME >= QUIET_MIN:
                runs.append((start * FRAME, k * FRAME))
            start = None
    if start is not None and (b - start) * FRAME >= QUIET_MIN:
        runs.append((start * FRAME, b * FRAME))
    return runs


def _find_blobs(db: list[float]) -> list[tuple[float, float]]:
    """找出连续发声区间。

    Args:
        db: 分贝值列表。

    Returns:
        连续发声音块区间列表。
    """
    blobs: list[tuple[float, float]] = []
    k = 0
    while k < len(db):
        if db[k] > EDGE_DB:
            j = k
            while j < len(db) and db[j] > EDGE_DB:
                j += 1
            if blobs and k * FRAME - blobs[-1][1] < 0.05:
                blobs[-1] = (blobs[-1][0], j * FRAME)
            else:
                blobs.append((k * FRAME, j * FRAME))
            k = j
        else:
            k += 1
    return blobs


def edge_problems(path: Path | str) -> list[str]:
    """切好的片段：头尾要是静音，头尾不能有孤立的小块声音。

    Args:
        path: 音讯路径。

    Returns:
        边缘问题描述列表。
    """
    db = frames_db(path)
    probs: list[str] = []
    if db[:2] and max(db[:2]) > EDGE_DB:
        probs.append("开头贴着声音")
    if db[-2:] and max(db[-2:]) > EDGE_DB:
        probs.append("结尾贴着声音")
    blobs = _find_blobs(db)
    if len(blobs) > 1 and blobs[0][1] - blobs[0][0] < BLOB_MAX:
        probs.append(f"开头有孤立声音 {blobs[0][1] - blobs[0][0]:.2f}s")
    if len(blobs) > 1 and blobs[-1][1] - blobs[-1][0] < BLOB_MAX:
        probs.append(f"结尾有孤立声音 {blobs[-1][1] - blobs[-1][0]:.2f}s")
    return probs


def speech_bounds(path: Path | str, keep: float = 0.04, threshold: float = -45.0) -> tuple[float, float]:
    """有声音的范围（前后各留 keep 秒）。

    Args:
        path: 音讯路径。
        keep: 边缘保留秒数。
        threshold: 判别发声的音量门槛。

    Returns:
        (开始秒数, 结束秒数) 元组。
    """
    db = frames_db(path)
    on = [k for k, d in enumerate(db) if d > threshold]
    if not on:
        return 0.0, len(db) * FRAME
    return max(0.0, on[0] * FRAME - keep), min(len(db) * FRAME, (on[-1] + 1) * FRAME + keep)
