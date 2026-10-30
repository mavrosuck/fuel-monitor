from datetime import UTC, datetime, timedelta

import pytest

from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.models import CollectedMessage
from app import runner
from app.runner import (
    LatePublicationError,
    deduplicate_messages,
    publication_end,
    reports_from_results,
    scheduled_publication_end,
)
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


def test_diagnostic_source_counts_redact_source_names_and_identifiers() -> None:
    messages = [
        CollectedMessage("max", -777, 1, datetime.now(UTC), "private text", "private MAX chat"),
        CollectedMessage("max", -777, 2, datetime.now(UTC), "more private text", "private MAX chat"),
        CollectedMessage("telegram", 999, 3, datetime.now(UTC), "another private text", "private Telegram chat"),
    ]

    diagnostics = runner.diagnostic_source_counts(messages)

    assert diagnostics == "max#1=2 telegram#1=1"
    assert "777" not in diagnostics
    assert "private" not in diagnostics


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


def test_dry_run_collector_window_is_thirty_minutes(monkeypatch) -> None:
    observed = {}

    class Notifier:
        async def notify_error(self, *_args) -> None:
            pass

        async def close(self) -> None:
            pass

    async def fake_run(_settings, start, end, _metrics):
        observed["start"] = start
        observed["end"] = end
        return None

    monkeypatch.setattr(runner, "_run_monitor", fake_run)
    monkeypatch.setattr(runner, "_admin_notifier", lambda _settings: Notifier())
    monkeypatch.setattr(runner, "_health_state", lambda _settings, _now: (None, None))
    monkeypatch.setattr(runner, "get_settings", lambda: type("Settings", (), {"dry_run": True})())

    end = datetime(2026, 9, 28, 12, tzinfo=UTC)
    import asyncio
    asyncio.run(runner.run_once(end))

    assert observed["end"] == end
    assert observed["start"] == end - timedelta(minutes=30)


def test_channel_summary_window_covers_full_two_hour_slot(monkeypatch) -> None:
    observed = {}

    class Notifier:
        async def notify_error(self, *_args) -> None:
            pass

        async def close(self) -> None:
            pass

    async def fake_run(_settings, start, end, _metrics):
        observed["start"] = start
        observed["end"] = end
        return None

    monkeypatch.setattr(runner, "_run_monitor", fake_run)
    monkeypatch.setattr(runner, "_admin_notifier", lambda _settings: Notifier())
    monkeypatch.setattr(runner, "_health_state", lambda _settings, _now: (None, None))
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "dry_run": False,
                "timezone": "Asia/Yekaterinburg",
                "channel_summary_interval_hours": 2,
            },
        )(),
    )

    end = datetime(2026, 9, 28, 9, tzinfo=UTC)
    import asyncio

    asyncio.run(runner.run_once(end))

    assert observed["end"] == end
    assert observed["start"] == end - timedelta(hours=2)


def test_small_publication_delay_uses_the_scheduled_orenburg_slot(monkeypatch) -> None:
    observed = {}

    class Notifier:
        async def notify_error(self, *_args) -> None:
            pass

        async def close(self) -> None:
            pass

    async def fake_run(_settings, start, end, _metrics):
        observed["start"] = start
        observed["end"] = end
        return None

    monkeypatch.setattr(runner, "_run_monitor", fake_run)
    monkeypatch.setattr(runner, "_admin_notifier", lambda _settings: Notifier())
    monkeypatch.setattr(runner, "_health_state", lambda _settings, _now: (None, None))
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "dry_run": False,
                "timezone": "Asia/Yekaterinburg",
                "channel_summary_interval_hours": 2,
            },
        )(),
    )

    import asyncio

    asyncio.run(runner.run_once(datetime(2026, 9, 28, 9, 14, tzinfo=UTC)))

    assert observed["end"] == datetime(2026, 9, 28, 9, tzinfo=UTC)
    assert observed["start"] == datetime(2026, 9, 28, 7, tzinfo=UTC)


def test_late_publication_is_rejected_before_collection(monkeypatch) -> None:
    notifications = []

    class Notifier:
        async def notify_error(self, title, now, error) -> None:
            notifications.append((title, now, error))

        async def close(self) -> None:
            pass

    async def unexpected_run(*_args):
        raise AssertionError("late publication must stop before collection")

    monkeypatch.setattr(runner, "_run_monitor", unexpected_run)
    monkeypatch.setattr(runner, "_admin_notifier", lambda _settings: Notifier())
    monkeypatch.setattr(runner, "_health_state", lambda _settings, _now: (None, None))
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "dry_run": False,
                "timezone": "Asia/Yekaterinburg",
                "channel_summary_interval_hours": 2,
                "max_publication_delay_minutes": 15,
            },
        )(),
    )

    import asyncio

    now = datetime(2026, 9, 28, 9, 16, tzinfo=UTC)
    with pytest.raises(LatePublicationError, match="16 minutes late"):
        asyncio.run(runner.run_once(now))

    assert notifications[0][0] == "Scheduled publication skipped because GitHub Actions started late"
    assert notifications[0][1] == now


def test_publication_slot_is_calculated_in_orenburg_time() -> None:
    delayed = datetime(2026, 9, 28, 19, 12, tzinfo=UTC)

    assert scheduled_publication_end(delayed, "Asia/Yekaterinburg", 2) == datetime(
        2026, 9, 28, 19, tzinfo=UTC
    )


def test_explicit_publication_slot_cannot_jump_to_a_later_slot() -> None:
    explicit_slot = datetime(2026, 9, 28, 1, tzinfo=UTC)
    settings = type(
        "Settings",
        (),
        {
            "publication_slot_end": explicit_slot,
            "timezone": "Asia/Yekaterinburg",
            "channel_summary_interval_hours": 2,
        },
    )()

    assert publication_end(settings, datetime(2026, 9, 28, 4, 5, tzinfo=UTC)) == explicit_slot


def test_explicit_publication_slot_must_match_orenburg_schedule() -> None:
    settings = type(
        "Settings",
        (),
        {
            "publication_slot_end": datetime(2026, 9, 28, 2, tzinfo=UTC),
            "timezone": "Asia/Yekaterinburg",
            "channel_summary_interval_hours": 2,
        },
    )()

    with pytest.raises(ValueError, match="not aligned"):
        publication_end(settings, datetime(2026, 9, 28, 2, 1, tzinfo=UTC))
