import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.models import CollectedMessage
from app.collector.max_collector import MaxCollectionError
from app import runner
from app.services.batch_classifier import BatchClassification


def test_max_error_blocks_publication(monkeypatch) -> None:
    settings = SimpleNamespace(
        max_enabled=True,
        dry_run=True,
        source_chats=["GdeBenzin56", "benzin156ru"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
    )

    class FakeTelegramCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return []

    class FailingMaxCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            raise MaxCollectionError("unavailable")

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", FakeTelegramCollector)
    monkeypatch.setattr(runner, "MaxCollector", FailingMaxCollector)

    with pytest.raises(RuntimeError, match="publication blocked"):
        asyncio.run(runner.run_once(datetime(2026, 9, 14, tzinfo=UTC)))


def test_fewer_than_five_aggregated_fuel_facts_never_reaches_publisher(monkeypatch) -> None:
    settings = SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=5,
        dry_run=False,
        source_chats=["GdeBenzin56", "benzin156ru"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
    )
    messages = [CollectedMessage("telegram", 1, index, datetime(2026, 9, 14, 12, index, tzinfo=UTC), f"АИ-95 {index}") for index in range(4)]

    class FakeTelegramCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return messages

    class FakeClassifier:
        def __init__(self, _parser) -> None:
            pass

        async def classify(self, text_messages):
            return BatchClassification(
                set(),
                {
                    item.source_message_id: MessageParseResult(
                        source_message_id=item.source_message_id,
                        classification="FACT",
                        has_new_fuel_information=True,
                        reports=[FuelReportData(station_state="AVAILABLE", fuel_available=["АИ-95"])],
                    )
                    for item in text_messages
                },
            )

    class UnexpectedPublisher:
        def __init__(self, *_args) -> None:
            raise AssertionError("publisher must not be constructed")

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", FakeTelegramCollector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", FakeClassifier)
    monkeypatch.setattr(runner, "TelegramPublisher", UnexpectedPublisher)

    assert asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC))) is None


@pytest.mark.parametrize("report_count", [5, 8])
def test_many_reports_from_one_fact_source_message_pass_fuel_fact_threshold(monkeypatch, report_count: int) -> None:
    settings = SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=5,
        dry_run=True,
        source_chats=["GdeBenzin56", "benzin156ru"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
        timezone="Asia/Yekaterinburg",
    )
    source = CollectedMessage("telegram", 1, 1, datetime(2026, 9, 14, 12, tzinfo=UTC), "Мини-сводка")

    class FakeTelegramCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return [source]

    class FakeClassifier:
        def __init__(self, _parser) -> None:
            pass

        async def classify(self, text_messages):
            reports = [
                FuelReportData(location=f"АЗС {index}", fuel_available=["АИ-92"], station_state="AVAILABLE")
                for index in range(report_count)
            ]
            return BatchClassification(
                set(),
                {
                    1: MessageParseResult(
                        source_message_id=1,
                        classification="FACT",
                        has_new_fuel_information=True,
                        reports=reports,
                    )
                },
            )

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", FakeTelegramCollector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", FakeClassifier)
    summary = asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC)))

    assert summary is not None
    assert summary.count("• ") == report_count


@pytest.mark.parametrize(
    ("reports_by_source", "should_publish"),
    [
        ([["A", "B"], ["C", "D"], ["E"], ["F"]], True),
        ([["A"], ["B"], ["C"], ["D"], ["A"], ["B"], ["C"], ["D"], ["A"], ["B"]], False),
    ],
)
def test_fuel_fact_threshold_uses_unique_aggregated_stations(monkeypatch, reports_by_source, should_publish: bool) -> None:
    settings = SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=5,
        dry_run=True,
        source_chats=["GdeBenzin56", "benzin156ru"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
        timezone="Asia/Yekaterinburg",
    )
    messages = [
        CollectedMessage("telegram", 1, index, datetime(2026, 9, 14, 12, index, tzinfo=UTC), f"source {index}")
        for index in range(1, len(reports_by_source) + 1)
    ]

    class FakeTelegramCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return messages

    class FakeClassifier:
        def __init__(self, _parser) -> None:
            pass

        async def classify(self, text_messages):
            return BatchClassification(
                set(),
                {
                    message.source_message_id: MessageParseResult(
                        source_message_id=message.source_message_id,
                        classification="FACT",
                        has_new_fuel_information=True,
                        reports=[
                            FuelReportData(location=location, fuel_available=["АИ-92"], station_state="AVAILABLE")
                            for location in reports_by_source[message.source_message_id - 1]
                        ],
                    )
                    for message in text_messages
                },
            )

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", FakeTelegramCollector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", FakeClassifier)

    summary = asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC)))

    assert (summary is not None) is should_publish


def test_successful_publish_marks_only_one_multi_report_source_and_skips_it_later(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "published-source-messages.json"
    settings = SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=1,
        dry_run=False,
        source_chats=["GdeBenzin56", "benzin156ru"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
        bot_token=SimpleNamespace(get_secret_value=lambda: "unused"),
        target_channel="@benzinoren",
        timezone="Asia/Yekaterinburg",
        published_state_path=str(state_path),
        published_state_retention_days=14,
    )
    source = CollectedMessage("telegram", 1, 10, datetime(2026, 9, 14, 12, tzinfo=UTC), "Мини-сводка")

    class FakeTelegramCollector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return [source]

    class FakeClassifier:
        def __init__(self, _parser) -> None:
            pass

        async def classify(self, _text_messages):
            return BatchClassification(
                set(),
                {1: MessageParseResult(source_message_id=1, classification="FACT", has_new_fuel_information=True, reports=[
                    FuelReportData(location=f"АЗС {index}", fuel_available=["АИ-92"], station_state="AVAILABLE")
                    for index in range(8)
                ])},
            )

    class FakePublisher:
        calls = 0

        def __init__(self, *_args) -> None:
            pass

        async def publish(self, _text):
            self.__class__.calls += 1
            return 1

        async def close(self):
            pass

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", FakeTelegramCollector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", FakeClassifier)
    monkeypatch.setattr(runner, "TelegramPublisher", FakePublisher)

    asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC)))
    asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, 5, tzinfo=UTC)))

    assert FakePublisher.calls == 1
    assert set(json.loads(state_path.read_text(encoding="utf-8"))["published_messages"]) == {"telegram|1|10"}
