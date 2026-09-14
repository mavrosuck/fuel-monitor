import asyncio

import pytest

from app.services.retry import is_transient_gemini_error, retry_async


def test_transient_retry_succeeds_on_third_attempt() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "ok"

    async def no_sleep(_delay: float) -> None:
        return None

    assert asyncio.run(retry_async(operation, is_retryable=is_transient_gemini_error, operation_name="test", delays=(0, 0), sleep=no_sleep)) == "ok"
    assert attempts == 3


def test_permanent_errors_are_not_retried() -> None:
    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("invalid request")

    with pytest.raises(ValueError, match="invalid request"):
        asyncio.run(retry_async(operation, is_retryable=is_transient_gemini_error, operation_name="test", delays=(0, 0)))
    assert attempts == 1
