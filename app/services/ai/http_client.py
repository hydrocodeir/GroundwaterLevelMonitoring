from __future__ import annotations

import json
import socket
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from app.services.ai.errors import (
    AIForbiddenError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)


def _extract_error_message(body: str, fallback: str) -> str:
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if message:
                    return str(message)
            message = payload.get("message")
            if message:
                return str(message)
    except Exception:
        pass
    return fallback


def post_chat_completion(
    *,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> str:
    request = urlrequest.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urlerror.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        message = _extract_error_message(
            body,
            f"{provider} API request failed with HTTP {error.code}.",
        )
        if error.code == 429:
            raise AIRateLimitError(message, provider) from error
        if error.code == 403 and message.strip().lower() == "forbidden":
            message = (
                f"{provider} rejected access with HTTP 403. "
                "The API key is configured, but this account or network location "
                "is not permitted to use the provider."
            )
            raise AIForbiddenError(message, provider) from error
        raise AIProviderError(message, provider) from error
    except urlerror.URLError as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise AITimeoutError(
                f"{provider} API request timed out.",
                provider,
            ) from error
        raise AIProviderError(
            f"{provider} API request failed: {reason}",
            provider,
        ) from error

    try:
        response_payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AIProviderError(
            f"{provider} returned invalid JSON.",
            provider,
        ) from error

    if isinstance(response_payload, dict) and response_payload.get("error"):
        error_block = response_payload["error"]
        if isinstance(error_block, dict):
            message = error_block.get("message") or f"{provider} returned an error."
        else:
            message = str(error_block)
        raise AIProviderError(message, provider)

    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIProviderError(
            f"{provider} returned no completion choices.",
            provider,
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise AIProviderError(
            f"{provider} returned an invalid response message.",
            provider,
        )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AIProviderError(
            f"{provider} returned an empty completion.",
            provider,
        )
    return content.strip()
