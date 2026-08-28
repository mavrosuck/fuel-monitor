import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FuelReport, Publication, SourceMessage, SystemState
from app.services.aggregator import AggregatedReport, aggregate_reports
from app.services.formatter import format_summary

logger = logging.getLogger(__name__)


def unique_information_messages(messages: list[SourceMessage]) -> list[SourceMessage]:
    """Keeps the newest copy of an identical report, including cross-chat reposts."""
    newest_by_text: dict[str, SourceMessage] = {}
    for message in sorted(messages, key=lambda item: item.message_date):
        fingerprint = re.sub(r"\s+", " ", message.message_text.casefold()).strip()
        newest_by_text[fingerprint] = message
    return list(newest_by_text.values())


def filter_information_messages(messages: list[SourceMessage], start: datetime, end: datetime) -> list[SourceMessage]:
    """Filters out backfill, non-facts and records outside this hourly window."""
    eligible = [
        message
        for message in messages
        if start < message.message_date <= end
        and message.is_ai_processed
        and message.has_new_fuel_information
    ]
    return unique_information_messages(eligible)


def publication_allowed(messages: list[SourceMessage], minimum: int) -> bool:
    return len(messages) >= minimum


class ReportService:
    def __init__(self, session: AsyncSession, minimum: int, timezone: str) -> None:
        self.session, self.minimum, self.timezone = session, minimum, timezone

    async def _period_start(self, end: datetime) -> datetime:
        """Returns the current one-hour window, never preceding the initial cutoff."""
        start = end - timedelta(hours=1)
        last = await self.session.scalar(select(Publication).order_by(Publication.published_at.desc()).limit(1))
        if last:
            return max(start, last.published_at)
        started = await self.session.get(SystemState, "started_at")
        if started:
            return max(start, datetime.fromisoformat(started.value["timestamp"]))
        return start

    async def _information_messages(self, start: datetime, end: datetime) -> list[SourceMessage]:
        rows = (
            await self.session.scalars(
                select(SourceMessage).where(
                    SourceMessage.message_date > start,
                    SourceMessage.message_date <= end,
                    SourceMessage.is_ai_processed.is_(True),
                    SourceMessage.has_new_fuel_information.is_(True),
                )
            )
        ).all()
        return filter_information_messages(rows, start, end)

    async def _format_messages(self, messages: list[SourceMessage], end: datetime) -> str | None:
        if not messages:
            return None
        ids = [message.id for message in messages]
        rows = (await self.session.scalars(select(FuelReport).where(FuelReport.source_message_id.in_(ids)))).all()
        reports = [
            AggregatedReport(
                station_normalized=row.station_normalized,
                brand=row.station_brand,
                location=row.station_location,
                fuel_available=row.fuel_available,
                fuel_unavailable=row.fuel_unavailable,
                price_text=row.price_text,
                observed_time=row.observed_time,
                queue_text=row.queue_text,
                queue_cars=row.queue_cars,
                restrictions=row.restrictions,
                station_state=row.station_state,
                additional_info=row.additional_info,
                reported_at=row.reported_at,
            )
            for row in rows
        ]
        aggregated = aggregate_reports(reports)
        return format_summary(aggregated, end, self.timezone) if aggregated else None

    async def build_pending_summary(self, now: datetime | None = None) -> tuple[str, int, datetime, datetime] | None:
        """Builds a publication only when this one-hour window has enough facts."""
        end = now or datetime.now(UTC)
        start = await self._period_start(end)
        messages = await self._information_messages(start, end)
        if not publication_allowed(messages, self.minimum):
            logger.info("Only %d unique informational messages in the last hour; publication skipped", len(messages))
            return None
        text = await self._format_messages(messages, end)
        return (text, len(messages), start, end) if text else None

    async def build_summary_for_message_ids(self, message_ids: list[int], now: datetime | None = None) -> tuple[str, int, datetime, datetime] | None:
        """Creates a summary from exactly one completed scheduler batch."""
        if not message_ids:
            return None
        end = now or datetime.now(UTC)
        messages = (
            await self.session.scalars(
                select(SourceMessage).where(
                    SourceMessage.id.in_(message_ids),
                    SourceMessage.is_ai_processed.is_(True),
                    SourceMessage.has_new_fuel_information.is_(True),
                )
            )
        ).all()
        messages = unique_information_messages(messages)
        if not publication_allowed(messages, self.minimum):
            logger.info("Only %d unique informational messages in completed batch; publication skipped", len(messages))
            return None
        text = await self._format_messages(messages, end)
        start = min(message.message_date for message in messages)
        return (text, len(messages), start, end) if text else None

    async def build_preview_summary(self, now: datetime | None = None) -> tuple[str, int, datetime, datetime] | None:
        """Uses exactly the production aggregation path but never enforces publication."""
        end = now or datetime.now(UTC)
        start = await self._period_start(end)
        messages = await self._information_messages(start, end)
        text = await self._format_messages(messages, end)
        return (text, len(messages), start, end) if text else None
