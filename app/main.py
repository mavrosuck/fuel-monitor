import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.parser import FuelAIParser
from app.collector.message_handler import MessageHandler
from app.collector.telegram_client import TelegramCollector
from app.config import get_settings
from app.database.database import Database
from app.database.models import SystemState
from app.publisher.telegram_publisher import TelegramPublisher
from app.scheduler.hourly_job import run_hourly_job
from app.services.batch_classifier import BatchClassifier
from app.services.station_normalizer import StationNormalizer

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
database = Database(settings.database_url)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await database.create_tables()
    async with database.session_factory() as session:
        if await session.get(SystemState, "started_at") is None:
            session.add(SystemState(key="started_at", value={"timestamp": datetime.now(UTC).isoformat()}))
            await session.commit()
    parser = FuelAIParser(settings.openai_api_key.get_secret_value(), settings.openai_model)
    handler = MessageHandler(database.session_factory, BatchClassifier(parser), StationNormalizer())
    collector = TelegramCollector(settings, handler)
    publisher = TelegramPublisher(settings.bot_token.get_secret_value(), settings.target_channel)
    await collector.start()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(run_hourly_job, CronTrigger(minute=settings.schedule_minute, second=settings.schedule_second, timezone=settings.timezone), args=[database.session_factory, publisher, handler, settings.min_reports_to_publish, settings.timezone], id="hourly_report", max_instances=1, coalesce=True)
    scheduler.start()
    collector_task = asyncio.create_task(collector.run())
    logger.info("Application started")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        collector_task.cancel()
        await collector.stop()
        await publisher.close()
        await database.dispose()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.health_port)
