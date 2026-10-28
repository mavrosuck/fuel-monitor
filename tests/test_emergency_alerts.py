import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.emergency_alerts.core import (
    SOURCE_CHANNEL,
    TARGET_CHANNEL,
    SourcePost,
    claim_delivery,
    classify,
    event_transition,
    open_store,
    record_removal,
    register_post,
)
from app.emergency_alerts.max_source import PreparedMaxReader, from_verified_message
from app.emergency_alerts.pipeline import EmergencyPipeline
from app.emergency_alerts.rewrite import GeminiRewriter, validate_rewrite
from app.emergency_alerts.telegram import EmergencyTelegramSender
from app.emergency_alerts.worker import run_forever


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def post(text: str, **changes) -> SourcePost:
    data = dict(
        post_id="test-post-1",
        channel_url=SOURCE_CHANNEL,
        post_url=f"{SOURCE_CHANNEL}/test-post-1",
        published_at=NOW - timedelta(minutes=2),
        text=text,
    )
    data.update(changes)
    return SourcePost(**data)


@pytest.mark.parametrize("text", [
    "В Оренбургской области закрыто движение по дороге Р-239 на 12 км.",
    "В Оренбургской области открыто движение по дороге Р-239 на 12 км.",
    "В Оренбуржье объявлена опасность атаки БПЛА.",
    "В Оренбуржье отбой опасности атаки БПЛА.",
    "В Оренбургской области объявлена ракетная опасность.",
    "В Оренбургской области отбой ракетной опасности.",
    "В Оренбургской области объявлена воздушная опасность.",
    "В Оренбургской области отбой воздушной опасности.",
    "В Оренбурге введен режим Ковер.",
    "В Оренбурге отменен режим Ковер.",
    "В Оренбургской области восстановлено движение по трассе.",
])
def test_allowed_synthetic_notice_shapes(text):
    assert classify(post(text)) == text


@pytest.mark.parametrize("text", [
    "В Оренбуржье ожидается снег и ветер.",
    "Пожар в Оренбурге ликвидирован.",
    "Поздравляем жителей Оренбуржья с праздником!",
    "В Самаре объявлена опасность атаки БПЛА.",
    "В Оренбурге БПЛА летит по траектории к координатам 1, 2.",
    "В Оренбурге расположена воинская часть, закрыта дорога.",
    "В Оренбуржье проходят учебные мероприятия: объявлена опасность атаки БПЛА.",
])
def test_rejected_synthetic_notice_shapes(text):
    assert classify(post(text)) is None


@pytest.mark.parametrize(("text", "expected"), [
    ("В Оренбуржье закрыта дорога.", "road_restricted"),
    ("В Оренбуржье открыта дорога.", "road_reopened"),
    ("В Оренбуржье объявлена опасность атаки БПЛА.", "threat_announced"),
    ("В Оренбуржье отбой опасности атаки БПЛА.", "threat_cleared"),
    ("В Оренбуржье введен режим Ковер.", "kover_introduced"),
    ("В Оренбуржье отменен режим Ковер.", "kover_lifted"),
])
def test_event_transition(text, expected):
    assert event_transition(post(text)) == expected


@pytest.mark.parametrize("changes", [
    {"channel_url": "https://max.ru/other"},
    {"post_url": "https://max.ru/other/test-post-1"},
    {"post_url": "https://max.ru/id5610084427_gos/"},
    {"post_url": "https://max.ru/id5610084427_gos/test-post-1?redirect=1"},
    {"post_url": "https://max.ru/id5610084427_gos/another-post"},
    {"post_id": ""},
])
def test_source_boundary(changes):
    assert classify(post("В Оренбуржье объявлена опасность атаки БПЛА.", **changes)) is None


def test_rewrite_preserves_numbers_status_and_vocabulary():
    original = "В Оренбургской области закрыта дорога Р-239 на 12 км с 10:30."
    assert validate_rewrite(original, original) == original
    for candidate in (
        "В Оренбургской области открыта дорога Р-239 на 12 км с 10:30.",
        "В Оренбургской области закрыта дорога Р-239 на 13 км с 10:30.",
        "В Оренбургской области закрыта дорога Р-239 на 12 км с 10:30, есть пострадавшие.",
    ):
        with pytest.raises(ValueError):
            validate_rewrite(original, candidate)


def test_store_restarts_stale_edits_and_destination(tmp_path):
    path = str(tmp_path / "emergency.db")
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    first = open_store(path)
    assert register_post(first, source, NOW)
    first.close()
    second = open_store(path)
    assert register_post(second, source, NOW)
    with pytest.raises(ValueError):
        claim_delivery(second, source, "max", NOW)
    assert claim_delivery(second, source, TARGET_CHANNEL, NOW)
    assert claim_delivery(second, source, TARGET_CHANNEL, NOW) is None
    assert not register_post(second, source, NOW)
    assert not register_post(second, post("В Оренбуржье отбой опасности атаки БПЛА."), NOW)
    assert second.execute("SELECT status FROM posts").fetchone()[0] == "review_edit"
    record_removal(second, source.post_id)
    assert second.execute("SELECT status FROM posts").fetchone()[0] == "review_removed"
    assert not register_post(second, post(source.text, post_id="old", published_at=NOW - timedelta(hours=1)), NOW)
    assert second.execute("SELECT DISTINCT destination FROM deliveries").fetchall() == [(TARGET_CHANNEL,)]
    second.close()


def test_claim_rechecks_freshness(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    assert register_post(connection, source, NOW)
    assert claim_delivery(connection, source, TARGET_CHANNEL, NOW + timedelta(minutes=20)) is None
    assert connection.execute("SELECT status FROM posts").fetchone()[0] == "stale"
    connection.close()


def test_restart_marks_unsent_old_post_stale(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    assert register_post(connection, source, NOW)
    assert not register_post(connection, source, NOW + timedelta(minutes=20))
    assert connection.execute("SELECT status FROM posts").fetchone()[0] == "stale"
    connection.close()


class FakeRewriter:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error

    async def rewrite(self, source):
        if self.error:
            raise self.error
        return self.output or source.text


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, destination, text):
        self.sent.append((destination, text))
        return "123"


def test_pipeline_dedup_rewrite_failure_and_original(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    sender = FakeSender()
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    pipeline = EmergencyPipeline(connection, FakeRewriter(error=RuntimeError("Gemini unavailable")), sender)
    assert asyncio.run(pipeline.process(source, NOW))
    assert not asyncio.run(pipeline.process(source, NOW))
    assert sender.sent[0][0] == TARGET_CHANNEL
    assert "Оригинал: " + source.text in sender.sent[0][1]
    assert source.post_url in sender.sent[0][1]
    assert connection.execute("SELECT status, remote_id, sent_at FROM deliveries").fetchone()[0:2] == ("sent", "123")
    connection.close()


def test_telegram_sender_enforces_target_without_network(monkeypatch):
    class BotStub:
        def __init__(self, token):
            self.token = token

        async def get_me(self):
            return SimpleNamespace(id=7)

        async def get_chat(self, destination):
            assert destination == TARGET_CHANNEL
            return SimpleNamespace(id=-9, username="benzinoren")

        async def get_chat_member(self, chat_id, user_id):
            assert (chat_id, user_id) == (-9, 7)
            return SimpleNamespace(status="administrator", can_post_messages=True)

        async def send_message(self, destination, text, **kwargs):
            assert destination == TARGET_CHANNEL
            return SimpleNamespace(message_id=9)

    monkeypatch.setenv("BOT_TOKEN", "fuel-token")
    with pytest.raises(ValueError):
        EmergencyTelegramSender("fuel-token", bot_factory=BotStub)
    with pytest.raises(ValueError):
        EmergencyTelegramSender("token", "@other", bot_factory=BotStub)
    sender = EmergencyTelegramSender("separate-token", bot_factory=BotStub)
    with pytest.raises(ValueError):
        asyncio.run(sender.send("@other", "text"))
    assert asyncio.run(sender.send(TARGET_CHANNEL, "text")) == "9"


def test_telegram_preflight_rejects_wrong_chat():
    class BotStub:
        def __init__(self, token):
            pass

        async def get_me(self):
            return SimpleNamespace(id=7)

        async def get_chat(self, destination):
            return SimpleNamespace(id=-9, username="other")

        async def send_message(self, *args, **kwargs):
            raise AssertionError("send must not be reached")

    sender = EmergencyTelegramSender("separate-token", bot_factory=BotStub)
    with pytest.raises(ValueError, match="identity mismatch"):
        asyncio.run(sender.send(TARGET_CHANNEL, "text"))


def test_max_adapter_accepts_only_verified_chat():
    message = SimpleNamespace(id=123, chat_id=-42, time=int(NOW.timestamp() * 1000), text="В Оренбуржье объявлена опасность атаки БПЛА.")
    source = from_verified_message(message, -42, f"{SOURCE_CHANNEL}/123")
    assert source.channel_url == SOURCE_CHANNEL
    assert source.published_at == NOW
    with pytest.raises(ValueError):
        from_verified_message(message, -41, f"{SOURCE_CHANNEL}/123")
    with pytest.raises(ValueError, match="unverified MAX post link"):
        from_verified_message(message, -42, f"{SOURCE_CHANNEL}/999")


def test_prepared_reader_requests_only_verified_channel():
    class ClientStub:
        async def fetch_history(self, **kwargs):
            assert kwargs == {"chat_id": -42, "backward": 20, "get_chat": False, "interactive": False}
            return [SimpleNamespace(id=123, chat_id=-42, time=int(NOW.timestamp() * 1000), text="В Оренбуржье объявлена опасность атаки БПЛА.")]

    reader = PreparedMaxReader(ClientStub(), -42, lambda post_id: f"{SOURCE_CHANNEL}/{post_id}")
    result = asyncio.run(reader.fetch_recent())
    assert len(result) == 1 and result[0].post_id == "123"


def test_gemini_rewrite_uses_strict_validation():
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")

    class ModelsStub:
        async def generate_content(self, **kwargs):
            assert kwargs["contents"] == source.text
            return SimpleNamespace(parsed={"text": "В Оренбуржье объявлена опасность атаки БПЛА."})

    rewriter = GeminiRewriter("unused", "unused")
    rewriter.client = SimpleNamespace(aio=SimpleNamespace(models=ModelsStub()))
    assert asyncio.run(rewriter.rewrite(source)) == source.text


def test_worker_recovers_after_read_error(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    sender = FakeSender()
    stop = asyncio.Event()

    class ReaderStub:
        calls = 0

        async def fetch_recent(self, count=20):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary error")
            stop.set()
            return [post("В Оренбуржье объявлена опасность атаки БПЛА.", published_at=datetime.now(UTC))]

    reader = ReaderStub()
    pipeline = EmergencyPipeline(connection, FakeRewriter(), sender)
    asyncio.run(run_forever(reader, pipeline, stop, interval_seconds=0.001))
    assert reader.calls == 2
    assert len(sender.sent) == 1
    connection.close()


def test_unknown_send_result_is_not_retried(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")

    class UncertainSender:
        calls = 0

        async def send(self, destination, text):
            self.calls += 1
            raise TimeoutError("unknown Telegram result")

    sender = UncertainSender()
    pipeline = EmergencyPipeline(connection, FakeRewriter(), sender)
    assert not asyncio.run(pipeline.process(source, NOW))
    assert not asyncio.run(pipeline.process(source, NOW))
    assert sender.calls == 1
    assert connection.execute("SELECT status FROM deliveries").fetchone()[0] == "claimed"
    connection.close()
