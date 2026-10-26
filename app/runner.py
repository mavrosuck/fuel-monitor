"""One-off hourly Fuel Monitor run, suitable for GitHub Actions."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai.parser import FuelAIParser
from app.ai.schema import MessageParseResult
from app.collector.max_collector import MaxCollectionError, MaxCollector
from app.collector.models import CollectedMessage
from app.collector.telegram_client import TelegramCollector
from app.config import get_settings
from app.facts.persistence import NeonFactsPersistence, create_neon_facts_persistence
from app.publisher.telegram_publisher import TelegramPublisher
from app.services.admin_notifier import AdminNotifier
from app.services.aggregator import AggregatedReport, aggregate_reports
from app.services.batch_classifier import BatchClassifier, TextMessage
from app.services.formatter import format_styled_summary
from app.services.health_state import HealthState, HealthStateStore
from app.services.publication_guard import publication_allowed, publishable_fuel_facts
from app.services.published_state import PublishedMessageStore
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)


class LatePublicationError(RuntimeError):
    pass


@dataclass
class RunMetrics:
    telegram_collected: int = 0
    max_collected: int = 0
    publishable_facts: int = 0
    publication: bool = False
    failure_title: str = "Fuel monitor run failed"


def deduplicate_messages(messages: list[CollectedMessage]) -> list[CollectedMessage]:
    """Keeps one copy of repeated text, including reposts between source chats."""
    unique: dict[str, CollectedMessage] = {}
    for message in sorted(messages, key=lambda item: item.message_date):
        fingerprint = re.sub(r"\s+", " ", message.text.casefold()).strip()
        unique[fingerprint] = message
    return list(unique.values())


def source_key(message: CollectedMessage) -> str:
    return f"{message.platform}|{message.source_chat_id}|{message.source_message_id}"


def scheduled_publication_end(now: datetime, timezone: str, interval_hours: int) -> datetime:
    if now.tzinfo is None:
        raise ValueError("publication timestamp must be timezone-aware")
    if interval_hours < 1 or interval_hours > 24:
        raise ValueError("publication interval must be between 1 and 24 hours")
    local_now = now.astimezone(ZoneInfo(timezone))
    slot_hour = local_now.hour - local_now.hour % interval_hours
    return local_now.replace(hour=slot_hour, minute=0, second=0, microsecond=0).astimezone(UTC)


def publication_end(settings, now: datetime) -> datetime:
    explicit_slot = getattr(settings, "publication_slot_end", None)
    end = explicit_slot or scheduled_publication_end(
        now,
        getattr(settings, "timezone", "Asia/Yekaterinburg"),
        getattr(settings, "channel_summary_interval_hours", 3),
    )
    if end.tzinfo is None:
        raise ValueError("publication slot must be timezone-aware")
    end = end.astimezone(UTC)
    expected = scheduled_publication_end(
        end,
        getattr(settings, "timezone", "Asia/Yekaterinburg"),
        getattr(settings, "channel_summary_interval_hours", 3),
    )
    if end != expected:
        raise ValueError("publication slot is not aligned with the Orenburg summary schedule")
    return end


def ensure_publication_is_timely(now: datetime, scheduled_end: datetime, max_delay_minutes: int) -> None:
    if max_delay_minutes < 0:
        raise ValueError("maximum publication delay cannot be negative")
    delay = now.astimezone(UTC) - scheduled_end.astimezone(UTC)
    if delay > timedelta(minutes=max_delay_minutes):
        delay_minutes = int(delay.total_seconds() // 60)
        raise LatePublicationError(
            f"scheduled publication is {delay_minutes} minutes late; "
            f"maximum allowed delay is {max_delay_minutes} minutes"
        )


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
    current = now or datetime.now(UTC)
    dry_run = getattr(settings, "dry_run", False)
    end = (
        current
        if dry_run
        else publication_end(settings, current)
    )
    window_minutes = (
        getattr(settings, "collector_window_minutes", 30)
        if dry_run
        else getattr(settings, "channel_summary_window_minutes", 180)
    )
    start = end - timedelta(minutes=window_minutes)
    notifier = _admin_notifier(settings)
    health_store, health_state = _health_state(settings, current)
    metrics = RunMetrics()
    try:
        slot_already_published = False
        if not dry_run:
            metrics.failure_title = "Scheduled publication skipped because GitHub Actions started late"
            ensure_publication_is_timely(
                current,
                end,
                getattr(settings, "max_publication_delay_minutes", 15),
            )
            published_store = PublishedMessageStore(
                getattr(settings, "published_state_path", ".runtime-state/published-source-messages.json"),
                getattr(settings, "published_state_retention_days", 14),
            )
            if published_store.has_published_slot(published_store.load(), end):
                logger.info("Publication: skipped (slot %s was already published)", end.isoformat())
                slot_already_published = True
        result = None if slot_already_published else await _run_monitor(settings, start, end, metrics)
    except Exception as exc:
        if health_store is not None and health_state is not None:
            try:
                health_store.record_failure(health_state, current)
            except Exception as health_error:
                logger.error("Health failure state was not saved: %s", type(health_error).__name__)
        await notifier.notify_error(metrics.failure_title, current, exc)
        raise
    else:
        if health_store is not None and health_state is not None:
            health_store.record_success(
                health_state,
                current,
                publishable_facts=metrics.publishable_facts,
                telegram_collected=metrics.telegram_collected,
                max_collected=metrics.max_collected,
                publication=metrics.publication,
            )
        return result
    finally:
        await notifier.close()


def _admin_notifier(settings) -> AdminNotifier:
    bot_token = getattr(settings, "bot_token", None)
    notifier = AdminNotifier(
        bot_token.get_secret_value() if bot_token is not None else None,
        getattr(settings, "admin_telegram_chat_id", None),
        getattr(settings, "timezone", "Asia/Yekaterinburg"),
    )
    if not notifier.enabled:
        logger.info("Admin notifications: disabled")
    return notifier


def _health_state(settings, now: datetime) -> tuple[HealthStateStore | None, HealthState | None]:
    path = getattr(settings, "health_state_path", None)
    if path is None:
        return None, None
    store = HealthStateStore(path, getattr(settings, "timezone", "Asia/Yekaterinburg"))
    return store, store.load(now)


async def _run_monitor(settings, start: datetime, end: datetime, metrics: RunMetrics) -> str | None:
    persistence = create_neon_facts_persistence(getattr(settings, "neon_collector_database_url", None))
    try:
        return await _run_monitor_with_optional_persistence(settings, start, end, metrics, persistence)
    finally:
        if persistence is not None:
            await persistence.close()


async def _run_monitor_with_optional_persistence(
    settings,
    start: datetime,
    end: datetime,
    metrics: RunMetrics,
    persistence: NeonFactsPersistence | None,
) -> str | None:
    logger.info("Window: %s -> %s", start.isoformat(), end.isoformat())
    metrics.failure_title = "Telegram collection failed"
    telegram_messages = await TelegramCollector(settings).collect_since(start, end)
    metrics.telegram_collected = len(telegram_messages)
    logger.info("Telegram:")
    for source in settings.source_chats:
        logger.info("  %s: %d", source, sum(message.source_name == source for message in telegram_messages))
    messages = list(telegram_messages)
    if settings.max_enabled:
        metrics.failure_title = "MAX collection failed"
        try:
            max_collection = await MaxCollector(settings).collect_since(start, end)
        except MaxCollectionError as exc:
            logger.error("MAX collection failed; publication blocked: %s", exc)
            raise RuntimeError("MAX collection failed; publication blocked") from exc
        logger.info("MAX:")
        for chat_id in settings.max_source_chat_ids:
            logger.info("  %s: %d", max_collection.chat_titles[chat_id], max_collection.message_counts[chat_id])
        messages.extend(max_collection.messages)
        metrics.max_collected = len(max_collection.messages)
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
    metrics.failure_title = "Gemini request failed after retries"
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
    normalizer = StationNormalizer()
    if persistence is not None:
        await _persist_classified_results(messages, classified.results_by_message_id, normalizer, persistence)
    reports = reports_from_results(messages, classified.results_by_message_id, normalizer)
    aggregated = aggregate_reports(reports)
    metrics.publishable_facts = publishable_fuel_facts(aggregated)
    logger.info("Aggregated stations: %d", len(aggregated))
    logger.info("Publishable fuel facts: %d", metrics.publishable_facts)
    if not publication_allowed(aggregated, settings.min_reports_to_publish):
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
        logger.info("Publication: dry-run (would publish %d fuel facts)", metrics.publishable_facts)
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
        metrics.failure_title = "Telegram publication failed"
        await publisher.publish(summary)
        published_store.record_published(
            published_state,
            source_dates,
            datetime.now(UTC),
            slot_end=end,
        )
        metrics.publication = True
    finally:
        await publisher.close()
    logger.info("Published a report from %d unique FACT messages", len(factual_messages))
    return summary.text


async def _persist_classified_results(
    messages: list[CollectedMessage],
    results: dict[int, MessageParseResult],
    normalizer: StationNormalizer,
    persistence: NeonFactsPersistence,
) -> None:
    for index, message in enumerate(messages, start=1):
        result = results.get(index)
        if result is None:
            continue
        try:
            await persistence.persist(message, result, normalizer)
        except Exception as exc:
            logger.warning("Neon facts persistence disabled for this run: %s", type(exc).__name__)
            return


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
