from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class AggregatedReport:
    station_normalized: str
    brand: str | None
    location: str | None
    fuel_available: list[str] = field(default_factory=list)
    fuel_unavailable: list[str] = field(default_factory=list)
    price_text: str | None = None
    observed_time: str | None = None
    queue_text: str | None = None
    queue_cars: int | None = None
    restrictions: list[str] = field(default_factory=list)
    station_state: str = "AVAILABLE"
    additional_info: str | None = None
    reported_at: datetime | None = None


def _union(old: list[str], new: list[str]) -> list[str]:
    return list(dict.fromkeys([*old, *new]))


def aggregate_reports(reports: list[AggregatedReport]) -> list[AggregatedReport]:
    grouped: dict[str, list[AggregatedReport]] = {}
    for report in reports:
        grouped.setdefault(report.station_normalized, []).append(report)
    result: list[AggregatedReport] = []
    for station_reports in grouped.values():
        ordered = sorted(station_reports, key=lambda report: report.reported_at or datetime.min)
        state = ordered[0]
        for newer in ordered[1:]:
            # A newer status supersedes an older contradictory fuel state.
            if newer.station_state == "UNAVAILABLE":
                state.fuel_available = []
                state.fuel_unavailable = newer.fuel_unavailable
                state.station_state = newer.station_state
            elif newer.station_state != state.station_state or newer.fuel_available or newer.fuel_unavailable:
                if newer.fuel_available:
                    state.fuel_available = newer.fuel_available
                    state.fuel_unavailable = newer.fuel_unavailable
                state.station_state = newer.station_state
            state.fuel_available = _union(state.fuel_available, newer.fuel_available)
            state.fuel_unavailable = _union(state.fuel_unavailable, newer.fuel_unavailable)
            state.restrictions = _union(state.restrictions, newer.restrictions)
            state.queue_text = newer.queue_text or state.queue_text
            state.queue_cars = newer.queue_cars if newer.queue_cars is not None else state.queue_cars
            state.price_text = newer.price_text or state.price_text
            state.observed_time = newer.observed_time or state.observed_time
            state.additional_info = newer.additional_info or state.additional_info
            state.brand = newer.brand or state.brand
            state.location = newer.location or state.location
            state.reported_at = newer.reported_at or state.reported_at
        result.append(state)
    return result
