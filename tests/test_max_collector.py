import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.collector.max_collector import MaxCollectionError, MaxCollector
from app.collector.models import CollectedMessage
from app.runner import deduplicate_messages

CHAT_IDS = [-76867728756169, -76729715050629, -76783627133571]


class FakeWebClient:
    def __init__(self, *, chats, histories, **_kwargs) -> None:
        self.chats = chats
        self.histories = histories
        self.history_calls: list[int] = []
        self.closed = False
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def fetch_chats(self):
        return self.chats

    async def fetch_history(self, *, chat_id, **_kwargs):
        self.history_calls.append(chat_id)
        return self.histories[chat_id]


class StoppedWebClient(FakeWebClient):
    async def connect(self) -> None:
        return None


class HangingWebClient(FakeWebClient):
    async def connect(self) -> None:
        await asyncio.sleep(3600)


class HangingHistoryWebClient(FakeWebClient):
    async def fetch_history(self, *, chat_id, **_kwargs):
        self.history_calls.append(chat_id)
        await asyncio.sleep(3600)


class PagingWebClient(FakeWebClient):
    def __init__(self, *, chats, pages) -> None:
        super().__init__(chats=chats, histories={})
        self.pages = pages

    async def fetch_history(self, *, chat_id, **_kwargs):
        self.history_calls.append(chat_id)
        return self.pages.pop(0)


def settings(tmp_path: Path, chat_ids=CHAT_IDS):
    session = tmp_path / "max_web_session.db"
    session.write_bytes(b"session")
    return SimpleNamespace(max_session_path=str(session), max_source_chat_ids=chat_ids)


def test_max_collector_reads_only_configured_chats_and_filters_hour(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    start = end - timedelta(hours=1)
    chats = [SimpleNamespace(id=chat_id, title=f"chat {index}") for index, chat_id in enumerate(CHAT_IDS)]
    histories = {
        chat_id: [
            SimpleNamespace(id=1, time=int((end - timedelta(minutes=10)).timestamp() * 1000), text="Есть АИ-95"),
            SimpleNamespace(id=2, time=int((end - timedelta(hours=2)).timestamp() * 1000), text="Старое"),
        ]
        for chat_id in CHAT_IDS
    }
    fake = FakeWebClient(chats=chats, histories=histories)
    result = asyncio.run(MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake).collect_since(start, end))

    assert fake.history_calls == CHAT_IDS
    assert len(result.messages) == 3
    assert all(message.platform == "max" for message in result.messages)
    assert all(start < message.message_date <= end for message in result.messages)
    assert result.message_counts == {chat_id: 1 for chat_id in CHAT_IDS}
    assert fake.closed


def test_max_collector_fails_closed_when_a_required_chat_is_missing(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    fake = FakeWebClient(chats=[SimpleNamespace(id=CHAT_IDS[0], title="only one")], histories={})
    collector = MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake)

    with pytest.raises(MaxCollectionError, match="required MAX chats"):
        asyncio.run(collector.collect_since(end - timedelta(hours=1), end))


def test_max_collector_fails_closed_when_session_never_starts(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    fake = StoppedWebClient(chats=[], histories={})
    collector = MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake)

    with pytest.raises(MaxCollectionError, match="session is invalid"):
        asyncio.run(collector.collect_since(end - timedelta(hours=1), end))


def test_max_collector_times_out_when_existing_session_start_hangs(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    fake = HangingWebClient(chats=[], histories={})
    collector = MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake)
    collector.START_TIMEOUT_SECONDS = 0.01

    with pytest.raises(MaxCollectionError, match="start timed out"):
        asyncio.run(collector.collect_since(end - timedelta(hours=1), end))
    assert fake.closed


def test_max_collector_fails_closed_when_history_request_hangs(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    chats = [SimpleNamespace(id=chat_id, title=f"chat {index}") for index, chat_id in enumerate(CHAT_IDS)]
    fake = HangingHistoryWebClient(chats=chats, histories={})
    collector = MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake)
    collector.HISTORY_REQUEST_TIMEOUT_SECONDS = 0.01

    with pytest.raises(MaxCollectionError, match="history request timed out"):
        asyncio.run(collector.collect_since(end - timedelta(hours=1), end))
    assert fake.closed


def test_max_collector_configures_certifi_ca_bundle() -> None:
    assert os.environ["SSL_CERT_FILE"].endswith("cacert.pem")


def test_max_collector_paginates_past_five_messages_within_the_hour(tmp_path: Path) -> None:
    end = datetime(2026, 9, 14, 12, tzinfo=UTC)
    start = end - timedelta(hours=1)
    chats = [SimpleNamespace(id=chat_id, title=f"chat {index}") for index, chat_id in enumerate(CHAT_IDS)]
    first_page = [
        SimpleNamespace(id=index, time=int((end - timedelta(minutes=index)).timestamp() * 1000), text=f"message {index}")
        for index in range(1, 7)
    ]
    boundary_page = [SimpleNamespace(id=7, time=int(start.timestamp() * 1000), text="boundary")]
    pages = [first_page, boundary_page, boundary_page, boundary_page]
    fake = PagingWebClient(chats=chats, pages=pages)
    result = asyncio.run(MaxCollector(settings(tmp_path), client_factory=lambda **_kwargs: fake).collect_since(start, end))

    assert len(result.messages) == 9
    assert result.message_counts[CHAT_IDS[0]] == 7
    assert fake.history_calls.count(CHAT_IDS[0]) == 2


def test_cross_platform_exact_duplicates_are_counted_once_but_different_messages_remain() -> None:
    now = datetime.now(UTC)
    messages = [
        CollectedMessage("telegram", 1, 10, now - timedelta(minutes=1), "На АЗС есть АИ-95"),
        CollectedMessage("max", 2, 20, now, "На   АЗС есть АИ-95"),
        CollectedMessage("max", 2, 21, now, "На АЗС есть АИ-92"),
    ]
    unique = deduplicate_messages(messages)

    assert len(unique) == 2
    assert {message.source_message_id for message in unique} == {20, 21}


def test_max_collector_contains_no_mutation_api_calls() -> None:
    source = Path("app/collector/max_collector.py").read_text(encoding="utf-8")
    forbidden = [
        "send_message",
        "delete_message",
        "edit_message",
        "add_reaction",
        "join",
        "leave",
        "invite",
        "remove_user",
        "update_settings",
        "change_profile",
        "create_",
    ]
    assert not any(name in source for name in forbidden)
