from datetime import UTC, datetime

from app.services.aggregator import AggregatedReport
from app.services.formatter import format_summary


def test_formatter_omits_empty_sections() -> None:
    text = format_summary([AggregatedReport("x", "Лукойл", "Джангильдина", station_state="UNAVAILABLE")], datetime(2026, 8, 28, 13, 27, tzinfo=UTC), "Asia/Yekaterinburg")
    assert "**ГДЕ БЕНЗИН, ОРЕНБУРГ?" in text
    assert "🔴 **Нет топлива:**" in text
    assert "🟢" not in text and "🟡" not in text


def test_formatter_uses_orenburg_time_and_deduplicates_details() -> None:
    report = AggregatedReport(
        "x", "Башнефть", "Победы", fuel_available=["АИ-95", "АИ-95"], station_state="AVAILABLE"
    )
    text = format_summary([report], datetime(2026, 8, 28, 13, 27, tzinfo=UTC), "Asia/Yekaterinburg")
    assert "28 августа 2026, 18:27" in text
    assert "Сегодня ЧЕТНЫЙ ДЕНЬ" in text
    assert text.count("АИ-95") == 1
