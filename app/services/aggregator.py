from dataclasses import dataclass, field
from datetime import UTC, datetime

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
    source_keys: set[str] = field(default_factory=set)


def _union(old: list[str], new: list[str]) -> list[str]:
    return list(dict.fromkeys([*old, *new]))


def aggregate_reports(reports: list[AggregatedReport]) -> list[AggregatedReport]:
    grouped: dict[str, list[AggregatedReport]] = {}
    for report in reports:
        grouped.setdefault(report.station_normalized, []).append(report)
    result: list[AggregatedReport] = []
    for station_reports in grouped.values():
        ordered = sorted(
            station_reports,
            key=lambda report: report.reported_at or datetime.min.replace(tzinfo=UTC),
        )
        state = ordered[0]
        origins: dict[str, set[str]] = {
            "station_state": set(state.source_keys),
            "fuel_available": set(state.source_keys) if state.fuel_available else set(),
            "fuel_unavailable": set(state.source_keys) if state.fuel_unavailable else set(),
            "restrictions": set(state.source_keys) if state.restrictions else set(),
            "queue": set(state.source_keys) if state.queue_text or state.queue_cars is not None else set(),
            "price": set(state.source_keys) if state.price_text else set(),
            "observed_time": set(state.source_keys) if state.observed_time else set(),
            "additional_info": set(state.source_keys) if state.additional_info else set(),
        }
        for newer in ordered[1:]:
            # A newer status supersedes an older contradictory fuel state.
            if newer.station_state == "UNAVAILABLE":
                state.fuel_available = []
                state.fuel_unavailable = newer.fuel_unavailable
                state.station_state = newer.station_state
                origins["fuel_available"] = set()
                origins["fuel_unavailable"] = set(newer.source_keys)
                origins["station_state"] = set(newer.source_keys)
            elif newer.station_state != state.station_state or newer.fuel_available or newer.fuel_unavailable:
                if newer.fuel_available:
                    state.fuel_available = newer.fuel_available
                    state.fuel_unavailable = newer.fuel_unavailable
                    origins["fuel_available"] = set(newer.source_keys)
                    origins["fuel_unavailable"] = set(newer.source_keys) if newer.fuel_unavailable else set()
                state.station_state = newer.station_state
                origins["station_state"] = set(newer.source_keys)
            state.fuel_available = _union(state.fuel_available, newer.fuel_available)
            state.fuel_unavailable = _union(state.fuel_unavailable, newer.fuel_unavailable)
            state.restrictions = _union(state.restrictions, newer.restrictions)
            if newer.fuel_available:
                origins["fuel_available"].update(newer.source_keys)
            if newer.fuel_unavailable:
                origins["fuel_unavailable"].update(newer.source_keys)
            if newer.restrictions:
                origins["restrictions"].update(newer.source_keys)
            if newer.queue_text or newer.queue_cars is not None:
                state.queue_text = newer.queue_text or state.queue_text
                state.queue_cars = newer.queue_cars if newer.queue_cars is not None else state.queue_cars
                origins["queue"] = set(newer.source_keys)
            if newer.price_text:
                state.price_text = newer.price_text
                origins["price"] = set(newer.source_keys)
            if newer.observed_time:
                state.observed_time = newer.observed_time
                origins["observed_time"] = set(newer.source_keys)
            if newer.additional_info:
                state.additional_info = newer.additional_info
                origins["additional_info"] = set(newer.source_keys)
            state.brand = newer.brand or state.brand
            state.location = newer.location or state.location
            state.reported_at = newer.reported_at or state.reported_at
        state.source_keys = set().union(*origins.values())
        result.append(state)
    return result
