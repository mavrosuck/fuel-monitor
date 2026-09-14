from datetime import UTC, datetime

from app.publisher.cta import (
    CTA_TITLE,
    MAX_CHANNEL_URL,
    MAX_LABEL,
    TELEGRAM_CHANNEL_URL,
    TELEGRAM_LABEL,
    with_cta,
)
from app.services.aggregator import AggregatedReport
from app.services.formatter import format_styled_summary


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


def test_full_post_uses_deterministic_utf16_entities_without_changing_fact_text() -> None:
    reports = [
        AggregatedReport(
            "ros", "Роснефть", "Шоссейная", fuel_available=["АИ-92", "АИ-95"],
            additional_info="работает", station_state="AVAILABLE",
            reported_at=datetime(2026, 9, 14, 9, 42, tzinfo=UTC),
        ),
        AggregatedReport(
            "special", None, "Тест 😀", fuel_available=["АИ-92"], queue_text="очередь 5–7 машин",
            station_state="AVAILABLE", reported_at=datetime(2026, 9, 14, 9, 53, tzinfo=UTC),
        ),
        AggregatedReport(
            "limit", "Башнефть", "Монтажников", restrictions=["только ДТ"],
            station_state="LIMITED", reported_at=datetime(2026, 9, 14, 9, 57, tzinfo=UTC),
        ),
        AggregatedReport(
            "none", "Башнефть", "Беляевская, 131", fuel_unavailable=["АИ-92", "АИ-95"],
            station_state="UNAVAILABLE", reported_at=datetime(2026, 9, 14, 10, 19, tzinfo=UTC),
        ),
    ]

    summary = format_styled_summary(reports, datetime(2026, 9, 14, 10, 27, tzinfo=UTC), "Asia/Yekaterinburg")
    text, entities = with_cta(summary)

    assert text == (
        "ГДЕ БЕНЗИН, ОРЕНБУРГ? — 15:27, 14 сентября\n\n"
        "🟢 Топливо есть\n\n"
        "• Тест 😀 — АИ-92, очередь 5–7 машин · 14:53\n"
        "• Роснефть · Шоссейная — АИ-92, АИ-95, работает · 14:42\n\n"
        "🟡 Есть ограничения\n\n"
        "• Башнефть · Монтажников — только ДТ · 14:57\n\n"
        "🔴 Топлива нет\n\n"
        "• Башнефть · Беляевская, 131 — АИ-92 нет, АИ-95 нет · 15:19\n\n"
        "ВСЯ АКТУАЛЬНАЯ ИНФОРМАЦИЯ ПО ТОПЛИВУ 👇\n\n"
        "МЫ В МАКС | МЫ В ТГ"
    )
    assert MAX_CHANNEL_URL not in text and TELEGRAM_CHANNEL_URL not in text

    entity_values = [(entity.type, _utf16_slice(text, entity.offset, entity.length), entity.url) for entity in entities]
    assert entity_values == [
        ("bold", "ГДЕ БЕНЗИН, ОРЕНБУРГ?", None),
        ("italic", "15:27, 14 сентября", None),
        ("bold", "🟢 Топливо есть", None),
        ("bold", "Тест 😀", None),
        ("italic", "14:53", None),
        ("bold", "Роснефть · Шоссейная", None),
        ("italic", "14:42", None),
        ("bold", "🟡 Есть ограничения", None),
        ("bold", "Башнефть · Монтажников", None),
        ("italic", "14:57", None),
        ("bold", "🔴 Топлива нет", None),
        ("bold", "Башнефть · Беляевская, 131", None),
        ("italic", "15:19", None),
        ("italic", CTA_TITLE, None),
        ("bold", MAX_LABEL, None),
        ("text_link", MAX_LABEL, MAX_CHANNEL_URL),
        ("bold", TELEGRAM_LABEL, None),
        ("text_link", TELEGRAM_LABEL, TELEGRAM_CHANNEL_URL),
    ]


def test_empty_sections_are_omitted_and_location_without_brand_is_bold() -> None:
    summary = format_styled_summary(
        [
            AggregatedReport(
                "location-only", None, "Локация <&> 😀", station_state="UNAVAILABLE",
                reported_at=datetime(2026, 9, 14, 10, 19, tzinfo=UTC),
            )
        ],
        datetime(2026, 9, 14, 10, 27, tzinfo=UTC),
        "Asia/Yekaterinburg",
    )
    text, entities = with_cta(summary)

    assert "🟢" not in text and "🟡" not in text
    bold_values = [_utf16_slice(text, entity.offset, entity.length) for entity in entities if entity.type == "bold"]
    assert "Локация <&> 😀" in bold_values
