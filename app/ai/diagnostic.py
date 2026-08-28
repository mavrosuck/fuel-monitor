"""Run the real Structured Output parser against stored messages without publishing."""

import argparse
import asyncio
import json
from datetime import datetime

from sqlalchemy import select

from app.ai.parser import FuelAIParser
from app.ai.schema import ParseResult
from app.config import get_settings
from app.database.database import Database
from app.database.models import SourceMessage


def format_result(message: SourceMessage, result: ParseResult) -> str:
    """Produces human-readable diagnostic output without exposing configuration."""
    source = message.chat_username or str(message.chat_id)
    header = (
        f"source={source} message_id={message.telegram_message_id} "
        f"date={message.message_date.isoformat()} classification={result.classification}"
    )
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return f"{header}\ntext={message.message_text}\nresult={payload}\n"


async def run_diagnostic(limit: int) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            messages = (
                await session.scalars(
                    select(SourceMessage).order_by(SourceMessage.message_date.desc()).limit(limit)
                )
            ).all()
        if not messages:
            print("No source messages found in PostgreSQL.")
            return 0
        parser = FuelAIParser(settings.openai_api_key.get_secret_value(), settings.openai_model)
        for message in reversed(messages):
            try:
                result = await parser.parse(message.message_text)
                print(format_result(message, result))
            except Exception as exc:
                # The exception text is not expected to contain credentials; do not log settings.
                print(f"source={message.chat_username or message.chat_id} message_id={message.telegram_message_id} parser_error={type(exc).__name__}")
        return 0
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose stored fuel messages without publishing.")
    parser.add_argument("--limit", type=int, default=20, choices=range(1, 101))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_diagnostic(args.limit)))


if __name__ == "__main__":
    main()
