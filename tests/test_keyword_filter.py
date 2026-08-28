from app.services.keyword_filter import is_keyword_relevant


def test_keyword_filter() -> None:
    assert is_keyword_relevant("На Лукойле появился 95")
    assert is_keyword_relevant("Где сейчас есть бензин?")
    assert not is_keyword_relevant("Доброе утро всем")
