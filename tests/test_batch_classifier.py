import asyncio
from datetime import UTC, datetime

from app.ai.schema import BatchParseResult, MessageParseResult
from app.services.batch_classifier import BatchClassifier, TextMessage


class CountingParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_batch(self, messages):
        self.calls += 1
        return BatchParseResult(
            results=[
                MessageParseResult(
                    source_message_id=message.source_message_id,
                    classification="QUESTION",
                    has_new_fuel_information=False,
                    reports=[],
                )
                for message in messages
            ]
        )


def test_fifty_relevant_messages_make_one_gemini_call() -> None:
    parser = CountingParser()
    messages = [TextMessage(index, datetime(2026, 8, 28, tzinfo=UTC), f"На АЗС есть АИ-95 {index}") for index in range(50)]
    result = asyncio.run(BatchClassifier(parser).classify(messages))
    assert parser.calls == 1
    assert len(result.results_by_message_id) == 50


def test_zero_messages_make_zero_gemini_calls() -> None:
    parser = CountingParser()
    result = asyncio.run(BatchClassifier(parser).classify([]))
    assert parser.calls == 0
    assert result.results_by_message_id == {}


def test_obvious_local_noise_makes_zero_gemini_calls() -> None:
    parser = CountingParser()
    messages = [TextMessage(1, datetime(2026, 8, 28, tzinfo=UTC), "Доброе утро всем")]
    result = asyncio.run(BatchClassifier(parser).classify(messages))
    assert parser.calls == 0
    assert result.locally_irrelevant_ids == {1}
