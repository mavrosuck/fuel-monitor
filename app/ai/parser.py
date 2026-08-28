import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schema import BatchInput, BatchParseResult, ParseResult

logger = logging.getLogger(__name__)


class FuelAIParser:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def parse(self, text: str) -> ParseResult:
        """Single-message parsing kept solely for the explicit diagnostic command."""
        for attempt in range(3):
            try:
                response = await self.client.responses.parse(
                    model=self.model,
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    text_format=ParseResult,
                )
                if response.output_parsed is None:
                    raise RuntimeError("OpenAI returned no structured output")
                return response.output_parsed
            except Exception:
                if attempt == 2:
                    raise
                delay = 2**attempt
                logger.warning("OpenAI parsing failed; retrying in %s seconds", delay, exc_info=True)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    async def parse_batch(self, messages: list[BatchInput]) -> BatchParseResult:
        """Makes exactly one OpenAI request for a scheduler batch."""
        if not messages:
            return BatchParseResult(results=[])
        payload = [message.model_dump(mode="json") for message in messages]
        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            text_format=BatchParseResult,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured batch output")
        return response.output_parsed
