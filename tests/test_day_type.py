from datetime import datetime

from app.services.formatter import day_type


def test_day_type() -> None:
    assert day_type(datetime(2026, 8, 28)) == "ЧЕТНЫЙ ДЕНЬ"
    assert day_type(datetime(2026, 8, 29)) == "НЕЧЕТНЫЙ ДЕНЬ"
