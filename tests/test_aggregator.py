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


def test_newer_unavailability_clears_old_available_fuels() -> None:
    now = datetime.now(UTC)
    reports = [AggregatedReport("station", "Лукойл", "Победы", fuel_available=["АИ-95"], station_state="AVAILABLE", reported_at=now), AggregatedReport("station", "Лукойл", "Победы", station_state="UNAVAILABLE", reported_at=now + timedelta(minutes=1))]
    result = aggregate_reports(reports)[0]
    assert result.station_state == "UNAVAILABLE"
    assert result.fuel_available == []
