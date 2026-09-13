import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.collector.message_handler import MessageHandler
from app.database.models import Publication
from app.publisher.telegram_publisher import TelegramPublisher
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)


async def run_hourly_job(sessions: async_sessionmaker, publisher: TelegramPublisher, handler: MessageHandler, minimum: int, timezone: str) -> None:
    outcome = await handler.process_pending_batch()
    if outcome.processed_count == 0:
        logger.info("No new messages in hourly batch; AI and publication skipped")
        return
    async with sessions() as session:
        service = ReportService(session, minimum, timezone)
        prepared = await service.build_summary_for_message_ids(outcome.fact_source_message_ids)
        if not prepared:
            return
        text, count, start, end = prepared
        message_id = await publisher.publish(text)
        session.add(Publication(telegram_message_id=message_id, published_at=datetime.now(UTC), period_start=start, period_end=end, reports_count=count, publication_text=text))
        await session.commit()
        logger.info("Published a report with %d source messages", count)
