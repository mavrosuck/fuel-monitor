"""Bounded retries for operations known to be safe to repeat."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramRetryAfter
from google.genai import errors as gemini_errors

logger = logging.getLogger(__name__)

Result = TypeVar("Result")
RETRY_DELAYS_SECONDS = (2, 5)


def _http_status(error: BaseException) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    return None


def is_transient_gemini_error(error: BaseException) -> bool:
    """Returns true only for request failures that did not produce a response."""
    status = _http_status(error)
    return isinstance(error, (TimeoutError, ConnectionError, OSError, gemini_errors.ServerError)) or status == 429 or (
        status is not None and 500 <= status < 600
    )


def is_safe_telegram_send_retry(error: BaseException) -> bool:
    """429 is rejected before delivery; network/server outcomes may be ambiguous."""
    return isinstance(error, TelegramRetryAfter)


async def retry_async(
    operation: Callable[[], Awaitable[Result]],
    *,
    is_retryable: Callable[[BaseException], bool],
    operation_name: str,
    delays: tuple[int, ...] = RETRY_DELAYS_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Result:
    """Retries a safe operation at most three times with fixed bounded delays."""
    for attempt in range(len(delays) + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt == len(delays) or not is_retryable(exc):
                raise
            delay = delays[attempt]
            logger.warning("%s failed temporarily; retrying in %s seconds", operation_name, delay)
            await sleep(delay)
    raise RuntimeError("unreachable")
