"""Word-level and sentence-level prosody tags, FFmpeg envelope effects, and 10s A/B/C previews."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SENTENCE_PREFIX_RE = re.compile(r"^\s*\[(fast|slow|loud|soft)\]\s+(.+)$", re.IGNORECASE | re.DOTALL)
_INLINE_TAG_RE = re.compile(
    r"\[(fast|slow|loud|soft)\](.+?)\[/\1\]|\*\*(.+?)\*\*",
    re.IGNORECASE | re.DOTALL,
)

PRESET_SETTINGS: dict[str, tuple[float, float]] = {
    "normal": (1.0, 1.0),
    "energetic": (1.12, 1.15),
    "calm": (0.90, 0.90),
}


@dataclass(frozen=True)
class ProsodySpan:
    """Tagged word or phrase requesting local tempo or volume emphasis.

    Attributes:
        tag: Prosody tag ('loud', 'soft', 'fast', or 'slow').
        phrase: Clean inner text without markup.
    """

    tag: str
    phrase: str


def parse_prosody_tags(text: str) -> tuple[str, list[ProsodySpan]]:
    """Strip inline/sentence prosody markup and extract structured ProsodySpan list.

    Args:
        text: Raw script line (may contain [loud]...[/loud], **...**, or prefix [fast]).

    Returns:
        Tuple of (clean_spoken_text, list of ProsodySpan).
    """
    spans: list[ProsodySpan] = []
    work = text.strip()
    m_pref = _SENTENCE_PREFIX_RE.match(work)
    if m_pref:
        tag = m_pref.group(1).lower()
        work = m_pref.group(2).strip()
        clean_inner, nested = parse_prosody_tags(work)
        spans.append(ProsodySpan(tag=tag, phrase=clean_inner))
        spans.extend(nested)
        return clean_inner, spans

    def _replace(match: re.Match[str]) -> str:
        """Record a ProsodySpan for an inline tag and return the plain inner text.

        Args:
            match: Regex match object for inline prosody markup.

        Returns:
            Plain spoken text without markup.
        """
        if match.group(3) is not None:
            inner = match.group(3).strip()
            spans.append(ProsodySpan(tag="loud", phrase=inner))
            return inner
        tag_name = match.group(1).lower()
        inner = match.group(2).strip()
        spans.append(ProsodySpan(tag=tag_name, phrase=inner))
        return inner

    clean = _INLINE_TAG_RE.sub(_replace, work)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean, spans


def match_word_spans(
    spans: list[ProsodySpan],
    words: list[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    """Align ProsodySpan phrases against Whisper word timestamps.

    Args:
        spans: Extracted ProsodySpan objects.
        words: Whisper word timestamps [(word, start_sec, end_sec), ...].

    Returns:
        List of (tag, start_sec, end_sec) intervals.
    """
    if not spans or not words:
        return []
    timed: list[tuple[str, float, float]] = []
    joined = [(w.strip().lower(), float(s), float(e)) for w, s, e in words if w.strip()]
    for sp in spans:
        target = re.sub(r"\s+", "", sp.phrase).lower()
        if not target:
            continue
        for idx in range(len(joined)):
            first_tok = re.sub(r"\s+", "", joined[idx][0])
            if not (target.startswith(first_tok) or first_tok in target):
                continue
            acc = ""
            for j in range(idx, len(joined)):
                acc += re.sub(r"\s+", "", joined[j][0])
                if acc == target or (j == idx and target in acc):
                    timed.append((sp.tag, joined[idx][1], joined[j][2]))
                    break
                if len(acc) > len(target) + 4:
                    break
            else:
                continue
            break
    return timed


def _build_volume_expr(timed_spans: list[tuple[str, float, float]], base_gain: float) -> str:
    """Build an FFmpeg dynamic volume expression for word-level loud/soft emphasis.

    Args:
        timed_spans: Timed (tag, start, end) intervals.
        base_gain: Overall preset gain multiplier.

    Returns:
        FFmpeg volume filter string.
    """
    expr = f"{base_gain:.2f}"
    for tag, start, end in timed_spans:
        if tag == "loud":
            mult = base_gain * 1.48
        elif tag == "soft":
            mult = base_gain * 0.58
        else:
            continue
        expr = f"if(between(t,{start:.3f},{end:.3f}),{mult:.2f},{expr})"
    return f"volume='{expr}':eval=frame"


def apply_prosody_to_wav(
    src_wav: Path,
    dst_wav: Path,
    timed_spans: list[tuple[str, float, float]],
    preset: str = "normal",
) -> Path:
    """Apply preset tempo/gain and word-level loud/soft emphasis to a WAV file.

    Args:
        src_wav: Input WAV path.
        dst_wav: Output WAV path.
        timed_spans: Word-level (tag, start, end) intervals.
        preset: Global prosody preset ('normal', 'energetic', or 'calm').

    Returns:
        Output WAV path.

    Raises:
        RuntimeError: If ffmpeg fails.
    """
    tempo, gain = PRESET_SETTINGS.get(preset, (1.0, 1.0))
    if any(t == "fast" for t, _, _ in timed_spans) and tempo == 1.0:
        tempo = 1.15
    elif any(t == "slow" for t, _, _ in timed_spans) and tempo == 1.0:
        tempo = 0.88

    filters: list[str] = [_build_volume_expr(timed_spans, gain)]
    if abs(tempo - 1.0) > 0.01:
        filters.append(f"atempo={tempo:.2f}")

    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src_wav), "-af", ",".join(filters), str(dst_wav)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg prosody filter failed: {proc.stderr[-300:]}")
    return dst_wav
