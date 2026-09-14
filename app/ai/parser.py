import json

from google import genai
from google.genai import types

from app.ai.prompt import SYSTEM_PROMPT
from app.ai.schema import BatchInput, BatchParseResult, ParseResult
from app.services.retry import is_transient_gemini_error, retry_async


class FuelAIParser:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def parse(self, text: str) -> ParseResult:
        """Classifies one message for local diagnostics."""
        return await self._generate(text, ParseResult)

    async def parse_batch(self, messages: list[BatchInput]) -> BatchParseResult:
        """Makes exactly one Gemini request for a non-empty hourly batch."""
        if not messages:
            return BatchParseResult(results=[])
        return await self._generate(
            json.dumps([item.model_dump(mode="json") for item in messages], ensure_ascii=False),
            BatchParseResult,
        )

    async def _generate(self, contents: str, schema: type[ParseResult] | type[BatchParseResult]):
        async def request():
            return await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )

        response = await retry_async(request, is_retryable=is_transient_gemini_error, operation_name="Gemini request")
        return _parse_response(response, schema)


def _parse_response(response, schema: type[ParseResult] | type[BatchParseResult]):
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return schema.model_validate(parsed)
    if not response.text:
        raise RuntimeError("Gemini returned no structured output")
    return schema.model_validate_json(response.text)
