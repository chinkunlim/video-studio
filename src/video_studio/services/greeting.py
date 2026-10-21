"""Services layer: business logic that depends only on `config` and `domain`."""

from __future__ import annotations

import logging

from video_studio.config.settings import AppConfig
from video_studio.domain.models import GreetingRequest, GreetingResult

logger = logging.getLogger(__name__)


def create_greeting(request: GreetingRequest, config: AppConfig) -> GreetingResult:
    """Build a greeting for the requested user.

    Args:
        request: The user's greeting request; blank names fall back to "World".
        config: Application settings (provides the environment name).

    Returns:
        The greeting message and the environment it was produced in.
    """
    clean_name = request.user_name.strip() or "World"
    logger.info("greeting user=%r env=%s", clean_name, config.app_env)
    return GreetingResult(message=f"Hello, {clean_name}!", environment=config.app_env)
