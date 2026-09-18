from dataclasses import dataclass
from datetime import datetime

from app.ai.schema import ParseResult
from app.services.station_normalizer import StationNormalizer


CANONICAL_FUELS = {
    "АИ-92": "ai_92", "АИ 92": "ai_92", "АИ-95": "ai_95", "АИ 95": "ai_95",
    "АИ-100": "ai_100", "АИ 100": "ai_100", "ДТ": "diesel", "ДИЗЕЛЬ": "diesel", "ГАЗ": "gas",
}


@dataclass(frozen=True)
class FuelFactInput:
    source_key: str
    station_normalized: str
    station_brand: str | None
    station_location: str | None
    fuel_type: str
    state: str
    price_text: str | None
    queue_text: str | None
    queue_cars: int | None
    restrictions: list[str]
    additional_info: str | None
    observed_at: datetime
    observed_time_text: str | None


def canonical_fuel_type(value: str) -> str | None:
    return CANONICAL_FUELS.get(" ".join(value.strip().upper().split()))


def facts_from_parse_result(result: ParseResult, source_key: str, source_message_date: datetime, normalizer: StationNormalizer) -> list[FuelFactInput]:
    if source_message_date.tzinfo is None:
        raise ValueError("source message date must be timezone-aware")
    if result.classification != "FACT" or not result.has_new_fuel_information:
        return []
    facts: list[FuelFactInput] = []
    for report in result.reports:
        available = {canonical_fuel_type(value) for value in report.fuel_available}
        unavailable = {canonical_fuel_type(value) for value in report.fuel_unavailable}
        for fuel_type in sorted((available - unavailable) - {None}):
            facts.append(_fact(source_key, report, normalizer, fuel_type, "limited" if report.station_state == "LIMITED" else "available", source_message_date))
        for fuel_type in sorted(unavailable - {None}):
            facts.append(_fact(source_key, report, normalizer, fuel_type, "unavailable", source_message_date))
    return facts


def _fact(source_key, report, normalizer, fuel_type, state, observed_at) -> FuelFactInput:
    return FuelFactInput(source_key, normalizer.normalize(report.brand, report.location), report.brand, report.location, fuel_type, state, report.price_text, report.queue_text, report.queue_cars, list(report.restrictions), report.additional_info, observed_at, report.observed_time)
