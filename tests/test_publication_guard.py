from app.services.aggregator import AggregatedReport
from app.services.publication_guard import publication_allowed, publishable_fuel_facts


def _report(station: str) -> AggregatedReport:
    return AggregatedReport(station, None, station, station_state="AVAILABLE")


def test_final_publication_guard_requires_two_distinct_aggregated_stations() -> None:
    assert publishable_fuel_facts([_report("A")]) == 1
    assert not publication_allowed([_report("A")], 2)
    assert publication_allowed([_report("A"), _report("B")], 2)
