"""Local Ollama HTTP adapter for script drafting and bilingual subtitle translation."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def is_ollama_reachable(base_url: str, timeout: float = 2.0) -> bool:
    """Check whether the local Ollama server responds on /api/tags.

    Args:
        base_url: Base URL of the local Ollama server.
        timeout: Connection timeout in seconds.

    Returns:
        True if Ollama responds with HTTP 200.
    """
    try:
        res = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        return res.status_code == 200
    except httpx.HTTPError:
        return False


def generate_text(
    prompt: str,
    base_url: str,
    model: str = "qwen2.5:latest",
    timeout: float = 120.0,
) -> str:
    """Generate text from a local Ollama model via /api/generate.

    Args:
        prompt: Prompt text sent to the model.
        base_url: Local Ollama base URL (127.0.0.1).
        model: Model tag installed in Ollama.
        timeout: Request timeout in seconds.

    Returns:
        Generated response text stripped of leading/trailing whitespace.

    Raises:
        ProviderError: If the HTTP request fails or returns an empty response.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    logger.info("Calling Ollama generate: model=%s url=%s", model, url)
    try:
        res = httpx.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        res.raise_for_status()
        data = res.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Ollama request failed ({model}): {exc}") from exc

    text = str(data.get("response", "")).strip()
    if not text:
        raise RuntimeError(f"Ollama returned empty response for model {model}")
    return text
