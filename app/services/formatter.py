from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from app.services.aggregator import AggregatedReport

MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


@dataclass(frozen=True)
class TextStyle:
    type: Literal["bold", "italic"]
    offset: int
    length: int


@dataclass(frozen=True)
class FormattedSummary:
    text: str
    styles: tuple[TextStyle, ...]


class _SummaryBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.styles: list[TextStyle] = []
        self.length = 0

    def append(self, value: str, style: Literal["bold", "italic"] | None = None) -> None:
        if style is not None and value:
            self.styles.append(TextStyle(style, self.length, len(value)))
        self.parts.append(value)
        self.length += len(value)

    def build(self) -> FormattedSummary:
        return FormattedSummary("".join(self.parts), tuple(self.styles))


def day_type(moment: datetime) -> str:
    return "ЧЕТНЫЙ ДЕНЬ" if moment.day % 2 == 0 else "НЕЧЕТНЫЙ ДЕНЬ"


def _clean(value: str) -> str:
    return value.strip()


def _detail(report: AggregatedReport) -> str:
    parts: list[str] = []
    if report.fuel_available:
        parts.append(", ".join(_clean(item) for item in dict.fromkeys(report.fuel_available)))
    if report.fuel_unavailable:
        parts.extend(f"{_clean(item)} нет" for item in dict.fromkeys(report.fuel_unavailable))
    if report.price_text:
        parts.append(_clean(report.price_text))
    if report.queue_text:
        parts.append(_clean(report.queue_text))
    elif report.queue_cars is not None:
        parts.append(f"очередь около {report.queue_cars} машин")
    parts.extend(_clean(item) for item in report.restrictions)
    if report.observed_time:
        parts.append(_clean(report.observed_time))
    if report.additional_info:
        parts.append(_clean(report.additional_info))
    if not parts:
        return "топлива нет" if report.station_state == "UNAVAILABLE" else "бензин есть"
    return ", ".join(dict.fromkeys(parts))


def _source_time(report: AggregatedReport, timezone: str) -> str:
    if report.reported_at is None:
        raise ValueError("aggregated report is missing a source timestamp")
    if report.reported_at.tzinfo is None:
        raise ValueError("aggregated report timestamp must be timezone-aware")
    return report.reported_at.astimezone(ZoneInfo(timezone)).strftime("%H:%M")


def _station_name(report: AggregatedReport) -> str:
    parts = [_clean(part) for part in (report.brand, report.location) if part]
    return " · ".join(parts) or "АЗС"


def format_styled_summary(reports: list[AggregatedReport], now: datetime, timezone: str) -> FormattedSummary:
    if now.tzinfo is None:
        raise ValueError("summary timestamp must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    builder = _SummaryBuilder()
    builder.append("ГДЕ БЕНЗИН, ОРЕНБУРГ?", "bold")
    builder.append(" — ")
    builder.append(f"{local:%H:%M}, {local.day} {MONTHS[local.month - 1]}", "italic")
    sections = [
        ("AVAILABLE", "🟢 Топливо есть"),
        ("LIMITED", "🟡 Есть ограничения"),
        ("UNAVAILABLE", "🔴 Топлива нет"),
    ]
    for state, heading in sections:
        items = [report for report in reports if report.station_state == state]
        if not items:
            continue
        builder.append("\n\n")
        builder.append(heading, "bold")
        builder.append("\n\n")
        for index, item in enumerate(sorted(items, key=lambda value: ((value.brand or ""), (value.location or "")))):
            if index:
                builder.append("\n")
            builder.append("• ")
            builder.append(_station_name(item), "bold")
            builder.append(" — ")
            builder.append(_detail(item))
            builder.append(" · ")
            builder.append(_source_time(item, timezone), "italic")
    return builder.build()


def format_summary(reports: list[AggregatedReport], now: datetime, timezone: str) -> str:
    return format_styled_summary(reports, now, timezone).text
