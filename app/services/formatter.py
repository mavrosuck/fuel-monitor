from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.aggregator import AggregatedReport

MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


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


def format_summary(reports: list[AggregatedReport], now: datetime, timezone: str) -> str:
    if now.tzinfo is None:
        raise ValueError("summary timestamp must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    title = f"ГДЕ БЕНЗИН, ОРЕНБУРГ? — {local:%H:%M}, {local.day} {MONTHS[local.month - 1]}"
    sections = [
        ("AVAILABLE", "🟢 Топливо есть"),
        ("LIMITED", "🟡 Есть ограничения"),
        ("UNAVAILABLE", "🔴 Топлива нет"),
    ]
    blocks = [title]
    for state, heading in sections:
        items = [report for report in reports if report.station_state == state]
        if not items:
            continue
        lines = []
        for item in sorted(items, key=lambda value: ((value.brand or ""), (value.location or ""))):
            line = f"• {_station_name(item)} — {_detail(item)} · {_source_time(item, timezone)}"
            lines.append(line)
        blocks.append(heading + "\n\n" + "\n".join(lines))
    return "\n\n".join(blocks)
