from aiogram.types import MessageEntity

from app.services.formatter import FormattedSummary

MAX_CHANNEL_URL = "https://max.ru/join/J1t2oMGDqRoR0dXflWyYEliQvn4uKMy_J5gRYDTUOrs"
TELEGRAM_CHANNEL_URL = "https://t.me/+fbRdFGKMAPkxZTVi"

CTA_TITLE = "ВСЯ АКТУАЛЬНАЯ ИНФОРМАЦИЯ ПО ТОПЛИВУ 👇"
MAX_LABEL = "МЫ В МАКС"
TELEGRAM_LABEL = "МЫ В ТГ"


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _utf16_offset(value: str, offset: int) -> int:
    return _utf16_length(value[:offset])


def with_cta(summary: str | FormattedSummary) -> tuple[str, list[MessageEntity]]:
    """Appends fixed CTA entities without applying a parse mode to the message."""
    summary_text = summary.text if isinstance(summary, FormattedSummary) else summary
    summary_entities = []
    if isinstance(summary, FormattedSummary):
        summary_entities = [
            MessageEntity(
                type=style.type,
                offset=_utf16_offset(summary.text, style.offset),
                length=_utf16_length(summary.text[style.offset : style.offset + style.length]),
            )
            for style in summary.styles
        ]
    prefix = f"{summary_text}\n\n"
    labels = f"{MAX_LABEL} | {TELEGRAM_LABEL}"
    text = f"{prefix}{CTA_TITLE}\n\n{labels}"
    title_offset = _utf16_length(prefix)
    max_offset = _utf16_length(f"{prefix}{CTA_TITLE}\n\n")
    telegram_offset = max_offset + _utf16_length(f"{MAX_LABEL} | ")
    entities = [
        *summary_entities,
        MessageEntity(type="italic", offset=title_offset, length=_utf16_length(CTA_TITLE)),
        MessageEntity(type="bold", offset=max_offset, length=_utf16_length(MAX_LABEL)),
        MessageEntity(type="text_link", offset=max_offset, length=_utf16_length(MAX_LABEL), url=MAX_CHANNEL_URL),
        MessageEntity(type="bold", offset=telegram_offset, length=_utf16_length(TELEGRAM_LABEL)),
        MessageEntity(
            type="text_link",
            offset=telegram_offset,
            length=_utf16_length(TELEGRAM_LABEL),
            url=TELEGRAM_CHANNEL_URL,
        ),
    ]
    return text, entities
