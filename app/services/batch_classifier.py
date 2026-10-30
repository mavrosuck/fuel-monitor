"""One-request classification of a scheduler's accumulated text messages."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.ai.schema import BatchInput, BatchParseResult, MessageParseResult
from app.services.keyword_filter import keyword_relevance


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
    local_relevance_reasons: dict[int, str] = field(default_factory=dict)


class BatchClassifier:
    def __init__(self, parser: BatchParser) -> None:
        self.parser = parser

    async def classify(self, messages: list[TextMessage]) -> BatchClassification:
        relevance = {message.source_message_id: keyword_relevance(message.text) for message in messages}
        relevant = [message for message in messages if relevance[message.source_message_id][0]]
        irrelevant_ids = {message.source_message_id for message in messages if not relevance[message.source_message_id][0]}
        reason_codes = {message.source_message_id: relevance[message.source_message_id][1] for message in messages}
        if not relevant:
            return BatchClassification(irrelevant_ids, {}, reason_codes)
        result = await self.parser.parse_batch(
            [BatchInput(source_message_id=item.source_message_id, message_date=item.message_date, text=item.text) for item in relevant]
        )
        valid_ids = {item.source_message_id for item in relevant}
        results = {
            item.source_message_id: item
            for item in result.results
            if item.source_message_id in valid_ids
        }
        return BatchClassification(irrelevant_ids, results, reason_codes)
