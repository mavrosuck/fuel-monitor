# Fuel Monitor — Оренбург

За каждый запуск collector читает сообщения последних 30 минут из Telegram и read-only MAX/PyMax источников, устраняет дубликаты, локально фильтрует шум и одним запросом Gemini классифицирует остаток. Структурированные FACT сохраняются в Neon с исходным timestamp сообщения. Telegram-сводка публикуется только при пяти или более уникальных FACT-сообщениях.

```text
GitHub Actions → Telethon → keyword filter + deduplication → Gemini Structured Output
                                                               ↓
Bot API ← formatter + aggregator ← FACT only (minimum: 5)
```

PostgreSQL, FastAPI, APScheduler и OpenAI в рабочем запуске не используются.

## Будущее shared facts storage

Опциональный persistence layer использует `NEON_COLLECTOR_DATABASE_URL` для collector. URL должен использовать `postgresql+asyncpg://` и не содержать `sslmode` или `channel_binding`: TLS включается отдельным проверяющим `SSLContext`. При отсутствии переменной рабочий запуск не создаёт Neon engine. Read-only MAX-бот использует отдельный `NEON_BOT_FACTS_DATABASE_URL` и показывает только FACT с исходным timestamp не старше трёх часов.

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

[`main.yml`](.github/workflows/main.yml) запускает collector каждые 10 минут (`7,17,27,37,47,57`, UTC): эти scheduled run используют `DRY_RUN=1`, читают последние 30 минут, сохраняют свежие FACT в Neon, но не публикуют в Telegram. Отдельный scheduled run выполняется в `01:00, 04:00, 07:00, 10:00, 13:00, 16:00, 19:00, 22:00` UTC — это `00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00` по Оренбургу. Он использует `DRY_RUN=0`, берёт сообщения только за последний час перед соответствующим оренбургским слотом и сохраняет runtime state для дедупликации. Границы окна всегда привязаны к запланированному слоту; если GitHub Actions начнёт публикационный запуск более чем на 15 минут позже, запуск завершится ошибкой до сбора данных и ничего не опубликует. Ручной `workflow_dispatch` отключён, чтобы внешние часовые запуски не могли публиковать дополнительные сводки.

Сессия Telethon декодируется из `TELETHON_SESSION_B64` только во временном runner'е GitHub Actions. SMS-авторизация не требуется.

## Проверки

```bash
python -m compileall -q app tests
pytest
```
