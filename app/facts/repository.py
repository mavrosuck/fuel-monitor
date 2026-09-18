import hashlib
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FuelFact, ProcessedSourceMessage
from app.facts.conversion import FuelFactInput


def build_source_key(source_platform: str, source_chat_id: str | int, source_message_id: str | int) -> str:
    values = (str(source_platform), str(source_chat_id), str(source_message_id))
    if not all(values) or any("|" in value for value in values):
        raise ValueError("source identity must contain three non-empty pipe-free values")
    return "|".join(values)


def content_hash_for_text(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    if not normalized:
        raise ValueError("source message text must not be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class FactsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_source_message(self, source_platform: str, source_chat_id: str | int, source_message_id: str | int, message_date: datetime, content_hash: str) -> ProcessedSourceMessage:
        if message_date.tzinfo is None:
            raise ValueError("message date must be timezone-aware")
        source_key = build_source_key(source_platform, source_chat_id, source_message_id)
        await self.session.execute(self._insert(ProcessedSourceMessage).values(source_key=source_key, source_platform=source_platform, source_chat_id=str(source_chat_id), source_message_id=str(source_message_id), message_date=message_date, content_hash=content_hash, processing_status="pending").on_conflict_do_nothing(index_elements=["source_key"]))
        await self.session.flush()
        return await self.session.get_one(ProcessedSourceMessage, source_key)

    async def claim_source_message(self, source_key: str, now: datetime, lease: timedelta = timedelta(minutes=15)) -> ProcessedSourceMessage | None:
        if now.tzinfo is None or lease <= timedelta(0):
            raise ValueError("claim time must be timezone-aware and lease positive")
        result = await self.session.execute(update(ProcessedSourceMessage).where(ProcessedSourceMessage.source_key == source_key, or_(ProcessedSourceMessage.processing_status.in_(("pending", "failed")), and_(ProcessedSourceMessage.processing_status == "processing", ProcessedSourceMessage.processing_started_at < now - lease))).values(processing_status="processing", processing_started_at=now, processed_at=None))
        if result.rowcount != 1:
            return None
        await self.session.flush()
        return await self.session.get_one(ProcessedSourceMessage, source_key)

    async def mark_source_processed(self, source_key: str, processed_at: datetime) -> None:
        await self._mark(source_key, "done", processed_at)

    async def mark_source_failed(self, source_key: str, failed_at: datetime) -> None:
        await self._mark(source_key, "failed", failed_at)

    async def mark_source_duplicate(self, source_key: str, canonical_source_key: str, processed_at: datetime) -> None:
        if source_key == canonical_source_key:
            raise ValueError("duplicate source must differ from canonical source")
        result = await self.session.execute(update(ProcessedSourceMessage).where(ProcessedSourceMessage.source_key == source_key, ProcessedSourceMessage.processing_status == "pending").values(processing_status="duplicate", canonical_source_key=canonical_source_key, processed_at=processed_at, processing_started_at=None))
        if result.rowcount != 1:
            raise ValueError("duplicate source must be pending")
        await self.session.flush()

    async def save_facts(self, facts: Sequence[FuelFactInput]) -> None:
        for fact in facts:
            values = fact.__dict__.copy()
            update_values = {key: value for key, value in values.items() if key not in {"source_key", "station_normalized", "fuel_type"}}
            await self.session.execute(self._insert(FuelFact).values(**values).on_conflict_do_update(index_elements=["source_key", "station_normalized", "fuel_type"], set_=update_values))
        await self.session.flush()

    async def get_latest_facts(self, fuel_types: Sequence[str], since: datetime) -> list[FuelFact]:
        if since.tzinfo is None:
            raise ValueError("since must be timezone-aware")
        if not fuel_types:
            return []
        rank = func.row_number().over(partition_by=(FuelFact.station_normalized, FuelFact.fuel_type), order_by=(FuelFact.observed_at.desc(), FuelFact.created_at.desc(), FuelFact.id.desc())).label("rank")
        ranked = select(FuelFact.id.label("id"), rank).where(FuelFact.fuel_type.in_(tuple(fuel_types)), FuelFact.observed_at >= since).subquery()
        return list(await self.session.scalars(select(FuelFact).join(ranked, FuelFact.id == ranked.c.id).where(ranked.c.rank == 1).order_by(FuelFact.station_normalized, FuelFact.fuel_type, FuelFact.id)))

    async def delete_facts_older_than(self, cutoff: datetime) -> int:
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        result = await self.session.execute(delete(FuelFact).where(FuelFact.observed_at < cutoff).execution_options(synchronize_session=False))
        await self.session.flush()
        return result.rowcount or 0

    async def _mark(self, source_key: str, status: str, timestamp: datetime) -> None:
        if timestamp.tzinfo is None:
            raise ValueError("processing timestamp must be timezone-aware")
        result = await self.session.execute(update(ProcessedSourceMessage).where(ProcessedSourceMessage.source_key == source_key, ProcessedSourceMessage.processing_status == "processing").values(processing_status=status, processed_at=timestamp, processing_started_at=None))
        if result.rowcount != 1:
            raise ValueError("source must be claimed before completion")
        await self.session.flush()

    def _insert(self, model):
        return postgresql_insert(model) if self.session.bind.dialect.name == "postgresql" else sqlite_insert(model)
