"""One-off hourly Fuel Monitor run, suitable for GitHub Actions."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from app.ai.parser import FuelAIParser
from app.ai.schema import MessageParseResult
from app.collector.telegram_client import CollectedMessage, TelegramCollector
from app.config import get_settings
from app.publisher.telegram_publisher import TelegramPublisher
from app.services.aggregator import AggregatedReport, aggregate_reports
from app.services.batch_classifier import BatchClassifier, TextMessage
from app.services.formatter import format_summary
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)


def deduplicate_messages(messages: list[CollectedMessage]) -> list[CollectedMessage]:
    """Keeps one copy of repeated text, including reposts between source chats."""
    unique: dict[str, CollectedMessage] = {}
    for message in sorted(messages, key=lambda item: item.date):
        fingerprint = re.sub(r"\s+", " ", message.text.casefold()).strip()
        unique[fingerprint] = message
    return list(unique.values())


def reports_from_results(
    messages: list[CollectedMessage], results: dict[int, MessageParseResult], normalizer: StationNormalizer
) -> list[AggregatedReport]:
    reports: list[AggregatedReport] = []
    for message in messages:
        parsed = results.get(message.source_message_id)
        if not parsed or not parsed.has_new_fuel_information:
            continue
        for item in parsed.reports:
            reports.append(
                AggregatedReport(
                    station_normalized=normalizer.normalize(item.brand, item.location),
                    brand=item.brand,
                    location=item.location,
                    fuel_available=item.fuel_available,
                    fuel_unavailable=item.fuel_unavailable,
                    price_text=item.price_text,
                    observed_time=item.observed_time,
                    queue_text=item.queue_text,
                    queue_cars=item.queue_cars,
                    restrictions=item.restrictions,
                    station_state=item.station_state,
                    additional_info=item.additional_info,
                    reported_at=message.date,
                )
            )
    return reports


async def run_once(now: datetime | None = None) -> str | None:
    settings = get_settings()
    end = now or datetime.now(UTC)
    start = end - timedelta(hours=1)
    collector = TelegramCollector(settings)
    messages = deduplicate_messages(await collector.collect_since(start))
    logger.info("Collected %d unique text messages in the hourly window", len(messages))
    classifier = BatchClassifier(FuelAIParser(settings.gemini_api_key.get_secret_value(), settings.gemini_model))
    classified = await classifier.classify(
        [TextMessage(item.source_message_id, item.date, item.text) for item in messages]
    )
    factual_messages = [
        item
        for item in messages
        if (parsed := classified.results_by_message_id.get(item.source_message_id)) and parsed.has_new_fuel_information
    ]
    if len(factual_messages) < settings.min_reports_to_publish:
        logger.info("Only %d unique FACT messages; publication skipped", len(factual_messages))
        return None
    reports = reports_from_results(messages, classified.results_by_message_id, StationNormalizer())
    summary = format_summary(aggregate_reports(reports), end, settings.timezone)
    if settings.dry_run:
        logger.info("DRY_RUN is enabled; Telegram publication skipped")
        print(summary)
        return summary
    if settings.bot_token is None:
        raise RuntimeError("BOT_TOKEN is required unless DRY_RUN=1")
    publisher = TelegramPublisher(settings.bot_token.get_secret_value(), settings.target_channel)
    try:
        await publisher.publish(summary)
    finally:
        await publisher.close()
    logger.info("Published a report from %d unique FACT messages", len(factual_messages))
    return summary


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
