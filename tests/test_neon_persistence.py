import asyncio
import ssl
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app import runner
from app.ai.schema import FuelReportData, MessageParseResult
from app.collector.models import CollectedMessage
from app.database.database import Database
from app.database.models import FuelFact, ProcessedSourceMessage
from app.facts import persistence as persistence_module
from app.facts.persistence import NeonFactsPersistence, create_neon_facts_persistence, validate_neon_collector_url
from app.services.batch_classifier import BatchClassification


def test_missing_neon_url_creates_no_engine(monkeypatch) -> None:
    monkeypatch.setattr(persistence_module, "Database", lambda *_args, **_kwargs: pytest.fail("engine must not be created"))
    assert create_neon_facts_persistence(None) is None


def test_neon_tls_uses_a_verifying_ssl_context(monkeypatch) -> None:
    captured = {}

    class FakeDatabase:
        def __init__(self, url, *, connect_args) -> None:
            captured["url"] = url
            captured["connect_args"] = connect_args

    monkeypatch.setattr(persistence_module, "Database", FakeDatabase)
    persistence = create_neon_facts_persistence(SecretStr("postgresql+asyncpg://collector_writer:password@ep-example.neon.tech/neondb"))

    assert persistence is not None
    context = captured["connect_args"]["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.parametrize("query", ["sslmode=require", "channel_binding=require"])
def test_incompatible_asyncpg_url_parameters_are_rejected(query: str) -> None:
    with pytest.raises(ValueError):
        validate_neon_collector_url(f"postgresql+asyncpg://collector_writer:password@ep-example.neon.tech/neondb?{query}")


def test_invalid_neon_url_disables_sidecar_without_creating_an_engine(monkeypatch) -> None:
    monkeypatch.setattr(persistence_module, "Database", lambda *_args, **_kwargs: pytest.fail("engine must not be created"))
    assert create_neon_facts_persistence(
        SecretStr("postgresql+asyncpg://collector_writer:password@ep-example.neon.tech/neondb?sslmode=require")
    ) is None


def test_persistence_saves_one_fact_without_telegram_threshold() -> None:
    async def scenario() -> None:
        database = Database("sqlite+aiosqlite:///:memory:")
        async with database.engine.begin() as connection:
            await connection.run_sync(ProcessedSourceMessage.__table__.create)
            await connection.run_sync(FuelFact.__table__.create)
        persistence = NeonFactsPersistence(database)
        message = CollectedMessage("telegram", 1, 1, datetime(2026, 9, 18, 12, tzinfo=UTC), "На Победе есть АИ-95")
        result = MessageParseResult(
            source_message_id=1,
            classification="FACT",
            has_new_fuel_information=True,
            reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")],
        )

        await persistence.persist(message, result, runner.StationNormalizer(), datetime(2026, 9, 18, 12, 1, tzinfo=UTC))

        async with database.session_factory() as session:
            assert len((await session.scalars(select(FuelFact))).all()) == 1
            assert (await session.get_one(ProcessedSourceMessage, "telegram|1|1")).processing_status == "done"
        await persistence.close()

    asyncio.run(scenario())


def _run_settings(minimum: int = 2):
    return SimpleNamespace(
        max_enabled=False,
        min_reports_to_publish=minimum,
        dry_run=True,
        source_chats=["GdeBenzin56"],
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "unused"),
        gemini_model="unused",
        timezone="Asia/Yekaterinburg",
        neon_collector_database_url=None,
    )


def _message() -> CollectedMessage:
    return CollectedMessage("telegram", 1, 1, datetime(2026, 9, 18, 12, tzinfo=UTC), "На Победе есть АИ-95")


def _patch_runner(monkeypatch, settings, persistence):
    class Collector:
        def __init__(self, _settings) -> None:
            pass

        async def collect_since(self, _start, _end):
            return [_message()]

    class Classifier:
        calls = 0

        def __init__(self, _parser) -> None:
            pass

        async def classify(self, messages):
            self.__class__.calls += 1
            return BatchClassification(
                set(),
                {
                    item.source_message_id: MessageParseResult(
                        source_message_id=item.source_message_id,
                        classification="FACT",
                        has_new_fuel_information=True,
                        reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")],
                    )
                    for item in messages
                },
            )

    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "TelegramCollector", Collector)
    monkeypatch.setattr(runner, "FuelAIParser", lambda *_args: object())
    monkeypatch.setattr(runner, "BatchClassifier", Classifier)
    monkeypatch.setattr(runner, "create_neon_facts_persistence", lambda _url: persistence)
    return Classifier


def test_sidecar_saves_before_below_threshold_without_extra_gemini_call(monkeypatch) -> None:
    class RecordingPersistence:
        def __init__(self) -> None:
            self.records = []

        async def persist(self, message, result, normalizer) -> None:
            self.records.append((message, result, normalizer))

        async def close(self) -> None:
            pass

    persistence = RecordingPersistence()
    classifier = _patch_runner(monkeypatch, _run_settings(minimum=2), persistence)

    assert asyncio.run(runner.run_once(datetime(2026, 9, 18, 13, tzinfo=UTC))) is None
    assert len(persistence.records) == 1
    assert classifier.calls == 1


def test_sidecar_does_not_change_aggregated_reports() -> None:
    class RecordingPersistence:
        async def persist(self, *_args) -> None:
            pass

    message = _message()
    result = MessageParseResult(
        source_message_id=1,
        classification="FACT",
        has_new_fuel_information=True,
        reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")],
    )
    normalizer = runner.StationNormalizer()
    expected = runner.reports_from_results([message], {1: result}, normalizer)

    asyncio.run(runner._persist_classified_results([message], {1: result}, normalizer, RecordingPersistence()))

    assert runner.reports_from_results([message], {1: result}, normalizer) == expected


def test_persistence_failure_does_not_change_telegram_result(monkeypatch) -> None:
    class FailingPersistence:
        async def persist(self, *_args) -> None:
            raise RuntimeError("database unavailable")

        async def close(self) -> None:
            pass

    _patch_runner(monkeypatch, _run_settings(minimum=1), FailingPersistence())

    summary = asyncio.run(runner.run_once(datetime(2026, 9, 18, 13, tzinfo=UTC)))
    assert summary is not None
    assert "Победа" in summary
