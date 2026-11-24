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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.narrate.core import (
    audio,
    bilingual,
    concat,
    generate,
    numbers,
    prosody,
    samples,
    script,
    subtitles,
    vocab,
    whisper,
)
from video_studio.services.narrate.core.edge_tts_client import DEFAULT_EDGE_VOICE, EdgeTTSClient
from video_studio.services.narrate.core.samples import (
    VOICE_SAMPLE_TEXTS,
    ensure_voice_samples,
    get_cached_voice_samples,
    voice_sample_cache_dir,
)
from video_studio.services.narrate.core.takes import TakeEntry, Takes
from video_studio.services.narrate.core.takes import key as take_key
from video_studio.services.narrate.core.voicebox import Voicebox

__all__ = [
    "VOICE_SAMPLE_TEXTS",
    "ensure_voice_samples",
    "get_cached_voice_samples",
    "voice_sample_cache_dir",
]

logger = logging.getLogger(__name__)


def _default_narrate_config(voicebox_url: str) -> dict[str, Any]:
    """回传预设的 narrate 设定字典。

    Args:
        voicebox_url: Voicebox 服务网址。

    Returns:
        预设设定字典。
    """
    return {
        "voicebox": {
            "url": voicebox_url,
            "profile": "My Voice",
            "language": "zh",
            "cleanup": True,
            "timeout": 180,
        },
        "tts": {"engine": "voicebox", "edge_voice": DEFAULT_EDGE_VOICE, "edge_rate": "+0%"},
        "audio": {"sample_rate": 48000, "loudness": -16.0},
        "pause": {"paragraph": 0.85, "sentence": 0.5, "semicolon": 0.4, "comma": 0.25, "slide": 0.85},
        "whisper": {"model": "small"},
        "generate": {"tries": 8, "accept_similarity": 0.85},
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


def load_narrate_config(job: J.Job | None = None) -> dict[str, Any]:
    """载入 narrate 设定并套用工作覆盖。

    Args:
        job: 工作物件（选填）。

    Returns:
        包含 voicebox, audio, pause, whisper 等设定的字典。
    """
    cfg = _default_narrate_config(load_app_config().voicebox_url)
    if not job:
        return cfg
    voice_cfg = job.cfg.get("voice", {})
    if voice_cfg.get("profile"):
        cfg["voicebox"]["profile"] = voice_cfg["profile"]
    for src_key, dst_sec, dst_key in (
        ("language", "voicebox", "language"),
        ("engine", "tts", "engine"),
        ("edge_voice", "tts", "edge_voice"),
        ("edge_rate", "tts", "edge_rate"),
    ):
        if voice_cfg.get(src_key):
            val = str(voice_cfg[src_key]).strip()
            cfg[dst_sec][dst_key] = val.lower() if src_key == "engine" else val
    whisper_cfg = job.cfg.get("whisper", {})
    if whisper_cfg.get("model"):
        cfg["whisper"]["model"] = str(whisper_cfg["model"]).strip()
    if whisper_cfg.get("opencc_mode"):
        mode = str(whisper_cfg["opencc_mode"]).strip()
        cfg["whisper"]["opencc_mode"] = mode
        cfg["subtitle"]["opencc"] = mode
    if "loudness" in job.cfg.get("output", {}):
        cfg["audio"]["loudness"] = job.cfg["output"]["loudness"]
    return cfg


def _build_tts_client(cfg: dict[str, Any]) -> Voicebox | EdgeTTSClient:
    """依設定建立 Voicebox 或 edge-tts 語音生成客戶端。

    Args:
        cfg: narrate 設定字典。

    Returns:
        已初始化的 TTS 客戶端。
    """
    engine = cfg.get("tts", {}).get("engine", "voicebox")
    if engine == "edge-tts":
        return EdgeTTSClient(cfg.get("tts", {}))
    return Voicebox(cfg["voicebox"])


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
        clean_raw, _ = prosody.parse_prosody_tags(ln.raw)
        ln.subtitle = vocab.expand(clean_raw, voc, "subtitle")
        ln.tts = numbers.normalize(vocab.expand(clean_raw, voc, "tts"))
    return lines, voc


def takes_of(job: J.Job) -> Takes:
    """取得工作的 Takes 管理器。

    Args:
        job: 工作物件。

    Returns:
        Takes 实例。
    """
    return Takes(job.work, job.takes_json)


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


def preview_prosody_10s(job: J.Job, sample_text: str = "") -> dict[str, str]:
    """Generate 10-second normal/energetic/calm prosody audio previews into needs_review/<job>/.

    Args:
        job: Target Job instance.
        sample_text: Optional custom sample sentence(s) with prosody markup.

    Returns:
        Mapping of preset name ('normal', 'energetic', 'calm') to review filename.
    """
    cfg = load_narrate_config(job)
    text = sample_text.strip()
    if not text and job.script and job.script.exists():
        lines, _ = load_lines(job)
        text = " ".join(ln.raw for ln in lines[:2])
    if not text:
        text = "大家好，歡迎來到今天的分享。今天我們來聊聊 [loud]核心關鍵[/loud] 與未來的發展。"
    return samples.render_prosody_preview(job, cfg, text)


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
    vb = _build_tts_client(cfg)
    vb.check_ready()
    takes = takes_of(job)
    for ln in missing:
        tts_val = getattr(ln, "tts", "")
        logger.info("[%d] %s", ln.no, tts_val)
        res = generate.take(vb, tts_val, (job.work / "gen" / take_key(tts_val), cfg))
        if not res:
            logger.warning("    全部失败：第 %d 句生成失败", ln.no)
            continue
        dest = generate.store(res[0], job.takes_dir / f"{take_key(tts_val)}.wav")
        _, spans = prosody.parse_prosody_tags(ln.raw)
        preset = str(job.cfg.get("voice", {}).get("prosody_preset", "normal"))
        if spans or preset != "normal":
            timed = prosody.match_word_spans(spans, res[0]["words"])
            tmp_wav = dest.with_suffix(".prosody.wav")
            prosody.apply_prosody_to_wav(dest, tmp_wav, timed, preset=preset)
            tmp_wav.replace(dest)
        takes.put(
            tts_val,
            dest,
            TakeEntry(words=res[0]["words"], source=f"build 写法{res[0]['wrap']}", sim=res[0]["sim"]),
        )


@dataclass(frozen=True)
class _ExportCtx:
    """字幕与对照表汇出上下文。"""

    job: J.Job
    lines: list[script.Line]
    timeline: list[dict[str, Any]]
    out: Path
    cfg: dict[str, Any]


def _write_tts_vs_subtitle_tsv(ctx: _ExportCtx, takes: Takes) -> None:
    """写出 tts_vs_subtitle.tsv 对照表。

    Args:
        ctx: 汇出上下文。
        takes: Takes 管理物件。
    """
    headers = [
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
    with open(ctx.out / "tts_vs_subtitle.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(headers)
        for ln, tl in zip(ctx.lines, ctx.timeline, strict=False):
            tts_val = getattr(ln, "tts", "")
            sub_val = getattr(ln, "subtitle", "")
            t = takes.get(tts_val) or {}
            hyp = "".join(x[0] for x in t.get("words", []))
            diff = "是" if tts_val != sub_val else ""
            w.writerow(
                [ln.no, ln.slide, tl["start"], tl["end"], sub_val, tts_val, diff, t.get("source", ""), hyp]
            )


def _export_subtitles_and_meta(ctx: _ExportCtx) -> list[str]:
    """输出字幕与时间对照表格档案。

    Args:
        ctx: 汇出上下文。

    Returns:
        产出的字幕档名列表。
    """
    takes = takes_of(ctx.job)
    sub_lines: list[dict[str, Any]] = []
    for ln, tl in zip(ctx.lines, ctx.timeline, strict=False):
        tts_val = getattr(ln, "tts", "")
        sub_val = getattr(ln, "subtitle", "")
        t = takes.get(tts_val) or {}
        if not t.get("words"):
            clip_path = takes.resolve_clip(str(t.get("clip", "")))
            t["words"] = whisper.words(clip_path, ctx.cfg["whisper"]["model"])
            takes.save()
        sub_lines.append({"text": sub_val, "words": t["words"], **tl})
    fixes_path = Path(__file__).resolve().parent / "traditional_fixes.tsv"
    cues = subtitles.to_traditional(subtitles.build_cues(sub_lines, ctx.cfg), ctx.cfg, fixes_path)
    sub_cfg = ctx.job.cfg.get("subtitles", {})
    want_bilingual = bool(sub_cfg.get("bilingual")) or str(ctx.cfg["voicebox"]["language"]).lower() == "en"
    if want_bilingual:
        bilingual_tsv = ctx.job.work / "script_bilingual.tsv"
        if not bilingual_tsv.is_file():
            try:
                bilingual.translate_job_script_bilingual(
                    ctx.job.name, str(sub_cfg.get("secondary_lang", "zh-TW"))
                )
            except RuntimeError as exc:
                logger.warning("Bilingual auto-translation skipped: %s", exc)
        cues = subtitles.attach_bilingual(cues, bilingual.load_bilingual_map(bilingual_tsv))
    files = subtitles.write_all(cues, ctx.out, ctx.cfg, ctx.job.title)
    _write_tts_vs_subtitle_tsv(ctx, takes)
    (ctx.out / "timeline.json").write_text(
        json.dumps(ctx.timeline, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if ctx.job.script and ctx.job.script.exists():
        shutil.copy2(ctx.job.script, ctx.out / "script.md")
    voc_path = J.vocabulary_path()
    if voc_path.exists():
        shutil.copy2(voc_path, ctx.out / "vocabulary.tsv")
    return files


def _prepare_concat_items(job: J.Job, lines: list[script.Line], takes: Takes) -> list[dict[str, Any]]:
    """检查所有句子音档是否齐备并组装拼接清单。

    Args:
        job: 工作物件。
        lines: 讲稿行列表。
        takes: Takes 管理物件。

    Returns:
        拼接项目字典列表。
    """
    still = [ln.no for ln in lines if not takes.get(getattr(ln, "tts", ""))]
    if still:
        raise RuntimeError(
            f"还有 {len(still)} 句没有音档（{', '.join(map(str, still))}），请先 audition 再 build。"
        )
    return [
        {
            "no": ln.no,
            "slide": ln.slide,
            "brk": ln.brk,
            "clip": takes.resolve_clip(str((takes.get(getattr(ln, "tts", "")) or {}).get("clip", ""))),
        }
        for ln in lines
    ]


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
        takes = takes_of(job)
    items = _prepare_concat_items(job, lines, takes)
    out = job.next_output()
    out.mkdir(parents=True, exist_ok=True)
    lead_in = float(job.cfg.get("voice", {}).get("lead_in_sec", 2.0))
    concat_opts = concat.ConcatOptions(
        pause=cfg["pause"],
        tmp=out / "tmp",
        loudness=cfg["audio"]["loudness"],
        sample_rate=cfg["audio"]["sample_rate"],
        lead_in=max(0.0, lead_in),
    )
    timeline = concat.build(items, out / "narration.wav", concat_opts)
    if (out / "tmp").exists():
        shutil.rmtree(out / "tmp")
    files = _export_subtitles_and_meta(_ExportCtx(job=job, lines=lines, timeline=timeline, out=out, cfg=cfg))
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
    vb = _build_tts_client(cfg)
    vb.check_ready()
    tts_val = getattr(ln, "tts", "")
    res = generate.take(
        vb,
        tts_val,
        (job.work / "gen" / take_key(tts_val), cfg),
        generate.TakeOptions(tries=len(generate.WRAPS), keep_all=True),
    )[:takes_count]
    return "\n".join(samples.save_audition_takes(job, ln, tts_val, res))


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
    return samples.pick_audition_take(job, lines[line_no - 1], take_no, takes_of(job))
