from datetime import UTC, datetime, timedelta

from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.telegram_client import CollectedMessage
from app.runner import deduplicate_messages, reports_from_results
from app.services.station_normalizer import StationNormalizer


def message(message_id: int, text: str, minutes: int = 0) -> CollectedMessage:
    return CollectedMessage(
        source_message_id=4_312_672_249_000_000_000 + message_id,
        chat_id=4_312_672_249,
        username="GdeBenzin56",
        message_id=message_id,
        date=datetime.now(UTC) - timedelta(minutes=minutes),
        text=text,
    )


def test_reposts_are_counted_once_before_gemini() -> None:
    unique = deduplicate_messages([message(1, "На АЗС есть АИ-95", 5), message(2, "На   АЗС есть АИ-95")])
    assert len(unique) == 1
    assert unique[0].message_id == 2


def test_facts_become_aggregatable_reports() -> None:
    source = message(1, "На Лукойле есть АИ-95")
    parsed = MessageParseResult(
        source_message_id=source.source_message_id,
        classification="FACT",
        has_new_fuel_information=True,
        reports=[FuelReportData(brand="Лукойл", fuel_available=["АИ-95"], station_state="AVAILABLE")],
    )
    reports = reports_from_results([source], {source.source_message_id: parsed}, StationNormalizer())
    assert len(reports) == 1
    assert reports[0].fuel_available == ["АИ-95"]
