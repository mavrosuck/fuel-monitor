import asyncio
import json
import logging

from google import genai
from google.genai import types

from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schema import BatchInput, BatchParseResult, ParseResult

logger = logging.getLogger(__name__)


class FuelAIParser:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def parse(self, text: str) -> ParseResult:
        """Classifies one message for local diagnostics."""
        for attempt in range(3):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=ParseResult,
                    ),
                )
                return _parse_response(response, ParseResult)
            except Exception:
                if attempt == 2:
                    raise
                delay = 2**attempt
                logger.warning("Gemini parsing failed; retrying in %s seconds", delay, exc_info=True)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    async def parse_batch(self, messages: list[BatchInput]) -> BatchParseResult:
        """Makes exactly one Gemini request for a non-empty hourly batch."""
        if not messages:
            return BatchParseResult(results=[])
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=json.dumps([item.model_dump(mode="json") for item in messages], ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=BatchParseResult,
            ),
        )
        return _parse_response(response, BatchParseResult)


def _parse_response(response, schema: type[ParseResult] | type[BatchParseResult]):
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return schema.model_validate(parsed)
    if not response.text:
        raise RuntimeError("Gemini returned no structured output")
    return schema.model_validate_json(response.text)
