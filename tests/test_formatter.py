from datetime import UTC, datetime

import pytest

from app.services.aggregator import AggregatedReport
from app.services.formatter import format_summary


def test_formatter_uses_strict_deterministic_format_and_orenburg_source_times() -> None:
    reports = [
        AggregatedReport(
            "r", "Роснефть", "Шоссейная", fuel_available=["АИ-92", "АИ-95"],
            additional_info="работает", station_state="AVAILABLE",
            reported_at=datetime(2026, 9, 14, 9, 42, tzinfo=UTC),
        ),
        AggregatedReport(
            "b", "Башнефть", "Монтажников", restrictions=["только ДТ"],
            station_state="LIMITED", reported_at=datetime(2026, 9, 14, 9, 57, tzinfo=UTC),
        ),
        AggregatedReport(
            "g", "Газпром", "Конституции", fuel_unavailable=["АИ-92", "АИ-95"],
            station_state="UNAVAILABLE", reported_at=datetime(2026, 9, 14, 10, 3, tzinfo=UTC),
        ),
    ]

    assert format_summary(reports, datetime(2026, 9, 14, 10, 27, tzinfo=UTC), "Asia/Yekaterinburg") == (
        "ГДЕ БЕНЗИН, ОРЕНБУРГ? — 15:27, 14 сентября\n\n"
        "🟢 Топливо есть\n\n"
        "• Роснефть · Шоссейная — АИ-92, АИ-95, работает · 14:42\n\n"
        "🟡 Есть ограничения\n\n"
        "• Башнефть · Монтажников — только ДТ · 14:57\n\n"
        "🔴 Топлива нет\n\n"
        "• Газпром · Конституции — АИ-92 нет, АИ-95 нет · 15:03"
    )


def test_formatter_omits_empty_sections_and_day_type_line() -> None:
    report = AggregatedReport(
        "x", "Лукойл", "Джангильдина", station_state="UNAVAILABLE",
        reported_at=datetime(2026, 8, 28, 13, 27, tzinfo=UTC),
    )
    text = format_summary([report], datetime(2026, 8, 28, 13, 27, tzinfo=UTC), "Asia/Yekaterinburg")

    assert "🟢" not in text and "🟡" not in text
    assert "ЧЕТНЫЙ" not in text and "НЕЧЕТНЫЙ" not in text
    assert text.endswith("· 18:27")


def test_formatter_requires_a_timezone_aware_source_timestamp() -> None:
    report = AggregatedReport("x", "Лукойл", "Джангильдина", station_state="UNAVAILABLE")

    with pytest.raises(ValueError, match="source timestamp"):
        format_summary([report], datetime(2026, 8, 28, 13, 27, tzinfo=UTC), "Asia/Yekaterinburg")
