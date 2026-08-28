import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.collector.telegram_client import inspect_source_chats


class FakeClient:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def get_entity(self, source: str):
        self.requested.append(source)
        return SimpleNamespace(id=100 + len(self.requested), title=f"Chat {source}", username=source)

    async def iter_messages(self, entity, limit: int):
        assert limit == 5
        for message_id in (3, 2):
            yield SimpleNamespace(id=message_id, date=datetime(2026, 8, 28, tzinfo=UTC), raw_text="x" * 350)


def test_inspect_source_chats_reads_requested_sources_and_truncates_text() -> None:
    client = FakeClient()
    result = asyncio.run(inspect_source_chats(client, ["GdeBenzin56", "benzin156ru"]))

    assert client.requested == ["GdeBenzin56", "benzin156ru"]
    assert len(result) == 2
    assert result[0].title == "Chat GdeBenzin56"
    assert len(result[0].messages[0][2]) == 300


class FailingClient(FakeClient):
    async def get_entity(self, source: str):
        if source == "benzin156ru":
            raise RuntimeError("access denied")
        return await super().get_entity(source)


def test_inspect_source_chats_continues_when_one_source_is_unavailable() -> None:
    result = asyncio.run(inspect_source_chats(FailingClient(), ["GdeBenzin56", "benzin156ru"]))

    assert result[0].error is None
    assert result[1].error == "access denied"
    assert result[1].messages == []
