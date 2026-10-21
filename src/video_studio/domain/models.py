"""Domain layer: pure data models with no I/O and no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobSummary:
    """Summary information for a studio job.

    Attributes:
        job_type: Type of the job (extract, dub, generate).
        name: Unique job name.
        title: Human-readable title.
        output_version: Latest output version, or empty.
    """

    job_type: str
    name: str
    title: str
    output_version: str = ""


@dataclass(frozen=True)
class CueItem:
    """A subtitle cue item.

    Attributes:
        start: Start timestamp in seconds.
        end: End timestamp in seconds.
        text: Subtitle text content.
    """

    start: float
    end: float
    text: str
