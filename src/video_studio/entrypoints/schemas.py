"""Pydantic schemas for video-studio FastAPI HTTP endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Service health status")
    app_env: str = Field(description="Active application environment")
    workspace: str = Field(description="Configured workspace directory")


class TextOutputResponse(BaseModel):
    """Standard text output response from service operations."""

    ok: bool = Field(default=True, description="Whether the operation succeeded")
    output: str = Field(description="Human-readable result or report")


class InitJobRequest(BaseModel):
    """Request payload for creating a new job workspace."""

    job_type: str = Field(description="Job type: extract, dub, or generate")
    name: str = Field(description="Job slug using lowercase letters, digits, and hyphens")
    title: str = Field(default="", description="Optional display title")


class ApproveFileRequest(BaseModel):
    """Request payload for approving a draft file from review/ to input/."""

    filename: str = Field(description="Draft file name inside review/, e.g. scenes.toml")


class VocabSetRequest(BaseModel):
    """Request payload for adding or updating a vocabulary entry."""

    key: str = Field(description="Vocabulary key used in script as {{key}}")
    subtitle: str = Field(default="", description="Subtitle display text")
    tts: str = Field(default="", description="Spoken pronunciation text for Voicebox")
    word_type: str = Field(default="", description="Optional category label")
    note: str = Field(default="", description="Optional note")


class DraftScenesRequest(BaseModel):
    """Request payload for drafting storyboard scenes."""

    source: str = Field(default="auto", description="Source mode: auto, pptx, or even")
    force: bool = Field(default=False, description="Overwrite existing review/scenes.toml if true")


class VersionRequest(BaseModel):
    """Optional version selector for narration/video actions."""

    version: str | None = Field(default=None, description="Target output version, e.g. v1")


class MuxVideoRequest(BaseModel):
    """Request payload for muxing an external video with narration."""

    video_file: str = Field(description="Video file path or filename inside input/")
    version: str | None = Field(default=None, description="Target output version")
    reserve_bottom: int = Field(default=0, description="Bottom pixels reserved for callout bar")


class ExtractAudioRequest(BaseModel):
    """Request payload for extracting 48kHz WAV audio from a video."""

    video: str = Field(description="Source video file path")
    out: str | None = Field(default=None, description="Optional output WAV path")
    rate: int = Field(default=48000, description="Sample rate in Hz")
    samples_dir: str | None = Field(default=None, description="Optional directory for voice samples")
