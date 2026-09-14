"""Final invariant for publication after aggregation."""

from app.services.aggregator import AggregatedReport


def publishable_fuel_facts(aggregated: list[AggregatedReport]) -> int:
    """Each aggregated station is exactly one current publishable fuel fact."""
    return len(aggregated)


def publication_allowed(aggregated: list[AggregatedReport], minimum_facts: int) -> bool:
    if minimum_facts < 1:
        raise ValueError("minimum publishable fuel facts must be positive")
    return publishable_fuel_facts(aggregated) >= minimum_facts
