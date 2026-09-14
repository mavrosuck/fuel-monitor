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


def test_short_natural_fuel_fact_has_one_report() -> None:
    result = ParseResult(
        classification="FACT",
        has_new_fuel_information=True,
        reports=[
            FuelReportData(
                location="Победе",
                fuel_available=["АИ-92", "АИ-95"],
                queue_cars=7,
                station_state="AVAILABLE",
            )
        ],
    )
    assert len(result.reports) == 1
    assert result.reports[0].brand is None


@pytest.mark.parametrize("count", [3, 8])
def test_multi_station_fact_can_contain_any_number_of_reports(count: int) -> None:
    result = ParseResult(
        classification="FACT",
        has_new_fuel_information=True,
        reports=[
            FuelReportData(location=f"Локация {index}", fuel_available=["АИ-92"], station_state="AVAILABLE")
            for index in range(count)
        ],
    )
    assert len(result.reports) == count


@pytest.mark.parametrize("classification", ["QUESTION", "UNCERTAIN"])
def test_questions_and_rumors_are_not_facts(classification: str) -> None:
    result = ParseResult(classification=classification, has_new_fuel_information=False, reports=[])
    assert result.reports == []
