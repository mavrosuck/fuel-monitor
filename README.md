# Fuel Monitor — Оренбург

Одноразовая задача: за каждый запуск читает текстовые сообщения последнего часа из `GdeBenzin56` и `benzin156ru`, устраняет дубликаты, локально фильтрует шум и одним запросом Gemini классифицирует остаток. Сводка публикуется в Telegram только при пяти или более уникальных FACT-сообщениях.

```text
GitHub Actions → Telethon → keyword filter + deduplication → Gemini Structured Output
                                                               ↓
Bot API ← formatter + aggregator ← FACT only (minimum: 5)
```

PostgreSQL, FastAPI, APScheduler и OpenAI в рабочем запуске не используются.

## Настройка

В GitHub repository secrets добавьте только `GEMINI_API_KEY`. Workflow также использует уже существующие `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `BOT_TOKEN` и `TELETHON_SESSION_B64`. Секреты и файлы `*.session` не коммитятся.

Используется `gemini-3.5-flash-lite`: модель поддерживает Pydantic structured output и доступна на Gemini Free Tier с ограничениями. Проверьте актуальные [лимиты и условия Gemini](https://ai.google.dev/gemini-api/docs/pricing) перед включением регулярного запуска.

## Локальная проверка

Скопируйте `.env.example` в `.env`, задайте путь к уже авторизованной Telethon session без суффикса `.session`, затем выполните:

```bash
python -m pip install -r requirements.txt
DRY_RUN=1 python -m app.runner
```

`DRY_RUN=1` читает Telegram, вызывает Gemini и печатает готовую сводку, но не вызывает Bot API.

## GitHub Actions

[`main.yml`](.github/workflows/main.yml) допускает ручной запуск через `workflow_dispatch`; он по умолчанию безопасный (`DRY_RUN=1`). Также в нём настроен запуск каждый час (`0 * * * *`, UTC). Scheduled run использует `DRY_RUN=0` и поэтому публикует отчёт после успешной ручной проверки.

Сессия Telethon декодируется из `TELETHON_SESSION_B64` только во временном runner'е GitHub Actions. SMS-авторизация не требуется.

## Проверки

```bash
python -m compileall -q app tests
pytest
```
