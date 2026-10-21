"""工具二：讲稿 → Voicebox 配音 → 拼接 → 字幕（YouTube / PowerPoint / VLC，繁体中文）。

使用前：从 Dock 打开 Voicebox，在 app 里用声音档生成一句话（让模型载入）。
<job> = 工作名称（例如 bart-risk-taking，或 generate/bart-risk-taking），见 docs/DESIGN.md。
讲稿在 <job>/input/script.md；每句音档在 work/takes/；试听版本在 review/audition/；成品在 output/vN/。
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.narrate.core import (
    audio,
    concat,
    generate,
    numbers,
    script,
    subtitles,
    vocab,
    whisper,
)
from video_studio.services.narrate.core.takes import Takes
from video_studio.services.narrate.core.takes import key as take_key
from video_studio.services.narrate.core.voicebox import Voicebox

logger = logging.getLogger(__name__)


def load_narrate_config(job: J.Job | None = None) -> dict[str, Any]:
    """载入 narrate 设定并套用工作覆盖。

    Args:
        job: 工作物件（选填）。

    Returns:
        包含 voicebox, audio, pause, whisper 等设定的字典。
    """
    app_cfg = load_app_config()
    cfg: dict[str, Any] = {
        "voicebox": {
            "url": app_cfg.voicebox_url,
            "profile": "My Voice",
            "language": "zh",
            "cleanup": True,
            "timeout": 180,
        },
        "audio": {
            "sample_rate": 48000,
            "loudness": -16.0,
        },
        "pause": {
            "paragraph": 0.85,
            "sentence": 0.5,
            "semicolon": 0.4,
            "comma": 0.25,
            "slide": 0.85,
        },
        "whisper": {
            "model": "small",
        },
        "generate": {
            "tries": 8,
            "accept_similarity": 0.85,
        },
        "subtitle": {
            "max_width": 18.0,
            "lead": 0.05,
            "tail": 0.08,
            "min_duration": 0.8,
            "opencc": "s2tw",
            "font": "PingFang TC",
            "font_size": 28,
        },
    }
    if job:
        voice_profile = job.cfg.get("voice", {}).get("profile")
        if voice_profile:
            cfg["voicebox"]["profile"] = voice_profile
        if "loudness" in job.cfg.get("output", {}):
            cfg["audio"]["loudness"] = job.cfg["output"]["loudness"]
    return cfg


def load_lines(job: J.Job) -> tuple[list[script.Line], dict[str, dict[str, str]]]:
    """载入讲稿行与词汇表并产生字幕与发音文字。

    Args:
        job: 工作物件。

    Returns:
        (Line 物件列表, 词汇表字典) 元组。
    """
    voc_path = J.vocabulary_path()
    voc = vocab.load(voc_path)
    if not job.script or not job.script.exists():
        raise RuntimeError(f"找不到讲稿档案：{job.script}")
    lines = script.parse(job.script.read_text(encoding="utf-8"))
    for ln in lines:
        ln.subtitle = vocab.expand(ln.raw, voc, "subtitle")
        ln.tts = numbers.normalize(vocab.expand(ln.raw, voc, "tts"))
    return lines, voc


def takes_of(job: J.Job) -> Takes:
    """取得工作的 Takes 管理器。

    Args:
        job: 工作物件。

    Returns:
        Takes 实例。
    """
    return Takes(job.dir, job.takes_json)


def list_lines(job: J.Job) -> str:
    """列出讲稿的每一行：行号、投影片、字幕文字 vs 送给 Voicebox 的文字。

    Args:
        job: 工作物件。

    Returns:
        讲稿状态列表文字。
    """
    lines, _ = load_lines(job)
    takes = takes_of(job)
    out: list[str] = []
    for ln in lines:
        tts_val = getattr(ln, "tts", "")
        sub_val = getattr(ln, "subtitle", "")
        t = takes.get(tts_val)
        state = "🔒" if t and t.get("locked") else ("✓" if t else "·")
        out.append(f"{ln.no:>3} [{ln.slide:>2}] {state} {sub_val}")
        if tts_val != sub_val:
            out.append(f"{'':10}念法：{tts_val}")
    out.append("\n✓ 已有音档  🔒 已锁定  · 还没生成")
    return "\n".join(out)


def scan_vocab(job: J.Job) -> str:
    """检查词汇表：漏标的英文、表里没有的 key。

    Args:
        job: 工作物件。

    Returns:
        词汇检查报告文字。
    """
    voc_path = J.vocabulary_path()
    voc = vocab.load(voc_path)
    used: dict[str, list[int]] = {}
    problems = 0
    out: list[str] = []
    if not job.script or not job.script.exists():
        raise RuntimeError("找不到讲稿档案")
    for ln in script.parse(job.script.read_text(encoding="utf-8")):
        for k in vocab.used_keys(ln.raw):
            used.setdefault(k, []).append(ln.no)
            if k not in voc:
                out.append(f"第 {ln.no} 行：词汇表没有「{k}」")
                problems += 1
        for w in vocab.unmarked_english(ln.raw):
            out.append(f"第 {ln.no} 行：英文「{w}」没有放进 {{{{}}}}，可能漏标")
            problems += 1
    out.append("\n用到的词汇：")
    for k, nos in used.items():
        v = voc.get(k, {})
        tested_str = "" if v.get("tested") else "（未试听）"
        nos_str = ", ".join(map(str, nos))
        sub_text = v.get("subtitle", "?")
        tts_text = v.get("tts", "?")
        out.append(f"  {{{{{k}}}}} 字幕「{sub_text}」念「{tts_text}」{tested_str}  第 {nos_str} 行")
    status_str = "没有问题" if not problems else f"有 {problems} 个地方要检查"
    out.append(f"\n{status_str}")
    return "\n".join(out)


def _generate_missing_takes(job: J.Job, missing: list[script.Line], cfg: dict[str, Any]) -> None:
    """为缺少的句子逐一呼叫 Voicebox 生成并记录。

    Args:
        job: 工作物件。
        missing: 缺少的讲稿行列表。
        cfg: 设定字典。
    """
    vb = Voicebox(cfg["voicebox"])
    vb.check_ready()
    takes = takes_of(job)
    for ln in missing:
        tts_val = getattr(ln, "tts", "")
        logger.info("[%d] %s", ln.no, tts_val)
        res = generate.take(vb, tts_val, job.work / "gen" / take_key(tts_val), cfg)
        if not res:
            logger.warning("    全部失败：第 %d 句生成失败", ln.no)
            continue
        dest = generate.store(res[0], job.takes_dir / f"{take_key(tts_val)}.wav")
        takes.put(tts_val, dest, res[0]["words"], f"build 写法{res[0]['wrap']}", res[0]["sim"])


def _export_subtitles_and_meta(
    job: J.Job,
    lines: list[script.Line],
    timeline: list[dict[str, Any]],
    out: Path,
    cfg: dict[str, Any],
) -> list[str]:
    """输出字幕与时间对照表格档案。

    Args:
        job: 工作物件。
        lines: 讲稿行列表。
        timeline: 拼接时间轴资料。
        out: 成品资料夹。
        cfg: 设定字典。

    Returns:
        产出的字幕档名列表。
    """
    takes = takes_of(job)
    sub_lines: list[dict[str, Any]] = []
    for ln, tl in zip(lines, timeline, strict=False):
        tts_val = getattr(ln, "tts", "")
        sub_val = getattr(ln, "subtitle", "")
        t = takes.get(tts_val) or {}
        if not t.get("words"):
            t["words"] = whisper.words(job.dir / str(t.get("clip", "")), cfg["whisper"]["model"])
            takes.save()
        sub_lines.append({"text": sub_val, "words": t["words"], **tl})
    fixes_path = Path(__file__).resolve().parent / "traditional_fixes.tsv"
    cues = subtitles.to_traditional(subtitles.build_cues(sub_lines, cfg), cfg, fixes_path)
    files = subtitles.write_all(cues, out, cfg, job.title)
    with open(out / "tts_vs_subtitle.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(
            [
                "行",
                "投影片",
                "开始",
                "结束",
                "字幕（讲稿）",
                "Voicebox 念法",
                "不同",
                "来源",
                "Whisper 听写",
            ]
        )
        for ln, tl in zip(lines, timeline, strict=False):
            tts_val = getattr(ln, "tts", "")
            sub_val = getattr(ln, "subtitle", "")
            t = takes.get(tts_val) or {}
            hyp = "".join(x[0] for x in t.get("words", []))
            diff = "是" if tts_val != sub_val else ""
            w.writerow(
                [
                    ln.no,
                    ln.slide,
                    tl["start"],
                    tl["end"],
                    sub_val,
                    tts_val,
                    diff,
                    t.get("source", ""),
                    hyp,
                ]
            )
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    if job.script and job.script.exists():
        shutil.copy2(job.script, out / "script.md")
    voc_path = J.vocabulary_path()
    if voc_path.exists():
        shutil.copy2(voc_path, out / "vocabulary.tsv")
    return files


def build_narration(job: J.Job) -> str:
    """生成缺少的句子 → 拼接 → 字幕，输出到 output/vN/。

    Args:
        job: 工作物件。

    Returns:
        产生结果摘要文字。
    """
    cfg = load_narrate_config(job)
    lines, _ = load_lines(job)
    takes = takes_of(job)
    missing = [ln for ln in lines if not takes.get(getattr(ln, "tts", ""))]
    if missing:
        _generate_missing_takes(job, missing, cfg)
    still = [ln.no for ln in lines if not takes.get(getattr(ln, "tts", ""))]
    if still:
        still_str = ", ".join(map(str, still))
        raise RuntimeError(f"还有 {len(still)} 句没有音档（{still_str}），请先 audition 再 build。")
    out = job.next_output()
    out.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "no": ln.no,
            "slide": ln.slide,
            "brk": ln.brk,
            "clip": job.dir / str((takes.get(getattr(ln, "tts", "")) or {}).get("clip", "")),
        }
        for ln in lines
    ]
    timeline = concat.build(
        items,
        cfg["pause"],
        out / "narration.wav",
        out / "tmp",
        cfg["audio"]["loudness"],
        cfg["audio"]["sample_rate"],
    )
    if (out / "tmp").exists():
        shutil.rmtree(out / "tmp")
    files = _export_subtitles_and_meta(job, lines, timeline, out, cfg)
    dur_min = audio.duration(out / "narration.wav") / 60.0
    return (
        f"完成：{out}/\n"
        f"  narration.wav（配音，{dur_min:.1f} 分钟，{len(lines)} 句）\n"
        f"  字幕 {len(timeline)} 条：{'、'.join(files)}\n"
        "  tts_vs_subtitle.tsv、timeline.json、script.md 与 vocabulary.tsv 已留底"
    )


def audition_line(job: J.Job, line_no: int, takes_count: int = 4) -> str:
    """为特定讲稿行生成多个试听版本。

    Args:
        job: 工作物件。
        line_no: 行号。
        takes_count: 版本数量。

    Returns:
        试听产生摘要。
    """
    cfg = load_narrate_config(job)
    lines, _ = load_lines(job)
    if not 1 <= line_no <= len(lines):
        raise RuntimeError(f"没有第 {line_no} 行（讲稿共 {len(lines)} 行）")
    ln = lines[line_no - 1]
    vb = Voicebox(cfg["voicebox"])
    vb.check_ready()
    tts_val = getattr(ln, "tts", "")
    res = generate.take(
        vb,
        tts_val,
        job.work / "gen" / take_key(tts_val),
        cfg,
        tries=len(generate.WRAPS),
        keep_all=True,
    )[:takes_count]
    dest_dir = job.review / "audition" / f"line{ln.no:03d}"
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    meta: list[dict[str, Any]] = []
    lines_out: list[str] = [f"[{ln.no}] {tts_val}"]
    for k, r in enumerate(res, 1):
        dest = generate.store(r, dest_dir / f"{k}.wav")
        meta.append(
            {
                "take": k,
                "file": str(dest.relative_to(job.dir)),
                "words": r["words"],
                "sim": r["sim"],
                "wrap": r["wrap"],
                "hyp": r["hyp"],
            }
        )
        lines_out.append(f"  {dest}  ｜{r['hyp']}")
    (dest_dir / "takes.json").write_text(
        json.dumps({"tts": tts_val, "takes": meta}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    lines_out.append(f"\n听完后选用：uv run narrate/narrate.py pick {job.name} {ln.no} <编号>")
    return "\n".join(lines_out)


def pick_take(job: J.Job, line_no: int, take_no: int) -> str:
    """选定试听版本并锁定。

    Args:
        job: 工作物件。
        line_no: 行号。
        take_no: 版本编号。

    Returns:
        选定确认文字。
    """
    lines, _ = load_lines(job)
    if not 1 <= line_no <= len(lines):
        raise RuntimeError(f"没有第 {line_no} 行（讲稿共 {len(lines)} 行）")
    ln = lines[line_no - 1]
    tts_val = getattr(ln, "tts", "")
    d = job.review / "audition" / f"line{ln.no:03d}"
    if not (d / "takes.json").exists():
        raise RuntimeError(f"第 {ln.no} 行还没有试听版本，请先 audition")
    meta = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    if meta.get("tts") != tts_val:
        raise RuntimeError("这一行的念法在试听后改过了，请重新 audition")
    chosen = next((x for x in meta.get("takes", []) if x.get("take") == take_no), None)
    if chosen is None:
        raise RuntimeError(f"没有第 {take_no} 个版本")
    dest = job.takes_dir / f"{take_key(tts_val)}.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job.dir / chosen["file"], dest)
    takes_of(job).put(
        tts_val, dest, chosen["words"], f"audition 第{take_no}个", chosen.get("sim"), locked=True
    )
    return f"第 {ln.no} 行改用第 {take_no} 个版本，并锁定。下次 build 会用它。"
