"""Domain layer: pure data models with no I/O and no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GreetingRequest:
    """A request to greet one user.

    Attributes:
        user_name: Name typed by the user (may contain surrounding spaces).
    """

    user_name: str


@dataclass(frozen=True)
class GreetingResult:
    """The greeting produced by the service layer.

    Attributes:
        message: Final greeting text.
        environment: Environment the greeting was produced in.
    """

    message: str
    environment: str
