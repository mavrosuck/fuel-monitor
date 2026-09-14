"""One-off hourly Fuel Monitor run, suitable for GitHub Actions."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from app.ai.parser import FuelAIParser
from app.ai.schema import MessageParseResult
from app.collector.max_collector import MaxCollectionError, MaxCollector
from app.collector.models import CollectedMessage
from app.collector.telegram_client import TelegramCollector
from app.config import get_settings
from app.publisher.telegram_publisher import TelegramPublisher
from app.services.aggregator import AggregatedReport, aggregate_reports
from app.services.batch_classifier import BatchClassifier, TextMessage
from app.services.formatter import format_styled_summary
from app.services.published_state import PublishedMessageStore
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)


def deduplicate_messages(messages: list[CollectedMessage]) -> list[CollectedMessage]:
    """Keeps one copy of repeated text, including reposts between source chats."""
    unique: dict[str, CollectedMessage] = {}
    for message in sorted(messages, key=lambda item: item.message_date):
        fingerprint = re.sub(r"\s+", " ", message.text.casefold()).strip()
        unique[fingerprint] = message
    return list(unique.values())


def source_key(message: CollectedMessage) -> str:
    return f"{message.platform}|{message.source_chat_id}|{message.source_message_id}"


def reports_from_results(
    messages: list[CollectedMessage], results: dict[int, MessageParseResult], normalizer: StationNormalizer
) -> list[AggregatedReport]:
    reports: list[AggregatedReport] = []
    for batch_message_id, message in enumerate(messages, start=1):
        parsed = results.get(batch_message_id)
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
                    reported_at=message.message_date,
                    source_keys={source_key(message)},
                )
            )
    return reports


async def run_once(now: datetime | None = None) -> str | None:
    settings = get_settings()
    end = now or datetime.now(UTC)
    start = end - timedelta(hours=1)
    logger.info("Window: %s -> %s", start.isoformat(), end.isoformat())
    telegram_messages = await TelegramCollector(settings).collect_since(start, end)
    logger.info("Telegram:")
    for source in settings.source_chats:
        logger.info("  %s: %d", source, sum(message.source_name == source for message in telegram_messages))
    messages = list(telegram_messages)
    if settings.max_enabled:
        try:
            max_collection = await MaxCollector(settings).collect_since(start, end)
        except MaxCollectionError as exc:
            logger.error("MAX collection failed; publication blocked: %s", exc)
            raise RuntimeError("MAX collection failed; publication blocked") from exc
        logger.info("MAX:")
        for chat_id in settings.max_source_chat_ids:
            logger.info("  %s: %d", max_collection.chat_titles[chat_id], max_collection.message_counts[chat_id])
        messages.extend(max_collection.messages)
    logger.info("Total before dedupe: %d", len(messages))
    messages = deduplicate_messages(messages)
    logger.info("After dedupe: %d", len(messages))
    published_store = PublishedMessageStore(
        getattr(settings, "published_state_path", ".runtime-state/published-source-messages.json"),
        getattr(settings, "published_state_retention_days", 14),
    )
    published_state = published_store.load()
    unpublished_messages = [message for message in messages if source_key(message) not in published_state.published_messages]
    logger.info("Already published source messages skipped: %d", len(messages) - len(unpublished_messages))
    messages = unpublished_messages
    classifier = BatchClassifier(FuelAIParser(settings.gemini_api_key.get_secret_value(), settings.gemini_model))
    classified = await classifier.classify(
        [TextMessage(index, item.message_date, item.text) for index, item in enumerate(messages, start=1)]
    )
    logger.info("Locally relevant: %d", len(messages) - len(classified.locally_irrelevant_ids))
    factual_messages = [
        item
        for index, item in enumerate(messages, start=1)
        if (parsed := classified.results_by_message_id.get(index)) and parsed.has_new_fuel_information
    ]
    logger.info("Gemini FACT messages: %d", len(factual_messages))
    reports = reports_from_results(messages, classified.results_by_message_id, StationNormalizer())
    aggregated = aggregate_reports(reports)
    publishable_fuel_facts = len(aggregated)
    logger.info("Aggregated stations: %d", len(aggregated))
    logger.info("Publishable fuel facts: %d", publishable_fuel_facts)
    if publishable_fuel_facts < settings.min_reports_to_publish:
        logger.info("Publication: skipped (<%d fuel facts)", settings.min_reports_to_publish)
        return None
    summary = format_styled_summary(aggregated, end, settings.timezone)
    if settings.dry_run:
        bot_token = getattr(settings, "bot_token", None)
        if bot_token is not None:
            publisher = TelegramPublisher(bot_token.get_secret_value(), settings.target_channel)
            try:
                await publisher.log_identity()
            finally:
                await publisher.close()
        logger.info("DRY_RUN is enabled; Telegram publication skipped")
        logger.info("Publication: dry-run (would publish %d fuel facts)", publishable_fuel_facts)
        print(summary.text)
        return summary.text
    bot_token = getattr(settings, "bot_token", None)
    if bot_token is None:
        raise RuntimeError("BOT_TOKEN is required unless DRY_RUN=1")
    used_source_keys = set().union(*(report.source_keys for report in aggregated))
    source_dates = {
        source_key(message): message.message_date
        for message in factual_messages
        if source_key(message) in used_source_keys
    }
    publisher = TelegramPublisher(bot_token.get_secret_value(), settings.target_channel)
    try:
        await publisher.publish(summary)
        published_store.record_published(published_state, source_dates, datetime.now(UTC))
    finally:
        await publisher.close()
    logger.info("Published a report from %d unique FACT messages", len(factual_messages))
    return summary.text


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
