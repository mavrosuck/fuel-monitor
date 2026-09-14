from app.services.keyword_filter import is_keyword_relevant


def test_keyword_filter() -> None:
    assert is_keyword_relevant("На Лукойле появился 95")
    assert is_keyword_relevant("Где сейчас есть бензин?")
    assert not is_keyword_relevant("Доброе утро всем")


def test_keyword_filter_keeps_short_natural_fuel_reports() -> None:
    assert is_keyword_relevant("На Победе 95 есть")
    assert is_keyword_relevant("Терешковой без 92")
    assert is_keyword_relevant("На Монтажников только дизель")
