import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.models import FuelReport, SourceMessage
from app.services.batch_classifier import BatchClassifier, TextMessage
from app.services.keyword_filter import is_keyword_relevant
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchProcessOutcome:
    processed_count: int
    fact_source_message_ids: list[int]


class MessageHandler:
    def __init__(self, sessions: async_sessionmaker, classifier: BatchClassifier, normalizer: StationNormalizer) -> None:
        self.sessions, self.classifier, self.normalizer = sessions, classifier, normalizer

    async def process(self, chat_id: int, username: str | None, message_id: int, text: str, message_date) -> None:
        if not text.strip():
            return
        async with self.sessions() as session:
            source = SourceMessage(chat_id=chat_id, chat_username=username, telegram_message_id=message_id, message_text=text, message_date=message_date, is_keyword_relevant=is_keyword_relevant(text))
            session.add(source)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return
            # OpenAI is intentionally not called by the real-time collector.

    async def store_backfill(self, chat_id: int, username: str | None, message_id: int, text: str, message_date) -> bool:
        """Сохраняет сообщение, полученное при стартовой проверке, без AI-разбора.

        Исторические сообщения нужны для диагностики и дедупликации, но не должны
        становиться частью следующей сводки. Поэтому они считаются обработанными
        и неинформационными. Новые сообщения всё равно придут через NewMessage.
        """
        if not text.strip():
            return False
        async with self.sessions() as session:
            source = SourceMessage(
                chat_id=chat_id,
                chat_username=username,
                telegram_message_id=message_id,
                message_text=text,
                message_date=message_date,
                is_keyword_relevant=is_keyword_relevant(text),
                is_ai_processed=True,
                has_new_fuel_information=False,
            )
            session.add(source)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def process_pending_batch(self) -> BatchProcessOutcome:
        """Processes all accumulated text with at most one OpenAI request."""
        async with self.sessions() as session:
            pending = (
                await session.scalars(
                    select(SourceMessage)
                    .where(SourceMessage.is_ai_processed.is_(False))
                    .order_by(SourceMessage.message_date)
                )
            ).all()
            if not pending:
                return BatchProcessOutcome(0, [])
            classified = await self.classifier.classify(
                [TextMessage(item.id, item.message_date, item.message_text) for item in pending]
            )
            fact_ids: list[int] = []
            for source in pending:
                source.is_ai_processed = True
                source.has_new_fuel_information = False
                source.is_keyword_relevant = source.id not in classified.locally_irrelevant_ids
                parsed = classified.results_by_message_id.get(source.id)
                if parsed is None:
                    continue
                source.has_new_fuel_information = parsed.has_new_fuel_information
                if parsed.has_new_fuel_information:
                    fact_ids.append(source.id)
                self._store_reports(session, source, parsed.reports)
            await session.commit()
            logger.info("Hourly batch processed: total=%d facts=%d", len(pending), len(fact_ids))
            return BatchProcessOutcome(len(pending), fact_ids)

    def _store_reports(self, session, source: SourceMessage, reports) -> None:
        for item in reports:
            session.add(FuelReport(source_message_id=source.id, station_brand=item.brand, station_location=item.location, station_normalized=self.normalizer.normalize(item.brand, item.location), fuel_available=item.fuel_available, fuel_unavailable=item.fuel_unavailable, price_text=item.price_text, observed_time=item.observed_time, queue_text=item.queue_text, queue_cars=item.queue_cars, restrictions=item.restrictions, station_state=item.station_state, additional_info=item.additional_info, reported_at=source.message_date))

    async def _parse_and_store(self, session, source: SourceMessage) -> None:
        """Compatibility method for old callers; normal scheduler uses batch processing."""
        try:
            classified = await self.classifier.classify([TextMessage(source.id, source.message_date, source.message_text)])
        except Exception:
            logger.exception("AI parsing failed for message %s", source.telegram_message_id)
            await session.rollback()
            return
        source.is_ai_processed = True
        parsed = classified.results_by_message_id.get(source.id)
        source.has_new_fuel_information = bool(parsed and parsed.has_new_fuel_information)
        if parsed:
            self._store_reports(session, source, parsed.reports)
        await session.commit()
