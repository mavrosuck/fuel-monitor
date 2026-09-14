from aiogram.types import MessageEntity

MAX_CHANNEL_URL = "https://max.ru/join/J1t2oMGDqRoR0dXflWyYEliQvn4uKMy_J5gRYDTUOrs"
TELEGRAM_CHANNEL_URL = "https://t.me/+fbRdFGKMAPkxZTVi"

CTA_TITLE = "ВСЯ АКТУАЛЬНАЯ ИНФОРМАЦИЯ ПО ТОПЛИВУ 👇"
MAX_LABEL = "МЫ В МАКС"
TELEGRAM_LABEL = "МЫ В ТГ"


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def with_cta(summary: str) -> tuple[str, list[MessageEntity]]:
    """Appends the fixed CTA while leaving the formatter output literal."""
    prefix = f"{summary}\n\n"
    labels = f"{MAX_LABEL} | {TELEGRAM_LABEL}"
    text = f"{prefix}{CTA_TITLE}\n\n{labels}"
    title_offset = _utf16_length(prefix)
    max_offset = _utf16_length(f"{prefix}{CTA_TITLE}\n\n")
    telegram_offset = max_offset + _utf16_length(f"{MAX_LABEL} | ")
    entities = [
        MessageEntity(type="italic", offset=title_offset, length=_utf16_length(CTA_TITLE)),
        MessageEntity(type="text_link", offset=max_offset, length=_utf16_length(MAX_LABEL), url=MAX_CHANNEL_URL),
        MessageEntity(
            type="text_link",
            offset=telegram_offset,
            length=_utf16_length(TELEGRAM_LABEL),
            url=TELEGRAM_CHANNEL_URL,
        ),
    ]
    return text, entities
