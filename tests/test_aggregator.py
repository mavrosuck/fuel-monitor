from datetime import UTC, datetime, timedelta

from app.services.aggregator import AggregatedReport, aggregate_reports


def test_newer_availability_replaces_old_unavailable() -> None:
    now = datetime.now(UTC)
    reports = [AggregatedReport("station", "Лукойл", "Джангильдина", station_state="UNAVAILABLE", reported_at=now), AggregatedReport("station", "Лукойл", "Джангильдина", fuel_available=["АИ-92"], station_state="AVAILABLE", reported_at=now + timedelta(minutes=30))]
    result = aggregate_reports(reports)[0]
    assert result.station_state != "UNAVAILABLE"
    assert result.fuel_available == ["АИ-92"]


def test_merges_queue_details() -> None:
    now = datetime.now(UTC)
    reports = [AggregatedReport("station", "Башнефть", "Победы", fuel_available=["АИ-92", "АИ-95"], station_state="AVAILABLE", reported_at=now), AggregatedReport("station", "Башнефть", "Победы", queue_cars=10, queue_text="очередь 10 машин", station_state="AVAILABLE", reported_at=now + timedelta(minutes=1))]
    result = aggregate_reports(reports)[0]
    assert result.fuel_available == ["АИ-92", "АИ-95"]
    assert result.queue_text == "очередь 10 машин"
    assert result.reported_at == now + timedelta(minutes=1)


def test_newer_unavailability_clears_old_available_fuels() -> None:
    now = datetime.now(UTC)
    reports = [AggregatedReport("station", "Лукойл", "Победы", fuel_available=["АИ-95"], station_state="AVAILABLE", reported_at=now), AggregatedReport("station", "Лукойл", "Победы", station_state="UNAVAILABLE", reported_at=now + timedelta(minutes=1))]
    result = aggregate_reports(reports)[0]
    assert result.station_state == "UNAVAILABLE"
    assert result.fuel_available == []


def test_newer_fact_updates_only_its_station_and_timestamp() -> None:
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    reports = [
        AggregatedReport("pobeda", "Башнефть", "Победы", fuel_available=["АИ-92"], station_state="AVAILABLE", reported_at=now),
        AggregatedReport("montaznikov", "Башнефть", "Монтажников", restrictions=["только ДТ"], station_state="LIMITED", reported_at=now),
        AggregatedReport("pobeda", "Башнефть", "Победы", fuel_available=["АИ-92", "АИ-95"], station_state="AVAILABLE", reported_at=now + timedelta(minutes=14)),
    ]

    aggregated = {report.station_normalized: report for report in aggregate_reports(reports)}

    assert aggregated["pobeda"].fuel_available == ["АИ-92", "АИ-95"]
    assert aggregated["pobeda"].reported_at == now + timedelta(minutes=14)
    assert aggregated["montaznikov"].reported_at == now


def test_superseded_report_source_is_not_in_final_provenance() -> None:
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    reports = [
        AggregatedReport("pobeda", "Башнефть", "Победы", fuel_available=["АИ-95"], station_state="AVAILABLE", reported_at=now, source_keys={"telegram|1|1"}),
        AggregatedReport("pobeda", "Башнефть", "Победы", fuel_unavailable=["АИ-95"], station_state="UNAVAILABLE", reported_at=now + timedelta(minutes=5), source_keys={"max|2|2"}),
    ]

    result = aggregate_reports(reports)[0]

    assert result.source_keys == {"max|2|2"}
