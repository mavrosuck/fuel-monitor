from datetime import UTC, datetime, timedelta

from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.models import CollectedMessage
from app.runner import deduplicate_messages, reports_from_results
from app.services.station_normalizer import StationNormalizer


def message(message_id: int, text: str, minutes: int = 0) -> CollectedMessage:
    return CollectedMessage(
        platform="telegram",
        source_chat_id=4_312_672_249,
        source_message_id=message_id,
        message_date=datetime.now(UTC) - timedelta(minutes=minutes),
        text=text,
    )


def test_reposts_are_counted_once_before_gemini() -> None:
    unique = deduplicate_messages([message(1, "На АЗС есть АИ-95", 5), message(2, "На   АЗС есть АИ-95")])
    assert len(unique) == 1
    assert unique[0].source_message_id == 2


def test_facts_become_aggregatable_reports() -> None:
    source = message(1, "На Лукойле есть АИ-95")
    parsed = MessageParseResult(
        source_message_id=1,
        classification="FACT",
        has_new_fuel_information=True,
        reports=[FuelReportData(brand="Лукойл", fuel_available=["АИ-95"], station_state="AVAILABLE")],
    )
    reports = reports_from_results([source], {1: parsed}, StationNormalizer())
    assert len(reports) == 1
    assert reports[0].fuel_available == ["АИ-95"]


def test_all_reports_from_one_source_message_keep_its_timestamp() -> None:
    source = message(1, "Мини-сводка")
    parsed = MessageParseResult(
        source_message_id=1,
        classification="FACT",
        has_new_fuel_information=True,
        reports=[
            FuelReportData(location="Победа", fuel_available=["АИ-92"], station_state="AVAILABLE"),
            FuelReportData(location="Монтажников", restrictions=["только ДТ"], station_state="LIMITED"),
            FuelReportData(location="Терешковой", fuel_unavailable=["АИ-95"], station_state="LIMITED"),
        ],
    )

    reports = reports_from_results([source], {1: parsed}, StationNormalizer())

    assert len(reports) == 3
    assert {report.reported_at for report in reports} == {source.message_date}
