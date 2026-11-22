"""Voice sample pre-caching and 10-second prosody preview generation helpers."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from video_studio.config.settings import load_config as load_app_config
from video_studio.services.common import job as J
from video_studio.services.narrate.core import audio, generate, prosody, script, whisper
from video_studio.services.narrate.core.edge_tts_client import DEFAULT_EDGE_VOICE, EdgeTTSClient
from video_studio.services.narrate.core.takes import TakeEntry, Takes
from video_studio.services.narrate.core.takes import key as take_key
from video_studio.services.narrate.core.voicebox import Voicebox

logger = logging.getLogger(__name__)

VOICE_SAMPLE_TEXTS: dict[str, str] = {
    "en": ("Welcome to today's presentation. Let's walk through the key findings and practical insights."),
    "zh": "大家好，歡迎來到今天的簡報分享。接下來我們將一起了解核心重點與實務應用。",
    "ja": "皆さん、こんにちは。本日のプレゼンテーションへようこそ。重要なポイントをご紹介します。",
    "ko": "안녕하세요. 오늘 발표에 오신 것을 환영합니다. 핵심 내용을 함께 살펴보겠습니다.",
}


def build_tts_client(cfg: dict[str, Any]) -> Voicebox | EdgeTTSClient:
    """Create a Voicebox or edge-tts client from a narrate configuration dictionary.

    Args:
        cfg: Narrate configuration dictionary.

    Returns:
        Initialized TTS client instance.
    """
    engine = cfg.get("tts", {}).get("engine", "voicebox")
    if engine == "edge-tts":
        return EdgeTTSClient(cfg.get("tts", {}))
    return Voicebox(cfg["voicebox"])


def voice_sample_cache_dir() -> Path:
    """Return the DATA_DIR directory storing pre-cached 10s voice/prosody samples.

    Returns:
        Path to DATA_DIR/cache/voice_samples.
    """
    return load_app_config().data_dir / "cache" / "voice_samples"


def _safe_voice_key(voice_key: str) -> str:
    """Sanitize a voice/profile identifier for safe filesystem caching.

    Args:
        voice_key: Raw voice or profile name.

    Returns:
        Filesystem-safe token string.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "_", voice_key.strip() or "default")


def get_cached_voice_samples(voice_key: str) -> dict[str, str]:
    """Return cached 10s sample filenames for a voice key if all 3 presets exist.

    Args:
        voice_key: Edge-TTS voice ID or Voicebox profile name.

    Returns:
        Mapping of preset ('normal', 'energetic', 'calm') to filename, or empty dict if incomplete.
    """
    cdir = voice_sample_cache_dir()
    safe = _safe_voice_key(voice_key)
    out: dict[str, str] = {}
    for preset in ("normal", "energetic", "calm"):
        fname = f"{safe}_{preset}.wav"
        if not (cdir / fname).is_file():
            return {}
        out[preset] = fname
    return out


def _apply_presets(base_wav: Path, out_dir: Path, prefix: str, timed: list[Any]) -> dict[str, str]:
    """Render normal, energetic, and calm WAV variants from a 10s base WAV.

    Args:
        base_wav: Path to 10s base WAV file.
        out_dir: Target output directory.
        prefix: Filename prefix (e.g. `prosody_` or `<safe_voice>_`).
        timed: Timed prosody spans for word-level modulation.

    Returns:
        Mapping of preset name to generated filename.
    """
    out: dict[str, str] = {}
    for preset in ("normal", "energetic", "calm"):
        fname = f"{prefix}{preset}.wav"
        prosody.apply_prosody_to_wav(base_wav, out_dir / fname, timed, preset=preset)
        out[preset] = fname
    return out


def ensure_voice_samples(
    voice_key: str,
    language: str = "zh",
    engine: str = "edge-tts",
    rate: str = "+0%",
) -> dict[str, str]:
    """Ensure 10s normal/energetic/calm cached preview WAVs exist for a specific voice.

    Args:
        voice_key: Edge-TTS voice ID or Voicebox profile name.
        language: Language code ('en', 'zh', 'ja', 'ko').
        engine: TTS engine ('edge-tts' or 'voicebox').
        rate: Edge-TTS rate string (e.g. '+0%', '-10%').

    Returns:
        Mapping of preset name to cached filename inside DATA_DIR/cache/voice_samples.
    """
    cached = get_cached_voice_samples(voice_key)
    if cached:
        return cached
    cdir = voice_sample_cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    safe = _safe_voice_key(voice_key)
    lang_code = language.split("-")[0].lower()
    text = VOICE_SAMPLE_TEXTS.get(lang_code, VOICE_SAMPLE_TEXTS["zh"])
    cfg: dict[str, Any] = {
        "voicebox": {"url": load_app_config().voicebox_url, "profile": voice_key, "language": lang_code},
        "tts": {"engine": engine, "edge_voice": voice_key or DEFAULT_EDGE_VOICE, "edge_rate": rate},
    }
    client = build_tts_client(cfg)
    client.check_ready()
    raw_tmp = cdir / f"_{safe}_raw.wav"
    base_wav = cdir / f"_{safe}_base10s.wav"
    raw_tmp.write_bytes(client.generate(text, lang_code))
    audio.cut(raw_tmp, base_wav, audio.CutOptions(start=0.0, end=10.0, rate=24000))
    out = _apply_presets(base_wav, cdir, f"{safe}_", [])
    raw_tmp.unlink(missing_ok=True)
    base_wav.unlink(missing_ok=True)
    logger.info("已預先快取聲線試聽範本：%s (%s)", voice_key, lang_code)
    return out


def render_prosody_preview(job: J.Job, cfg: dict[str, Any], text: str) -> dict[str, str]:
    """Synthesize and render 10s normal/energetic/calm prosody previews into needs_review/<job>/.

    Args:
        job: Target Job instance.
        cfg: Loaded narrate configuration dictionary.
        text: Sample sentence(s) possibly containing prosody markup tags.

    Returns:
        Mapping of preset name ('normal', 'energetic', 'calm') to review filename.
    """
    clean_text, spans = prosody.parse_prosody_tags(text)
    client = build_tts_client(cfg)
    client.check_ready()
    raw_bytes = client.generate(clean_text, cfg["voicebox"].get("language"))
    job.review.mkdir(parents=True, exist_ok=True)
    base_wav = job.work / "prosody_base_10s.wav"
    base_wav.parent.mkdir(parents=True, exist_ok=True)
    raw_tmp = job.work / "prosody_raw.wav"
    raw_tmp.write_bytes(raw_bytes)
    audio.cut(raw_tmp, base_wav, audio.CutOptions(start=0.0, end=10.0, rate=24000))
    words = whisper.words(base_wav, cfg["whisper"]["model"])
    timed = prosody.match_word_spans(spans, words)
    return _apply_presets(base_wav, job.review, "prosody_", timed)


def save_audition_takes(job: J.Job, ln: script.Line, tts_val: str, res: list[dict[str, Any]]) -> list[str]:
    """Save candidate audition audio clips and takes.json metadata under needs_review/<job>/audition/.

    Args:
        job: Target Job instance.
        ln: Parsed script line object.
        tts_val: Spoken text key for TTS.
        res: Generated take candidate dictionaries.

    Returns:
        Formatted summary output lines for CLI/API response.
    """
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
                "file": str(dest.relative_to(job.review)),
                "words": r["words"],
                "sim": r["sim"],
                "wrap": r["wrap"],
                "hyp": r["hyp"],
            }
        )
        lines_out.append(f"  {dest}  ｜{r['hyp']}")
    (dest_dir / "takes.json").write_text(
        json.dumps({"tts": tts_val, "takes": meta}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines_out.append(f"\n听完后选用：uv run narrate/narrate.py pick {job.name} {ln.no} <编号>")
    return lines_out


def pick_audition_take(job: J.Job, ln: script.Line, take_no: int, takes: Takes) -> str:
    """Lock a chosen audition candidate WAV for a script line into Takes.

    Args:
        job: Target Job instance.
        ln: Parsed script line object.
        take_no: 1-based candidate take index.
        takes: Takes registry for the job.

    Returns:
        Confirmation summary string.
    """
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
    src_take = job.review / chosen["file"]
    if not src_take.exists():
        src_take = job.dir / chosen["file"]
    shutil.copy2(src_take, dest)
    takes.put(
        tts_val,
        dest,
        TakeEntry(
            words=chosen["words"], source=f"audition 第{take_no}个", sim=chosen.get("sim"), locked=True
        ),
    )
    return f"第 {ln.no} 行改用第 {take_no} 个版本，并锁定。下次 build 会用它。"
