from app.publisher.cta import (
    CTA_TITLE,
    MAX_CHANNEL_URL,
    MAX_LABEL,
    TELEGRAM_CHANNEL_URL,
    TELEGRAM_LABEL,
    with_cta,
)


def _utf16_slice(value: str, offset: int, length: int) -> str:
    encoded = value.encode("utf-16-le")
    return encoded[offset * 2 : (offset + length) * 2].decode("utf-16-le")


def test_cta_is_appended_after_an_unchanged_summary() -> None:
    summary = "ГДЕ БЕНЗИН, ОРЕНБУРГ? — 15:27, 14 сентября\n\n🟢 Топливо есть"

    text, entities = with_cta(summary)

    assert text == f"{summary}\n\n{CTA_TITLE}\n\n{MAX_LABEL} | {TELEGRAM_LABEL}"
    assert text.startswith(summary)
    assert MAX_CHANNEL_URL not in text
    assert TELEGRAM_CHANNEL_URL not in text
    assert entities[0].type == "italic"
    assert _utf16_slice(text, entities[0].offset, entities[0].length) == CTA_TITLE


def test_cta_links_use_text_entities_with_utf16_offsets_after_special_characters() -> None:
    summary = "АЗС 😀 _ <&>\n\n• Тест · АИ-95"

    text, entities = with_cta(summary)
    links = [entity for entity in entities if entity.type == "text_link"]

    assert [(entity.url, _utf16_slice(text, entity.offset, entity.length)) for entity in links] == [
        (MAX_CHANNEL_URL, MAX_LABEL),
        (TELEGRAM_CHANNEL_URL, TELEGRAM_LABEL),
    ]
