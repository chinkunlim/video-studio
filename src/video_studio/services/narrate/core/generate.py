"""一句话的生成：加 marker → Voicebox → 用 Whisper 时间戳找切点 → 只在静音处下刀 → 检查。

marker 一定要加，不加的话模型常会吞掉句子的头尾。Voicebox 会忽略 seed，
所以重试时换 marker 的写法（WRAPS），每种写法会得到不同的结果。
"""
import shutil, time
from pathlib import Path

from . import audio, whisper
from .whisper import is_marker, norm, same_last

WRAPS = [("开始。", "结束。"), ("开始……", "……结束。"),
         ("开始。\n\n", "\n\n结束。"), ("开始！……", "……结束！"),
         ("开始了。", "结束了。"), ("开始，", "，结束。"),
         ("现在开始。", "现在结束。"), ("开始……", "……结束！")]


def cut_points(words, body, raw):
    """回传 (正文开始秒, 正文结束秒, 失败原因)。找不到静音就放弃这一次。"""
    db = audio.frames_db(raw)
    dur = len(db) * audio.FRAME
    k0 = next((k for k, (w, _, _) in enumerate(words[:4]) if "始" in w), None)
    if k0 is None or k0 + 1 >= len(words):
        return None, None, "听不出开头的「开始」"
    runs = audio.quiet_runs(db, words[k0][2] - 0.15, words[k0 + 1][1] + 0.2)
    if not runs:
        return None, None, "「开始」和正文之间没有静音"
    a = runs[-1][1] - 0.02
    k1 = next((k for k in range(len(words) - 1, k0, -1) if same_last(words[k][0], body)), None)
    if k1 is None and body[-1:].isascii():        # 句尾是英文时 Whisper 常听成别的字
        k1 = next((k for k in range(len(words) - 1, k0, -1)
                   if words[k][0] and not is_marker(words[k][0])), None)
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


def take(vb, text, work, cfg, tries=None, keep_all=False, log=print):
    """生成一句。回传通过检查的版本 [{clip, words, hyp, sim, wrap}]；keep_all=False 时第一个通过就停"""
    work.mkdir(parents=True, exist_ok=True)
    body = norm(text)
    tries = tries or cfg["generate"]["tries"]
    model = cfg["whisper"]["model"]
    passed = []
    for k in range(tries):
        pre, post = WRAPS[k % len(WRAPS)]
        raw, clip = work / f"raw{k + 1}.wav", work / f"take{k + 1}.wav"
        t0 = time.time()
        try:
            raw.write_bytes(vb.generate(f"{pre}{text}{post}"))
        except (TimeoutError, RuntimeError) as e:
            log(f"    第{k + 1}次：生成失败（{e}）")
            continue
        a, b, why = cut_points(whisper.words(raw, model), body, raw)
        if a is None:
            log(f"    第{k + 1}次：{why}")
            continue
        audio.cut(raw, clip, a, b)
        probs = audio.edge_problems(clip)
        if probs:
            log(f"    第{k + 1}次：{'、'.join(probs)}")
            continue
        ws = whisper.words(clip, model)
        hyp = "".join(w for w, _, _ in ws)
        sim = whisper.similarity(text, hyp)
        head, tail = whisper.residue(text, hyp)
        if head or tail or sim < cfg["generate"]["accept_similarity"]:
            log(f"    第{k + 1}次：相似度 {sim:.2f}{' 残留' + head if head else ''}{' ' + tail if tail else ''}｜{hyp}")
            continue
        log(f"    第{k + 1}次：通过，相似度 {sim:.2f}（{time.time() - t0:.0f}s）｜{hyp}")
        passed.append({"clip": clip, "words": ws, "hyp": hyp, "sim": round(sim, 3), "wrap": k + 1})
        if not keep_all:
            break
    return passed


def store(result, dest):
    """把通过的版本存到 takes/ 资料夹"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result["clip"], dest)
    return dest
