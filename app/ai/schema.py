from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FuelReportData(BaseModel):
    brand: str | None = None
    location: str | None = None
    fuel_available: list[str] = Field(default_factory=list)
    fuel_unavailable: list[str] = Field(default_factory=list)
    price_text: str | None = None
    observed_time: str | None = None
    queue_text: str | None = None
    queue_cars: int | None = Field(default=None, ge=0)
    restrictions: list[str] = Field(default_factory=list)
    station_state: Literal["AVAILABLE", "LIMITED", "UNAVAILABLE"]
    additional_info: str | None = None


class ParseResult(BaseModel):
    classification: Literal["FACT", "QUESTION", "IRRELEVANT", "UNCERTAIN"]
    has_new_fuel_information: bool
    reports: list[FuelReportData] = Field(default_factory=list)

    @model_validator(mode="after")
    def reports_match_flag(self) -> "ParseResult":
        if self.classification == "FACT":
            if not self.has_new_fuel_information or not self.reports:
                raise ValueError("FACT must contain at least one concrete report")
        elif self.has_new_fuel_information or self.reports:
            raise ValueError("non-factual classifications cannot contain reports")
        return self


class BatchInput(BaseModel):
    source_message_id: int
    message_date: datetime
    text: str


class MessageParseResult(ParseResult):
    source_message_id: int


class BatchParseResult(BaseModel):
    results: list[MessageParseResult]
