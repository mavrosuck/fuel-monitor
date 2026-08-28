from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.aggregator import AggregatedReport

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def day_type(moment: datetime) -> str:
    return "ЧЕТНЫЙ ДЕНЬ" if moment.day % 2 == 0 else "НЕЧЕТНЫЙ ДЕНЬ"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")


def _detail(report: AggregatedReport) -> str:
    parts: list[str] = []
    if report.fuel_available:
        parts.append(" и ".join(_escape(item) for item in dict.fromkeys(report.fuel_available)))
    if report.fuel_unavailable:
        parts.append("нет " + " и ".join(_escape(item) for item in dict.fromkeys(report.fuel_unavailable)))
    if report.price_text:
        parts.append(_escape(report.price_text))
    if report.queue_text:
        parts.append(_escape(report.queue_text))
    elif report.queue_cars is not None:
        parts.append(f"очередь около {report.queue_cars} машин")
    parts.extend(_escape(item) for item in report.restrictions)
    if report.observed_time:
        parts.append(_escape(report.observed_time))
    if report.additional_info:
        parts.append(_escape(report.additional_info))
    if not parts:
        return "топлива нет" if report.station_state == "UNAVAILABLE" else "бензин есть"
    return ", ".join(dict.fromkeys(parts))


def format_summary(reports: list[AggregatedReport], now: datetime, timezone: str) -> str:
    local = now.astimezone(ZoneInfo(timezone))
    title = f"⁉️ **ГДЕ БЕНЗИН, ОРЕНБУРГ? — {local.day} {MONTHS[local.month - 1]} {local.year}, {local:%H:%M}**"
    sections = [("AVAILABLE", "🟢 **Бензин есть:**"), ("LIMITED", "🟡 **Есть ограничения:**"), ("UNAVAILABLE", "🔴 **Нет топлива:**")]
    blocks = [title, f"Сегодня {day_type(local)}"]
    for state, heading in sections:
        items = [report for report in reports if report.station_state == state]
        if items:
            lines = []
            for item in sorted(items, key=lambda x: ((x.brand or ""), (x.location or ""))):
                name = ", ".join(_escape(part) for part in [item.brand, item.location] if part) or "АЗС"
                lines.append(f"• **{name}** — {_detail(item)}.")
            blocks.append(heading + "\n\n" + "\n\n".join(lines))
    return "\n\n".join(blocks)
