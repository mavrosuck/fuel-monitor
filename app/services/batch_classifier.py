"""One-request classification of a scheduler's accumulated text messages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.ai.schema import BatchInput, BatchParseResult, MessageParseResult
from app.services.keyword_filter import is_keyword_relevant


@dataclass(frozen=True)
class TextMessage:
    source_message_id: int
    message_date: datetime
    text: str


class BatchParser(Protocol):
    async def parse_batch(self, messages: list[BatchInput]) -> BatchParseResult: ...


@dataclass(frozen=True)
class BatchClassification:
    locally_irrelevant_ids: set[int]
    results_by_message_id: dict[int, MessageParseResult]


class BatchClassifier:
    def __init__(self, parser: BatchParser) -> None:
        self.parser = parser

    async def classify(self, messages: list[TextMessage]) -> BatchClassification:
        relevant = [message for message in messages if is_keyword_relevant(message.text)]
        irrelevant_ids = {message.source_message_id for message in messages if message not in relevant}
        if not relevant:
            return BatchClassification(irrelevant_ids, {})
        result = await self.parser.parse_batch(
            [BatchInput(source_message_id=item.source_message_id, message_date=item.message_date, text=item.text) for item in relevant]
        )
        valid_ids = {item.source_message_id for item in relevant}
        results = {
            item.source_message_id: item
            for item in result.results
            if item.source_message_id in valid_ids
        }
        return BatchClassification(irrelevant_ids, results)
