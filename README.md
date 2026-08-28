# Fuel Monitor — Оренбург

Готовый сервис, который читает новые посты `GdeBenzin56` и `benzin156ru` через отдельный Telegram-аккаунт, извлекает факты через OpenAI и раз в час публикует сводку в `@benzinoren`, когда накопилось не менее пяти информационных сообщений.

## Архитектура

```text
Telethon user account → keyword filter → OpenAI Structured Outputs → PostgreSQL
                                                                    ↓
APScheduler (каждый час) → aggregator → Markdown formatter → aiogram Bot API
```

Collector и publisher намеренно используют разные Telegram-сущности: пользовательский аккаунт читает источники, бот лишь публикует в канал.

## Перед запуском

Нужны Docker и Docker Compose, Telegram `api_id`/`api_hash` из [Telegram API Development Tools](https://my.telegram.org/apps), отдельный Telegram-аккаунт для мониторинга, токен бота и ключ OpenAI. При необходимости аккаунт-монитор должен иметь доступ к источникам, а бот — быть администратором `@benzinoren` с правом публикации.

## Первый запуск

```bash
cp .env.example .env
```

Заполните все пустые значения в `.env`. Сначала создайте постоянную сессию Telethon — команда запросит код Telegram (и пароль 2FA, если он включён):

```bash
docker compose run --rm app python -m app.collector.login
```

Затем запустите сервис:

```bash
docker compose up -d --build
docker compose logs -f app
```

При пустой БД время первого запуска сохраняется в техническом состоянии; старые посты не публикуются. Если OpenAI временно недоступен, исходное сообщение остаётся в базе как необработанное и повторно разбирается следующей почасовой задачей. Сессия Telethon и PostgreSQL хранятся в Docker volumes.

Проверка состояния: `curl http://localhost:8080/health`.

Проверить сохранённую Telethon session и доступ к источникам без отправки сообщений можно так:

```bash
docker compose run --rm app python -m app.collector.diagnostic
```

Команда не запрашивает код входа: если persistent session не авторизована, она завершится с понятной ошибкой и предложит выполнить `python -m app.collector.login`.

## Диагностика AI без публикации

AI-диагностика читает последние сообщения только из PostgreSQL, повторно не обращается к Telegram и не создаёт публикаций:

```bash
docker compose exec app python -m app.ai.diagnostic
docker compose exec app python -m app.ai.diagnostic --limit 50
```

Для каждого сообщения выводятся источник, Telegram message ID, дата, исходный текст, категория (`FACT`, `QUESTION`, `IRRELEVANT` или `UNCERTAIN`) и строгий JSON-результат извлечения. Вопросы и недостаточно определённые формулировки не становятся фактами.

Предпросмотр применяет тот же выбор сообщений, агрегатор и форматтер, что и почасовая задача, но не вызывает Bot API и не создаёт запись `publications`:

```bash
docker compose exec app python -m app.publisher.preview
```

Остановка: `docker compose down`. Обновление: `git pull && docker compose up -d --build`.

## Тесты

```bash
python -m pip install -r requirements.txt
pytest
```

## Поведение публикаций

Каждая задача считает уникальные FACT-сообщения только за последний час (и не раньше последней успешной публикации или времени первого запуска). Идентичные репосты по нормализованному тексту считаются один раз. Backfill сохраняется для диагностики и дедупликации, но не является FACT и поэтому не увеличивает счётчик. При числе менее пяти не публикуется ничего. При успехе Bot API создаёт отдельный пост, после чего в транзакции сохраняется запись `publications`.

Время заголовка и чётность дня определяются в `Asia/Yekaterinburg` — корректной IANA timezone для Оренбурга (UTC+5), а не по UTC контейнера.
