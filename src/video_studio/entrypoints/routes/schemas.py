"""Shared Pydantic schemas, validation regexes, and job.toml serializer for Studio routes."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class JobConfigUpdate(BaseModel):
    """Editable fields of job.toml exposed in the Web UI."""

    title: str = Field(default="", description="Display title")
    visual_mode: str = Field(default="auto", description="auto | poster | pptx-export | html | none")
    voice_engine: str = Field(default="voicebox", description="voicebox | edge-tts")
    voice_language: str = Field(default="zh", description="Voice/TTS language code (zh, en, ja, etc.)")
    voice_profile: str = Field(default="My Voice", description="Voicebox profile name")
    edge_voice: str = Field(default="zh-TW-HsiaoChenNeural", description="edge-tts voice name")
    edge_rate: str = Field(default="+0%", description="edge-tts speaking rate")
    prosody_preset: str = Field(default="normal", description="normal | energetic | calm")
    lead_in_sec: float = Field(default=2.0, ge=0.0, le=10.0, description="Silence before speaking in seconds")
    whisper_model: str = Field(default="small", description="Whisper model (tiny, base, small, medium)")
    opencc_mode: str = Field(default="s2tw", description="OpenCC conversion (s2tw, s2t, none)")
    subtitles_formats: list[str] = Field(default_factory=lambda: ["youtube", "powerpoint", "vlc"])
    burn_in: bool = Field(default=True, description="Burn subtitles into video_subtitled.mp4")
    bilingual_subtitles: bool = Field(default=False, description="Enable dual-language subtitles")
    subtitle_secondary_lang: str = Field(default="zh-TW", description="Secondary subtitle language")
    subtitle_font_size: int = Field(default=22, description="Burn-in subtitle font size")
    avatar_engine: str = Field(default="none", description="none | lightweight | sadtalker")
    avatar_image: str = Field(default="", description="Portrait image filename inside input/")
    avatar_position: str = Field(default="bottom-right", description="Avatar PiP corner position")
    width: int = Field(default=1920, ge=320, le=3840, description="Output video width in pixels")
    height: int = Field(default=1080, ge=320, le=3840, description="Output video height in pixels")
    fps: int = Field(default=30, description="Output video FPS")
    loudness: float = Field(default=-16.0, description="Target LUFS (-30 to -8)")
    backup_dir: str = Field(default="", description="Optional backup output directory")
    inputs: dict[str, str] = Field(default_factory=dict, description="Input filename mappings")


class TextContentUpdate(BaseModel):
    """Request payload for saving script.md or brief.md."""

    content: str = Field(description="Markdown file content")
    auto_format: bool = Field(default=False, description="Auto-split sentences when saving script.md")


class PlanRequest(BaseModel):
    """Request payload for starting an Antigravity agy CLI planning run."""

    instruction: str = Field(default="", description="User planning instruction or follow-up")
    mode: str = Field(default="html", description="html | poster")
    model: str = Field(default="", description="Optional agy CLI model ID")
    follow_poster_design: bool = Field(default=True, description="Preserve uploaded poster design")
    thread_mode: str = Field(default="continue", description="continue | new")
    history: list[dict[str, str]] = Field(default_factory=list, description="Recent chat turns")


class VoiceSamplePrewarmRequest(BaseModel):
    """Request payload for pre-generating 10s voice/prosody sample previews."""

    voice: str = Field(description="Edge-TTS voice ID or Voicebox profile")
    language: str = Field(default="zh", description="Language code (en, zh, ja, ko)")
    engine: str = Field(default="edge-tts", description="edge-tts | voicebox")
    rate: str = Field(default="+0%", description="Edge-TTS rate string")


class EnvUpdateRequest(BaseModel):
    """Editable non-secret environment settings."""

    values: dict[str, str] = Field(description="Allowed .env key/value pairs")


class ScriptDraftRequest(BaseModel):
    """Request payload for AI script generation into needs_review/<job>/script.md."""

    instruction: str = Field(default="", description="Topic or prompt for the script")
    language: str = Field(default="zh", description="Spoken language code")
    duration_sec: int = Field(default=90, description="Target duration in seconds")
    model: str = Field(default="", description="Optional agy CLI model ID")


class BilingualRequest(BaseModel):
    """Request payload for translating script.md into bilingual subtitles."""

    target_lang: str = Field(default="zh-TW", description="Target secondary subtitle language")
    model: str = Field(default="", description="Optional agy CLI model ID")


class AvatarApplyRequest(BaseModel):
    """Request payload for compositing an avatar presenter onto the rendered video."""

    engine: str = Field(default="lightweight", description="lightweight | sadtalker")
    position: str = Field(default="bottom-right", description="Corner placement")
    image_name: str = Field(default="", description="Optional portrait image filename inside input/")


class SnapshotCreateRequest(BaseModel):
    """Request payload for saving a manual needs_review/<job>/ draft snapshot."""

    note: str = Field(default="手動備份", description="Snapshot description")


class ProsodyPreviewRequest(BaseModel):
    """Request payload for generating 10-second prosody A/B/C previews."""

    sample_text: str = Field(default="", description="Optional sample text with [loud]/[fast] tags")


def toml_str(val: str) -> str:
    """Escape a string as a TOML basic string.

    Args:
        val: Raw string value.

    Returns:
        Quoted and escaped TOML string.
    """
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _format_toml_section(header: str, entries: list[tuple[str, str]]) -> list[str]:
    """Format a TOML section header and its key-value lines.

    Args:
        header: Section name without brackets.
        entries: Ordered list of (key, formatted_toml_value) pairs.

    Returns:
        List of formatted TOML lines including a trailing blank line.
    """
    return [f"[{header}]", *(f"{k} = {v}" for k, v in entries), ""]


def _voice_and_subtitle_sections(req: JobConfigUpdate) -> list[tuple[str, list[tuple[str, str]]]]:
    """Build voice, whisper, and subtitles TOML section entries.

    Args:
        req: Validated JobConfigUpdate payload.

    Returns:
        List of (section_name, entries) tuples.
    """
    fmts = ", ".join(toml_str(f) for f in req.subtitles_formats)
    return [
        (
            "voice",
            [
                ("engine", toml_str(req.voice_engine)),
                ("language", toml_str(req.voice_language)),
                ("profile", toml_str(req.voice_profile)),
                ("edge_voice", toml_str(req.edge_voice)),
                ("edge_rate", toml_str(req.edge_rate)),
                ("prosody_preset", toml_str(req.prosody_preset)),
                ("lead_in_sec", str(req.lead_in_sec)),
            ],
        ),
        ("whisper", [("model", toml_str(req.whisper_model)), ("opencc_mode", toml_str(req.opencc_mode))]),
        (
            "subtitles",
            [
                ("formats", f"[{fmts}]"),
                ("burn_in", "true" if req.burn_in else "false"),
                ("bilingual", "true" if req.bilingual_subtitles else "false"),
                ("secondary_lang", toml_str(req.subtitle_secondary_lang)),
                ("font_size", str(req.subtitle_font_size)),
            ],
        ),
    ]


def serialize_job_toml(job_type: str, req: JobConfigUpdate) -> str:
    """Render a clean job.toml string from structured web form fields.

    Args:
        job_type: Fixed job type ('extract', 'dub', 'generate').
        req: Validated JobConfigUpdate payload.

    Returns:
        Formatted job.toml text.
    """
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("job", [("type", toml_str(job_type)), ("title", toml_str(req.title))]),
        ("inputs", [(k, toml_str(v)) for k, v in req.inputs.items()]),
        ("visual", [("mode", toml_str(req.visual_mode))]),
        *_voice_and_subtitle_sections(req),
        (
            "avatar",
            [
                ("engine", toml_str(req.avatar_engine)),
                ("image", toml_str(req.avatar_image)),
                ("position", toml_str(req.avatar_position)),
            ],
        ),
        (
            "output",
            [
                ("width", str(req.width)),
                ("height", str(req.height)),
                ("fps", str(req.fps)),
                ("loudness", str(req.loudness)),
                ("backup_dir", toml_str(req.backup_dir)),
            ],
        ),
    ]
    lines: list[str] = []
    for header, entries in sections:
        lines.extend(_format_toml_section(header, entries))
    return "\n".join(lines)
