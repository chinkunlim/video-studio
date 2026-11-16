"""一句话的生成：加 marker → Voicebox → 用 Whisper 时间戳找切点 → 只在静音处下刀 → 检查。

marker 一定要加，不加的话模型常会吞掉句子的头尾。Voicebox 会忽略 seed，
所以重试时换 marker 的写法（WRAPS），每种写法会得到不同的结果。
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_studio.services.narrate.core import audio, whisper
from video_studio.services.narrate.core.whisper import is_marker, norm, same_last

logger = logging.getLogger(__name__)

WRAPS: list[tuple[str, str]] = [
    ("开始。", "结束。"),
    ("开始……", "……结束。"),
    ("开始。\n\n", "\n\n结束。"),
    ("开始！……", "……结束！"),
    ("开始了。", "结束了。"),
    ("开始，", "，结束。"),
    ("现在开始。", "现在结束。"),
    ("开始……", "……结束！"),
]


def _find_end_marker(words: list[tuple[str, float, float]], k0: int, body: str) -> int | None:
    """定位正文最后一个字在时间戳中的索引。

    Args:
        words: 逐词时间戳列表。
        k0: 开头 marker 索引。
        body: 原文正规化字串。

    Returns:
        匹配到的词汇索引，找不到则回传 None。
    """
    k1 = next((k for k in range(len(words) - 1, k0, -1) if same_last(words[k][0], body)), None)
    if k1 is None and body[-1:].isascii():
        k1 = next(
            (k for k in range(len(words) - 1, k0, -1) if words[k][0] and not is_marker(words[k][0])),
            None,
        )
    return k1


def cut_points(
    words: list[tuple[str, float, float]],
    body: str,
    raw: Path | str,
) -> tuple[float | None, float | None, str]:
    """回传 (正文开始秒, 正文结束秒, 失败原因)。找不到静音就放弃这一次。

    Args:
        words: 包含 marker 的逐词时间戳列表。
        body: 原文正规化字串。
        raw: 原始生成未切割的 WAV 档案路径。

    Returns:
        (开始秒数, 结束秒数, 错误原因字串)。
    """
    db = audio.frames_db(raw)
    dur = len(db) * audio.FRAME
    k0 = next((k for k, (w, _, _) in enumerate(words[:4]) if "始" in w), None)
    if k0 is None or k0 + 1 >= len(words):
        return None, None, "听不出开头的「开始」"
    runs = audio.quiet_runs(db, words[k0][2] - 0.15, words[k0 + 1][1] + 0.2)
    if not runs:
        return None, None, "「开始」和正文之间没有静音"
    a = runs[-1][1] - 0.02
    k1 = _find_end_marker(words, k0, body)
    if k1 is None:
        return None, None, "对不上原文最后一个字"
    s1, e1 = words[k1][1], words[k1][2]
    hi = words[k1 + 1][1] + 0.25 if k1 + 1 < len(words) else dur
    runs = audio.quiet_runs(db, max(a, (s1 + e1) / 2), hi)
    if not runs:
        return None, None, "正文和「结束」之间没有静音"
    b = runs[0][0] + 0.02
    if b - a < 0.3:
        return None, None, "切出来太短"
    return a, b, ""


@dataclass(frozen=True)
class TakeOptions:
    """单句生成的可选控制参数。

    Attributes:
        tries: 最大重试尝试次数。
        keep_all: 是否保留所有通过版本（用于试听）。
        log: 记录函式，预设使用 logger.info。
    """

    tries: int | None = None
    keep_all: bool = False
    log: Callable[[str], None] | None = None


@dataclass(frozen=True)
class _AttemptCtx:
    """单次重试所需参数上下文。"""

    vb: Any
    text: str
    body: str
    work: Path
    model: str
    accept_sim: float
    logger_fn: Callable[[str], None]


def _verify_clip_quality(k: int, clip: Path, ctx: _AttemptCtx, t0: float) -> dict[str, Any] | None:
    """用 Whisper 检验切割后音档的相似度与头尾残留。

    Args:
        k: 尝试索引。
        clip: 切割后音档路径。
        ctx: 单次重试上下文。
        t0: 本次尝试开始时间戳。

    Returns:
        通过检验的 take 字典，未通过则回传 None。
    """
    ws = whisper.words(clip, ctx.model)
    hyp = "".join(w for w, _, _ in ws)
    sim = whisper.similarity(ctx.text, hyp)
    head, tail = whisper.residue(ctx.text, hyp)
    if head or tail or sim < ctx.accept_sim:
        msg = f"    第{k + 1}次：相似度 {sim:.2f}"
        if head:
            msg += f" 残留{head}"
        if tail:
            msg += f" {tail}"
        ctx.logger_fn(f"{msg}｜{hyp}")
        return None
    ctx.logger_fn(f"    第{k + 1}次：通过，相似度 {sim:.2f}（{time.time() - t0:.0f}s）｜{hyp}")
    return {"clip": clip, "words": ws, "hyp": hyp, "sim": round(sim, 3), "wrap": k + 1}


def _run_single_attempt(k: int, ctx: _AttemptCtx) -> dict[str, Any] | None:
    """执行单次 TTS 生成、切割与品质检验。

    Args:
        k: 尝试索引（从 0 开始）。
        ctx: 单次重试上下文。

    Returns:
        通过检验的 take 字典，未通过则回传 None。
    """
    pre, post = WRAPS[k % len(WRAPS)]
    raw = ctx.work / f"raw{k + 1}.wav"
    clip = ctx.work / f"take{k + 1}.wav"
    t0 = time.time()
    try:
        raw.write_bytes(ctx.vb.generate(f"{pre}{ctx.text}{post}"))
    except (TimeoutError, RuntimeError) as e:
        ctx.logger_fn(f"    第{k + 1}次：生成失败（{e}）")
        return None
    a, b, why = cut_points(whisper.words(raw, ctx.model), ctx.body, raw)
    if a is None:
        ctx.logger_fn(f"    第{k + 1}次：{why}")
        return None
    audio.cut(raw, clip, audio.CutOptions(start=a, end=b))
    probs = audio.edge_problems(clip)
    if probs:
        ctx.logger_fn(f"    第{k + 1}次：{'、'.join(probs)}")
        return None
    return _verify_clip_quality(k, clip, ctx, t0)


def take(
    vb: Any,
    text: str,
    work_and_cfg: tuple[Path, dict[str, Any]],
    options: TakeOptions | None = None,
) -> list[dict[str, Any]]:
    """生成一句。回传通过检查的版本 [{clip, words, hyp, sim, wrap}]。

    Args:
        vb: Voicebox 客户端。
        text: 要发音的文字。
        work_and_cfg: (暂存输出目录, 设定字典) 元组。
        options: 重试与记录设定。

    Returns:
        通过的 take 资料字典列表。
    """
    work, cfg = work_and_cfg
    opts = options or TakeOptions()
    work.mkdir(parents=True, exist_ok=True)
    if getattr(vb, "no_wrap", False):
        clip = work / "take1.wav"
        clip.write_bytes(vb.generate(text))
        ws = whisper.words(clip, str(cfg.get("whisper", {}).get("model", "small")))
        return [{"clip": clip, "words": ws, "hyp": text, "sim": 1.0, "wrap": 1}]
    max_tries = opts.tries or int(cfg.get("generate", {}).get("tries", 8))
    ctx = _AttemptCtx(
        vb=vb,
        text=text,
        body=norm(text),
        work=work,
        model=str(cfg.get("whisper", {}).get("model", "small")),
        accept_sim=float(cfg.get("generate", {}).get("accept_similarity", 0.85)),
        logger_fn=opts.log or logger.info,
    )
    passed: list[dict[str, Any]] = []
    for k in range(max_tries):
        item = _run_single_attempt(k, ctx)
        if item is not None:
            passed.append(item)
            if not opts.keep_all:
                break
    return passed


def store(result: dict[str, Any], dest: Path) -> Path:
    """把通过的版本存到 takes/ 资料夹。

    Args:
        result: take 资料字典。
        dest: 目标档案路径。

    Returns:
        最终存放路径。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result["clip"], dest)
    return dest
