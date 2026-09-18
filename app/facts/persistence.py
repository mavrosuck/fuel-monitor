import logging
import ssl
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

from pydantic import SecretStr

from app.ai.schema import MessageParseResult
from app.collector.models import CollectedMessage
from app.database.database import Database
from app.facts.conversion import facts_from_parse_result
from app.facts.repository import FactsRepository, content_hash_for_text
from app.services.station_normalizer import StationNormalizer

logger = logging.getLogger(__name__)

_INCOMPATIBLE_ASYNCPG_PARAMETERS = {"sslmode", "channel_binding"}


def validate_neon_collector_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "postgresql+asyncpg" or not parsed.hostname:
        raise ValueError("Neon collector URL must use the postgresql+asyncpg scheme and a host")
    if "-pooler." in parsed.hostname:
        raise ValueError("Neon collector URL must use a direct endpoint in Stage B1")
    query_names = {name for name, _value in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_names & _INCOMPATIBLE_ASYNCPG_PARAMETERS:
        raise ValueError("Neon collector URL must not include sslmode or channel_binding")


def create_neon_facts_persistence(url: SecretStr | None) -> "NeonFactsPersistence | None":
    if url is None:
        return None
    try:
        raw_url = url.get_secret_value()
        validate_neon_collector_url(raw_url)
        ssl_context = ssl.create_default_context()
        return NeonFactsPersistence(Database(raw_url, connect_args={"ssl": ssl_context}))
    except Exception as exc:
        logger.warning("Neon facts persistence disabled: %s", type(exc).__name__)
        return None


class NeonFactsPersistence:
    """Best-effort Stage B1 sidecar storage that never controls publication."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.disabled = False

    async def persist(
        self,
        message: CollectedMessage,
        result: MessageParseResult,
        normalizer: StationNormalizer,
        processed_at: datetime | None = None,
    ) -> None:
        if self.disabled:
            return
        now = processed_at or datetime.now(UTC)
        try:
            async with self.database.session_factory() as session:
                async with session.begin():
                    repository = FactsRepository(session)
                    source = await repository.register_source_message(
                        message.platform,
                        message.source_chat_id,
                        message.source_message_id,
                        message.message_date,
                        content_hash_for_text(message.text),
                    )
                    claimed = await repository.claim_source_message(source.source_key, now)
                    if claimed is None:
                        return
                    facts = facts_from_parse_result(result, source.source_key, message.message_date, normalizer)
                    await repository.save_facts(facts)
                    await repository.mark_source_processed(source.source_key, now)
        except Exception as exc:
            self.disabled = True
            logger.warning("Neon facts persistence disabled for this run: %s", type(exc).__name__)

    async def close(self) -> None:
        try:
            await self.database.dispose()
        except Exception as exc:
            logger.warning("Neon facts persistence close failed: %s", type(exc).__name__)
