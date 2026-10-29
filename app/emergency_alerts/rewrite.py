from __future__ import annotations

import re

from pydantic import BaseModel

from app.emergency_alerts.core import SourcePost


class RewriteResult(BaseModel):
    text: str


class OriginalRewriter:
    async def rewrite(self, post: SourcePost) -> str:
        return post.text


def validate_rewrite(original: str, candidate: str) -> str:
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate or len(candidate) > 500:
        raise ValueError("rewrite is empty or too long")
    if candidate not in re.sub(r"\s+", " ", original).strip():
        raise ValueError("rewrite is not an exact excerpt of the original")
    if re.findall(r"\d+(?:[.,:/–-]\d+)*", original) != re.findall(r"\d+(?:[.,:/–-]\d+)*", candidate):
        raise ValueError("rewrite changed dates, times or road numbers")
    original_words = re.findall(r"[а-яёa-z]+", original.casefold())
    candidate_words = re.findall(r"[а-яёa-z]+", candidate.casefold())
    if len(candidate_words) < 4 or not set(candidate_words).issubset(set(original_words)):
        raise ValueError("rewrite introduced unsupported wording")
    markers = ("отбой", "отмен", "снят", "введ", "закры", "откры", "огранич", "восстанов")
    for marker in markers:
        if any(word.startswith(marker) for word in original_words) != any(word.startswith(marker) for word in candidate_words):
            raise ValueError("rewrite changed alert status")
    if ("не" in original_words) != ("не" in candidate_words):
        raise ValueError("rewrite changed negation")
    for marker in ("бпла", "беспилотн", "ракетн", "воздушн", "авиационн", "опасност", "угроз", "ковер", "дорог", "трасс", "движени", "проезд"):
        if any(word.startswith(marker) for word in original_words) != any(word.startswith(marker) for word in candidate_words):
            raise ValueError("rewrite changed alert subject")
    names = re.findall(r"\b[А-ЯЁ][а-яё]+\b|\b[А-ЯЁ]-\d+\b", original)
    if any(name.casefold() not in candidate.casefold() for name in names):
        raise ValueError("rewrite omitted a named place or road")
    return candidate


class GeminiRewriter:
    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def rewrite(self, post: SourcePost) -> str:
        from google.genai import types

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=post.text,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Ты редактор экстренных сообщений МЧС. Сократи текст до одного-двух предложений. "
                    "Используй только слова и числовые значения оригинала, без новых фактов, "
                    "без смены статуса объявления или отбоя. Сохрани все даты, время, километры и номера дорог. "
                    "Если безопасное сокращение невозможно, верни оригинал без изменений."
                ),
                response_mime_type="application/json",
                response_schema=RewriteResult,
            ),
        )
        parsed = response.parsed if response.parsed is not None else RewriteResult.model_validate_json(response.text or "")
        return validate_rewrite(post.text, RewriteResult.model_validate(parsed).text)
