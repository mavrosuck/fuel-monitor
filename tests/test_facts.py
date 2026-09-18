import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schema import FuelReportData, ParseResult
from app.database.models import FuelFact, ProcessedSourceMessage
from app.facts.conversion import facts_from_parse_result
from app.facts.repository import FactsRepository, build_source_key, content_hash_for_text
from app.services.station_normalizer import StationNormalizer


async def with_repository(test):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(ProcessedSourceMessage.__table__.create)
        await connection.run_sync(FuelFact.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await test(FactsRepository(session), session)
    finally:
        await engine.dispose()


def test_source_identity_and_duplicate_registration() -> None:
    async def scenario(repository, _session):
        now = datetime(2026, 9, 18, 12, tzinfo=UTC)
        first = await repository.register_source_message("telegram", 1, 2, now, content_hash_for_text("Есть АИ-95"))
        second = await repository.register_source_message("telegram", 1, 2, now, content_hash_for_text("Есть АИ-95"))
        assert first.source_key == "telegram|1|2"
        assert second.source_key == first.source_key
        assert (await _session.scalar(select(func.count()).select_from(ProcessedSourceMessage))) == 1

    asyncio.run(with_repository(scenario))
    assert build_source_key("max", "-1", 2) == "max|-1|2"


def test_claim_done_failed_and_stale_processing_lease() -> None:
    async def scenario(repository, _session):
        now = datetime(2026, 9, 18, 12, tzinfo=UTC)
        source = await repository.register_source_message("telegram", 1, 1, now, "a" * 64)
        assert await repository.claim_source_message(source.source_key, now)
        assert await repository.claim_source_message(source.source_key, now) is None
        await repository.mark_source_failed(source.source_key, now)
        assert await repository.claim_source_message(source.source_key, now + timedelta(minutes=1))
        await repository.mark_source_processed(source.source_key, now + timedelta(minutes=1))
        assert await repository.claim_source_message(source.source_key, now + timedelta(minutes=2)) is None
        stale = await repository.register_source_message("max", 2, 2, now, "b" * 64)
        assert await repository.claim_source_message(stale.source_key, now)
        assert await repository.claim_source_message(stale.source_key, now + timedelta(minutes=16))

    asyncio.run(with_repository(scenario))


def test_duplicate_tracks_canonical_source() -> None:
    async def scenario(repository, _session):
        now = datetime(2026, 9, 18, 12, tzinfo=UTC)
        canonical = await repository.register_source_message("telegram", 1, 1, now, "a" * 64)
        duplicate = await repository.register_source_message("max", 2, 2, now, "a" * 64)
        await repository.mark_source_duplicate(duplicate.source_key, canonical.source_key, now)
        stored = await _session.get_one(ProcessedSourceMessage, duplicate.source_key)
        assert stored.processing_status == "duplicate"
        assert stored.canonical_source_key == canonical.source_key
        assert await repository.claim_source_message(duplicate.source_key, now + timedelta(hours=1)) is None

    asyncio.run(with_repository(scenario))


def test_parse_result_converts_available_unavailable_and_limited_facts() -> None:
    now = datetime(2026, 9, 18, 12, tzinfo=UTC)
    result = ParseResult(classification="FACT", has_new_fuel_information=True, reports=[
        FuelReportData(location="Победа", fuel_available=["АИ-92", "АИ-95"], fuel_unavailable=["ДТ"], restrictions=["по талонам"], station_state="LIMITED"),
        FuelReportData(location="Общая", station_state="UNAVAILABLE"),
    ])
    facts = facts_from_parse_result(result, "telegram|1|1", now, StationNormalizer())
    assert {(fact.fuel_type, fact.state) for fact in facts} == {("ai_92", "limited"), ("ai_95", "limited"), ("diesel", "unavailable")}
    assert all(fact.observed_at == now for fact in facts)
    assert all(fact.station_location != "Общая" for fact in facts)


def test_save_facts_is_idempotent_and_latest_state_wins() -> None:
    async def scenario(repository, session):
        now = datetime(2026, 9, 18, 12, tzinfo=UTC)
        source_one = await repository.register_source_message("telegram", 1, 1, now, "a" * 64)
        source_two = await repository.register_source_message("telegram", 1, 2, now + timedelta(minutes=5), "b" * 64)
        available = facts_from_parse_result(ParseResult(classification="FACT", has_new_fuel_information=True, reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")]), source_one.source_key, now, StationNormalizer())
        unavailable = facts_from_parse_result(ParseResult(classification="FACT", has_new_fuel_information=True, reports=[FuelReportData(location="Победа", fuel_unavailable=["АИ-95", "ДТ"], station_state="UNAVAILABLE")]), source_two.source_key, now + timedelta(minutes=5), StationNormalizer())
        await repository.save_facts(available)
        await repository.save_facts(available)
        await repository.save_facts(unavailable)
        assert (await session.scalar(select(func.count()).select_from(FuelFact))) == 3
        latest = await repository.get_latest_facts(["ai_95", "diesel"], now - timedelta(hours=3))
        assert [(fact.fuel_type, fact.state) for fact in latest] == [("ai_95", "unavailable"), ("diesel", "unavailable")]
        assert await repository.get_latest_facts(["ai_95"], now + timedelta(minutes=6)) == []
        assert await repository.delete_facts_older_than(now + timedelta(minutes=1)) == 1

    asyncio.run(with_repository(scenario))


def test_newer_available_wins_and_tie_break_is_stable() -> None:
    async def scenario(repository, _session):
        now = datetime(2026, 9, 18, 12, tzinfo=UTC)
        first = await repository.register_source_message("telegram", 1, 1, now, "a" * 64)
        second = await repository.register_source_message("max", 2, 2, now, "b" * 64)
        third = await repository.register_source_message("telegram", 1, 3, now + timedelta(minutes=1), "c" * 64)
        unavailable = facts_from_parse_result(ParseResult(classification="FACT", has_new_fuel_information=True, reports=[FuelReportData(location="Победа", fuel_unavailable=["АИ-95", "АИ-100"], station_state="UNAVAILABLE")]), first.source_key, now, StationNormalizer())
        tied_available = facts_from_parse_result(ParseResult(classification="FACT", has_new_fuel_information=True, reports=[FuelReportData(location="Победа", fuel_available=["АИ-100"], station_state="AVAILABLE")]), second.source_key, now, StationNormalizer())
        newer_available = facts_from_parse_result(ParseResult(classification="FACT", has_new_fuel_information=True, reports=[FuelReportData(location="Победа", fuel_available=["АИ-95"], station_state="AVAILABLE")]), third.source_key, now + timedelta(minutes=1), StationNormalizer())
        await repository.save_facts(unavailable + tied_available + newer_available)
        latest = await repository.get_latest_facts(["ai_95", "ai_100"], now - timedelta(hours=1))
        assert {fact.fuel_type for fact in latest} == {"ai_95", "ai_100"}
        assert next(fact.state for fact in latest if fact.fuel_type == "ai_95") == "available"
        tied = await repository.get_latest_facts(["ai_100"], now - timedelta(hours=1))
        assert [fact.id for fact in tied] == [fact.id for fact in await repository.get_latest_facts(["ai_100"], now - timedelta(hours=1))]

    asyncio.run(with_repository(scenario))


def test_restriction_text_does_not_make_available_fuel_limited_without_structured_status() -> None:
    result = ParseResult(classification="FACT", has_new_fuel_information=True, reports=[
        FuelReportData(location="Победа", fuel_available=["АИ-95"], restrictions=["очередь"], station_state="AVAILABLE")
    ])
    facts = facts_from_parse_result(result, "telegram|1|1", datetime(2026, 9, 18, 12, tzinfo=UTC), StationNormalizer())
    assert [(fact.fuel_type, fact.state) for fact in facts] == [("ai_95", "available")]
