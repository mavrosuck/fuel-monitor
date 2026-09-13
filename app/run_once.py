import asyncio
import logging
import os
import re
from datetime import UTC, datetime, timedelta

from app.ai.parser import FuelAIParser
from app.ai.schema import BatchInput
from app.collector.telegram_client import create_telegram_client
from app.config import get_settings
from app.publisher.telegram_publisher import TelegramPublisher
from app.services.aggregator import AggregatedReport, aggregate_reports
from app.services.batch_classifier import BatchClassifier, TextMessage
from app.services.formatter import format_summary
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


async def collect_last_hour(client, source_chats: list[str]) -> list[TextMessage]:
    end = datetime.now(UTC)
    start = end - timedelta(hours=1)

    collected: list[tuple[datetime, str]] = []

    for source in source_chats:
        entity = await client.get_entity(source)

        async for message in client.iter_messages(entity):
            message_date = message.date

            if message_date <= start:
                break

            if message_date > end:
                continue

            text = (message.raw_text or "").strip()

            if not text:
                continue

            if message.media:
                continue

            collected.append((message_date, text))

    # Убираем одинаковые репосты между чатами.
    newest_by_text: dict[str, tuple[datetime, str]] = {}

    for message_date, text in sorted(collected, key=lambda item: item[0]):
        newest_by_text[normalize_text(text)] = (message_date, text)

    unique_messages = sorted(
        newest_by_text.values(),
        key=lambda item: item[0],
    )

    # Внутренние ID нужны только для одного запроса Gemini.
    # Они уникальны даже если Telegram message_id совпал в двух разных чатах.
    return [
        TextMessage(
            source_message_id=index,
            message_date=message_date,
            text=text,
        )
        for index, (message_date, text) in enumerate(unique_messages, start=1)
    ]


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = FuelAIParser(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
    )

    classifier = BatchClassifier(parser)
    normalizer = StationNormalizer()

    client = create_telegram_client(settings)
    publisher = TelegramPublisher(
        settings.bot_token.get_secret_value(),
        settings.target_channel,
    )

    try:
        await client.start(phone=settings.telegram_phone)

        logger.info("Connected to Telegram")

        messages = await collect_last_hour(
            client,
            settings.source_chats,
        )

        logger.info(
            "Collected %d unique text messages from the last hour",
            len(messages),
        )

        if not messages:
            logger.info("No messages found; exiting")
            return

        classification = await classifier.classify(messages)

        fact_results = [
            classification.results_by_message_id[message.source_message_id]
            for message in messages
            if message.source_message_id
            in classification.results_by_message_id
            and classification.results_by_message_id[
                message.source_message_id
            ].classification
            == "FACT"
            and classification.results_by_message_id[
                message.source_message_id
            ].has_new_fuel_information
        ]

        logger.info(
            "Gemini found %d unique FACT messages",
            len(fact_results),
        )

        if len(fact_results) < settings.min_reports_to_publish:
            logger.info(
                "Only %d FACT messages; minimum is %d. Publication skipped.",
                len(fact_results),
                settings.min_reports_to_publish,
            )
            return

        reports: list[AggregatedReport] = []

        message_dates = {
            message.source_message_id: message.message_date
            for message in messages
        }

        for parsed in fact_results:
            reported_at = message_dates.get(parsed.source_message_id)

            for item in parsed.reports:
                reports.append(
                    AggregatedReport(
                        station_normalized=normalizer.normalize(
                            item.brand,
                            item.location,
                        ),
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
                        reported_at=reported_at,
                    )
                )

        if not reports:
            logger.info("No concrete fuel reports after parsing; exiting")
            return

        aggregated = aggregate_reports(reports)

        if not aggregated:
            logger.info("Nothing to publish after aggregation")
            return

        now = datetime.now(UTC)

        text = format_summary(
            aggregated,
            now,
            settings.timezone,
        )

        if os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}:
             logger.info(
                "DRY RUN successful: report was created but NOT published"
         )
            return

        message_id = await publisher.publish(text)

        logger.info(
            "Published Telegram report successfully: message_id=%s",
            message_id,
        )

    except Exception:
        logger.exception("Hourly run failed")
        raise

    finally:
        await client.disconnect()
        await publisher.close()


if __name__ == "__main__":
    asyncio.run(main())
