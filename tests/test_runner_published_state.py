import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import runner
from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.models import CollectedMessage
from app.services.batch_classifier import BatchClassification


def _configure(monkeypatch, tmp_path, *, dry_run: bool, minimum: int, publisher):
    state_path = tmp_path / "published-source-messages.json"
    settings = SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=minimum,
        dry_run=dry_run,
        source_chats=["GdeBenzin56"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
        bot_token=None if dry_run else SimpleNamespace(get_secret_value=lambda: "unused"),
        target_channel="@benzinoren",
        timezone="Asia/Yekaterinburg",
        published_state_path=str(state_path),
        published_state_retention_days=14,
    )
    message = CollectedMessage("telegram", 1, 1, datetime(2026, 9, 14, 12, tzinfo=UTC), "На Победе 95 есть")

    class Collector:
        def __init__(self, _settings):
            pass

        async def collect_since(self, _start, _end):
            return [message]

    class Classifier:
        def __init__(self, _parser):
            pass

        async def classify(self, _messages):
            return BatchClassification(set(), {1: MessageParseResult(
                source_message_id=1,
                classification="FACT",
                has_new_fuel_information=True,
                reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")],
            )})

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", Collector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", Classifier)
    monkeypatch.setattr(runner, "TelegramPublisher", publisher)
    return state_path


def test_dry_run_never_writes_published_state(monkeypatch, tmp_path) -> None:
    class UnexpectedPublisher:
        def __init__(self, *_args):
            raise AssertionError("publisher must not be constructed")

    state_path = _configure(monkeypatch, tmp_path, dry_run=True, minimum=1, publisher=UnexpectedPublisher)

    asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC)))

    assert not state_path.exists()


def test_below_threshold_never_writes_published_state(monkeypatch, tmp_path) -> None:
    class UnexpectedPublisher:
        def __init__(self, *_args):
            raise AssertionError("publisher must not be constructed")

    state_path = _configure(monkeypatch, tmp_path, dry_run=False, minimum=2, publisher=UnexpectedPublisher)

    assert asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC))) is None
    assert not state_path.exists()


def test_failed_publish_never_writes_published_state(monkeypatch, tmp_path) -> None:
    class FailingPublisher:
        def __init__(self, *_args):
            pass

        async def publish(self, _text):
            raise RuntimeError("publish failed")

        async def close(self):
            pass

    state_path = _configure(monkeypatch, tmp_path, dry_run=False, minimum=1, publisher=FailingPublisher)

    with pytest.raises(RuntimeError, match="publish failed"):
        asyncio.run(runner.run_once(datetime(2026, 9, 14, 13, tzinfo=UTC)))
    assert not state_path.exists()
