from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceMessage(Base):
    __tablename__ = "source_messages"
    __table_args__ = (UniqueConstraint("chat_id", "telegram_message_id", name="uq_source_message"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_username: Mapped[str | None] = mapped_column(String(255))
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    message_text: Mapped[str] = mapped_column(Text)
    message_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_keyword_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ai_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    has_new_fuel_information: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FuelReport(Base):
    __tablename__ = "fuel_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_message_id: Mapped[int] = mapped_column(ForeignKey("source_messages.id", ondelete="CASCADE"), index=True)
    station_brand: Mapped[str | None] = mapped_column(String(255))
    station_location: Mapped[str | None] = mapped_column(String(255))
    station_normalized: Mapped[str] = mapped_column(String(255), index=True)
    fuel_available: Mapped[list[str]] = mapped_column(JSONB, default=list)
    fuel_unavailable: Mapped[list[str]] = mapped_column(JSONB, default=list)
    price_text: Mapped[str | None] = mapped_column(Text)
    observed_time: Mapped[str | None] = mapped_column(String(255))
    queue_text: Mapped[str | None] = mapped_column(Text)
    queue_cars: Mapped[int | None] = mapped_column(Integer)
    restrictions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    station_state: Mapped[str] = mapped_column(String(20))
    additional_info: Mapped[str | None] = mapped_column(Text)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reports_count: Mapped[int] = mapped_column(Integer)
    publication_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StationAlias(Base):
    __tablename__ = "station_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_normalized: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
