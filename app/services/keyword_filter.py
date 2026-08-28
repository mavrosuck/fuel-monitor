import re

KEYWORDS = ["бензин", "топливо", "заправка", "заправляют", "заправиться", "азс", "аи-92", "аи92", "аи-95", "аи95", "аи-98", "аи98", "92", "95", "98", "дт", "дизель", "солярка", "очередь", "колонка", "колонки", "нет топлива", "топлива нет", "не заправляют", "появился", "появился бензин", "весь бензин", "башнефть", "лукойл", "роснефть", "газпром", "газпромнефть", "татнефть"]


def normalize_text(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\bаи[\s-]?(92|95|98)\b", r"аи\1", text)
    text = re.sub(r"\b(92|95|98)[-\s]?й\b", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def is_keyword_relevant(text: str) -> bool:
    normalized = normalize_text(text)
    return any(keyword.replace("-", "") in normalized.replace("-", "") for keyword in KEYWORDS)
