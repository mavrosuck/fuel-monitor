import pytest
from pydantic import ValidationError

from app.ai.schema import FuelReportData, ParseResult


@pytest.mark.parametrize("classification", ["QUESTION", "IRRELEVANT", "UNCERTAIN"])
def test_non_factual_categories_are_not_information(classification: str) -> None:
    result = ParseResult(classification=classification, has_new_fuel_information=False, reports=[])
    assert not result.has_new_fuel_information


def test_fact_is_information() -> None:
    result = ParseResult(
        classification="FACT",
        has_new_fuel_information=True,
        reports=[FuelReportData(station_state="AVAILABLE", fuel_available=["АИ-95"])],
    )
    assert result.has_new_fuel_information


def test_question_cannot_be_saved_as_a_fact() -> None:
    with pytest.raises(ValidationError):
        ParseResult(classification="QUESTION", has_new_fuel_information=True, reports=[])
