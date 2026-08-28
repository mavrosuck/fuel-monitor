"""Render the current hourly summary without using Bot API or writing publications."""

import asyncio

from app.config import get_settings
from app.database.database import Database
from app.services.report_service import ReportService


async def run_preview() -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        await database.create_tables()
        async with database.session_factory() as session:
            prepared = await ReportService(
                session, settings.min_reports_to_publish, settings.timezone
            ).build_preview_summary()
        if not prepared:
            print("Нет информационных сообщений для preview в текущем часовом окне.")
            return 0
        text, count, start, end = prepared
        print(f"Preview: {count} уникальных информационных сообщений ({start.isoformat()} — {end.isoformat()})\n")
        print(text)
        return 0
    finally:
        await database.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run_preview()))


if __name__ == "__main__":
    main()
