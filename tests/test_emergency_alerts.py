import asyncio
import base64
import os
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.enums import ParseMode

from app.emergency_alerts.core import (
    SOURCE_CHANNEL,
    SOURCE_CHAT_ID,
    TARGET_CHANNEL,
    SourcePost,
    claim_delivery,
    classify,
    event_transition,
    initialize_without_backfill,
    open_store,
    record_removal,
    record_baseline_observations,
    register_post,
    render,
)
from app.emergency_alerts import __main__ as emergency_cli
from app.emergency_alerts.max_source import AuthorizedMaxSession, PreparedMaxReader, from_verified_message
from app.emergency_alerts.pipeline import EmergencyPipeline
from app.emergency_alerts.rewrite import GeminiRewriter, validate_rewrite
from app.emergency_alerts.telegram import EmergencyTelegramSender
from app.emergency_alerts.worker import run_forever


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def post(text: str, **changes) -> SourcePost:
    data = dict(
        post_id="test-post-1",
        channel_url=SOURCE_CHANNEL,
        post_url=SOURCE_CHANNEL,
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
    "В Оренбургской области объявлена авиационная опасность.",
    "В Оренбургской области временно прекращено движение по дороге.",
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
    "В Оренбуржье возможно закрытие дороги из-за погоды.",
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


@pytest.mark.parametrize(("text", "expected"), [
    (
        "ОТБОЙ ОПАСНОСТИ АТАКИ БЕСПИЛОТНЫХ ЛЕТАТЕЛЬНЫХ АППАРАТОВ "
        "в Оренбургской области 24.10.2026 12:40. Тел. спасения 112.",
        "threat_cleared",
    ),
    (
        "ОТМЕНА прекращения движения для всех типов ТС на участке дороги "
        "Загородное шоссе в Оренбургской области.",
        "road_reopened",
    ),
])
def test_live_verified_notice_shapes(text, expected):
    assert classify(post(text)) == text
    assert event_transition(post(text)) == expected


@pytest.mark.parametrize("changes", [
    {"channel_url": "https://max.ru/other"},
    {"post_url": "https://max.ru/other"},
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
        "Дорога Р-239 закрыта в Оренбургской области на 12 км с 10:30.",
    ):
        with pytest.raises(ValueError):
            validate_rewrite(original, candidate)


@pytest.mark.parametrize(("text", "headline"), [
    (
        "В Оренбуржье объявлена опасность атаки БПЛА.",
        "Опасность атаки БПЛА объявлена в Оренбуржье",
    ),
    (
        "В Оренбургской области отбой опасности атаки БПЛА.",
        "Отбой опасности атаки БПЛА в Оренбургской области",
    ),
])
def test_render_uses_short_factual_html_alerts(text, headline):
    message = render(post(text), text)
    assert message == f"❗️ <b>{headline}</b>\n\n{text}"
    assert "Источник:" not in message
    assert "ID публикации" not in message
    assert SOURCE_CHANNEL not in message


def test_render_keeps_road_facts_in_order_and_removes_metadata():
    text = (
        "На Загородном шоссе (км 0+000 — км 0+200) закрыли проезд для всех видов транспорта. "
        "Также перекрыли участок дороги Сырт — Родничный Дол (км 0+000 — км 9+760). "
        "Временно нет проезда на подъезде к Оренбургу от автодороги М-5 «Урал» (км 0+000 — км 2+270).\n\n"
        "Источник: https://max.ru/id5610084427_gos\nID публикации MAX: 123\n#МЧС"
    )
    message = render(post(text), text)
    assert message.startswith("❗️ <b>Ограничение движения на дорогах в Оренбургской области</b>\n\n")
    assert "км 0+000 — км 0+200" in message
    assert "Сырт — Родничный Дол (км 0+000 — км 9+760)" in message
    assert "М-5 «Урал» (км 0+000 — км 2+270)" in message
    assert message.count("\n\n") == 3
    assert "Источник:" not in message
    assert "https://max.ru" not in message
    assert "ID публикации" not in message
    assert "#МЧС" not in message


def test_store_restarts_stale_edits_and_destination(tmp_path):
    path = str(tmp_path / "emergency.db")
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    first = open_store(path)
    assert os.stat(path).st_mode & 0o077 == 0
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


def test_store_refuses_ephemeral_or_shared_files(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        open_store(":memory:")
    with pytest.raises(ValueError, match="absolute"):
        open_store("relative.db")
    shared_path = tmp_path / "shared.db"
    shared_path.touch(mode=0o644)
    shared_path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        open_store(str(shared_path))
    link_path = tmp_path / "link.db"
    link_path.symlink_to(shared_path)
    with pytest.raises(ValueError, match="private"):
        open_store(str(link_path))


def test_claim_rechecks_freshness(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    assert register_post(connection, source, NOW)
    assert claim_delivery(connection, source, TARGET_CHANNEL, NOW + timedelta(minutes=20)) is None
    assert connection.execute("SELECT status FROM posts").fetchone()[0] == "stale"
    connection.close()


def test_initial_baseline_never_creates_deliveries(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    assert initialize_without_backfill(connection, [source], NOW) == 1
    assert initialize_without_backfill(connection, [source], NOW) == 0
    assert connection.execute("SELECT status FROM posts").fetchone() == ("baseline",)
    assert connection.execute("SELECT COUNT(*) FROM deliveries").fetchone() == (0,)
    assert not register_post(connection, source, NOW)
    connection.close()


def test_disabled_github_poll_advances_baseline_without_delivery(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    first = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    second = post("В Оренбуржье закрыта дорога.", post_id="test-post-2")
    assert initialize_without_backfill(connection, [first], NOW) == 1
    assert record_baseline_observations(connection, [first, second], NOW) == 1
    assert connection.execute("SELECT COUNT(*) FROM posts WHERE status='baseline'").fetchone() == (2,)
    assert connection.execute("SELECT COUNT(*) FROM deliveries").fetchone() == (0,)
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

    async def verify_destination(self):
        pass

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
    assert sender.sent[0][1] == "❗️ <b>Опасность атаки БПЛА объявлена в Оренбуржье</b>\n\nВ Оренбуржье объявлена опасность атаки БПЛА."
    assert "Источник:" not in sender.sent[0][1]
    assert source.post_url not in sender.sent[0][1]
    assert connection.execute("SELECT status, remote_id, sent_at FROM deliveries").fetchone()[0:2] == ("sent", "123")
    connection.close()


def test_pipeline_checkpoints_claim_before_send_and_confirmation_after(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")
    events = []

    class OrderedSender(FakeSender):
        async def send(self, destination, text):
            events.append("send")
            return "123"

    async def checkpoint():
        status = connection.execute("SELECT status FROM deliveries").fetchone()[0]
        events.append(f"checkpoint:{status}")

    pipeline = EmergencyPipeline(connection, FakeRewriter(), OrderedSender(), checkpoint)
    assert asyncio.run(pipeline.process(source, NOW))
    assert events == ["checkpoint:claimed", "send", "checkpoint:sent"]
    connection.close()


def test_encrypted_github_state_round_trip_and_tamper_detection(tmp_path, monkeypatch):
    from app.emergency_alerts.github_state import decrypt_state, encrypt_state

    monkeypatch.setenv("EMERGENCY_STATE_KEY_B64", base64.b64encode(b"k" * 32).decode())
    source = tmp_path / "source.sqlite3"
    connection = open_store(str(source))
    initialize_without_backfill(connection, [post("В Оренбуржье объявлена опасность атаки БПЛА.")], NOW)
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    connection.close()
    encrypted = tmp_path / "state.aesgcm"
    restored = tmp_path / "restored.sqlite3"
    encrypt_state(str(source), str(encrypted))
    assert b"test-post-1" not in encrypted.read_bytes()
    decrypt_state(str(encrypted), str(restored))
    restored_connection = open_store(str(restored))
    assert restored_connection.execute("SELECT status FROM posts").fetchone() == ("baseline",)
    restored_connection.close()
    payload = bytearray(encrypted.read_bytes())
    payload[-1] ^= 1
    encrypted.write_bytes(payload)
    with pytest.raises(Exception):
        decrypt_state(str(encrypted), str(restored))


def test_github_state_checkpoint_uses_lease_and_keeps_single_encrypted_commit(tmp_path, monkeypatch):
    from app.emergency_alerts.github_state import GitHubStateCheckpoint, STATE_FILE, decrypt_state

    monkeypatch.setenv("EMERGENCY_STATE_KEY_B64", base64.b64encode(b"s" * 32).decode())
    remote = tmp_path / "remote.git"
    repository = tmp_path / "state-repository"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(repository), "checkout", "--orphan", "emergency-runtime-state"], check=True, capture_output=True)
    source = tmp_path / "source.sqlite3"
    connection = open_store(str(source))
    initialize_without_backfill(connection, [post("В Оренбуржье объявлена опасность атаки БПЛА.")], NOW)
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    checkpoint = GitHubStateCheckpoint(str(repository), str(source))
    checkpoint.save()
    connection.execute("INSERT OR REPLACE INTO service_state VALUES ('test', 'second')")
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    checkpoint.save()
    connection.close()
    count = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-list", "--count", "emergency-runtime-state"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert count.stdout.strip() == "1"
    encrypted = subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"emergency-runtime-state:{STATE_FILE}"],
        check=True,
        capture_output=True,
    ).stdout
    encrypted_path = tmp_path / STATE_FILE
    encrypted_path.write_bytes(encrypted)
    restored = tmp_path / "restored.sqlite3"
    decrypt_state(str(encrypted_path), str(restored))
    restored_connection = open_store(str(restored))
    assert restored_connection.execute("SELECT value FROM service_state WHERE key='test'").fetchone() == ("second",)
    restored_connection.close()


def test_telegram_sender_enforces_target_without_network(monkeypatch):
    sent_options = []

    class BotStub:
        def __init__(self, token):
            self.token = token

        async def get_me(self):
            return SimpleNamespace(id=7)

        async def get_chat(self, destination):
            assert destination == TARGET_CHANNEL
            return SimpleNamespace(id=-9, username="benzinoren", type="channel")

        async def get_chat_member(self, chat_id, user_id):
            assert (chat_id, user_id) == (-9, 7)
            return SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR, can_post_messages=True)

        async def send_message(self, destination, text, **kwargs):
            assert destination == -9
            sent_options.append(kwargs)
            return SimpleNamespace(message_id=9)

    monkeypatch.setenv("BOT_TOKEN", "fuel-token")
    with pytest.raises(ValueError):
        EmergencyTelegramSender("token", "@other", bot_factory=BotStub)
    sender = EmergencyTelegramSender("fuel-token", bot_factory=BotStub)
    with pytest.raises(ValueError):
        asyncio.run(sender.send("@other", "text"))
    assert asyncio.run(sender.send(TARGET_CHANNEL, "text")) == "9"
    assert sent_options == [{"parse_mode": ParseMode.HTML, "disable_web_page_preview": True}]


def test_telegram_preflight_rejects_wrong_chat():
    class BotStub:
        def __init__(self, token):
            pass

        async def get_me(self):
            return SimpleNamespace(id=7)

        async def get_chat(self, destination):
            return SimpleNamespace(id=-9, username="other", type="channel")

        async def send_message(self, *args, **kwargs):
            raise AssertionError("send must not be reached")

    sender = EmergencyTelegramSender("separate-token", bot_factory=BotStub)
    with pytest.raises(ValueError, match="identity mismatch"):
        asyncio.run(sender.send(TARGET_CHANNEL, "text"))


def test_cli_preflight_never_sends(monkeypatch):
    from app.emergency_alerts import telegram

    actions = []

    class SenderStub:
        def __init__(self, token):
            assert token == "shared-test-token"

        async def verify_destination(self):
            actions.append("verified")

        async def close(self):
            actions.append("closed")

    monkeypatch.setenv("BOT_TOKEN", "shared-test-token")
    monkeypatch.setattr(telegram, "EmergencyTelegramSender", SenderStub)
    asyncio.run(emergency_cli.telegram_preflight())
    assert actions == ["verified", "closed"]


def test_preflight_workflow_is_manual_and_uses_existing_secret():
    from pathlib import Path

    workflow = Path(".github/workflows/emergency-telegram-preflight.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "secrets.BOT_TOKEN" in workflow
    assert "python -m app.emergency_alerts telegram-preflight" in workflow
    assert "send_message" not in workflow


def test_max_adapter_accepts_only_verified_chat():
    message = SimpleNamespace(id=123, chat_id=SOURCE_CHAT_ID, time=int(NOW.timestamp() * 1000), text="В Оренбуржье объявлена опасность атаки БПЛА.")
    source = from_verified_message(message, SOURCE_CHAT_ID)
    assert source.channel_url == SOURCE_CHANNEL
    assert source.post_url == SOURCE_CHANNEL
    assert source.published_at == NOW
    with pytest.raises(ValueError):
        from_verified_message(message, SOURCE_CHAT_ID + 1)


def test_prepared_reader_requests_only_verified_channel():
    class ClientStub:
        async def fetch_history(self, **kwargs):
            assert kwargs == {"chat_id": SOURCE_CHAT_ID, "backward": 20, "get_chat": False, "interactive": False}
            return [SimpleNamespace(id=123, chat_id=SOURCE_CHAT_ID, time=int(NOW.timestamp() * 1000), text="В Оренбуржье объявлена опасность атаки БПЛА.")]

    reader = PreparedMaxReader(ClientStub(), SOURCE_CHAT_ID)
    result = asyncio.run(reader.fetch_recent())
    assert len(result) == 1 and result[0].post_id == "123"


def test_authorized_max_session_checks_permission_and_channel(tmp_path):
    session_path = tmp_path / "max.db"
    session_path.touch()
    session_path.chmod(0o600)
    calls = []

    class ClientStub:
        is_connected = True

        async def connect(self):
            calls.append("connect")

        async def get_chat(self, chat_id):
            assert chat_id == SOURCE_CHAT_ID
            calls.append("get_chat")
            return SimpleNamespace(type="CHANNEL", link=SOURCE_CHANNEL)

        async def fetch_history(self, **kwargs):
            assert kwargs["chat_id"] == SOURCE_CHAT_ID
            calls.append("fetch_history")
            return [SimpleNamespace(id=123, chat_id=SOURCE_CHAT_ID, time=int(NOW.timestamp() * 1000), text="В Оренбуржье объявлена опасность атаки БПЛА.")]

        async def close(self):
            calls.append("close")

    def factory(**kwargs):
        assert kwargs["session_name"] == "max.db"
        return ClientStub()

    with pytest.raises(PermissionError):
        AuthorizedMaxSession(str(session_path), SOURCE_CHAT_ID, False, factory)
    assert calls == []

    async def read():
        async with AuthorizedMaxSession(str(session_path), SOURCE_CHAT_ID, True, factory) as reader:
            return await reader.fetch_recent()

    assert asyncio.run(read())[0].post_id == "123"
    assert calls == ["connect", "get_chat", "fetch_history", "close"]


def test_authorized_max_session_rejects_other_channel(tmp_path):
    session_path = tmp_path / "max.db"
    session_path.touch()
    session_path.chmod(0o600)
    calls = []

    class ClientStub:
        is_connected = True

        async def connect(self):
            calls.append("connect")

        async def get_chat(self, chat_id):
            return SimpleNamespace(type="CHAT", link=SOURCE_CHANNEL)

        async def fetch_history(self, **kwargs):
            raise AssertionError("history must not be read")

        async def close(self):
            calls.append("close")

    async def read():
        async with AuthorizedMaxSession(str(session_path), SOURCE_CHAT_ID, True, lambda **kwargs: ClientStub()):
            pass

    with pytest.raises(ValueError, match="identity"):
        asyncio.run(read())
    assert calls == ["connect", "close"]


def test_authorized_max_session_requires_pinned_id_and_private_file(tmp_path):
    session_path = tmp_path / "max.db"
    session_path.touch(mode=0o644)
    session_path.chmod(0o644)
    with pytest.raises(ValueError, match="pinned source"):
        AuthorizedMaxSession(str(session_path), SOURCE_CHAT_ID + 1, True)
    with pytest.raises(ValueError, match="other users"):
        AuthorizedMaxSession(str(session_path), SOURCE_CHAT_ID, True)
    session_path.chmod(0o600)
    link_path = tmp_path / "max-link.db"
    link_path.symlink_to(session_path)
    with pytest.raises(ValueError, match="symlink"):
        AuthorizedMaxSession(str(link_path), SOURCE_CHAT_ID, True)


def test_max_dry_run_requires_platform_permission(monkeypatch):
    monkeypatch.delenv("EMERGENCY_MAX_PERMISSION_CONFIRMED", raising=False)
    with pytest.raises(PermissionError, match="permission"):
        asyncio.run(emergency_cli.max_dry_run())


def test_max_dry_run_workflow_is_manual_read_only_and_serialized():
    from pathlib import Path

    workflow = Path(".github/workflows/emergency-max-dry-run.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "group: fuel-monitor-production" in workflow
    assert "secrets.MAX_SESSION_GZ_B64" in workflow
    assert "BOT_TOKEN" not in workflow
    assert "max-dry-run" in workflow
    assert "send_message" not in workflow


def test_github_poller_is_run_once_encrypted_and_separate_from_fuel_workflow():
    from pathlib import Path

    workflow = Path(".github/workflows/emergency-github.yml").read_text()
    fuel_workflow = Path(".github/workflows/main.yml").read_text()
    assert 'cron: "2/5 * * * *"' in workflow
    assert "timeout-minutes: 4" in workflow
    assert "group: emergency-mchs-github-poller" in workflow
    assert "secrets.EMERGENCY_STATE_KEY_B64" in workflow
    assert 'EMERGENCY_GITHUB_PUBLISH_ENABLED: "false"' in workflow
    assert "emergency-runtime-state" in workflow
    assert 'workflows: ["Fuel monitor"]' in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert "upload-artifact" not in workflow
    assert "run-once" in workflow
    assert "app.runner" not in workflow
    assert "emergency-github" not in fuel_workflow


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
    metrics = dict(connection.execute("SELECT key, value FROM service_state").fetchall())
    assert metrics["last_poll_post_count"] == "1"
    assert metrics["consecutive_poll_failures"] == "0"
    assert metrics["last_poll_error_type"] == ""
    assert int(metrics["last_poll_duration_ms"]) >= 0
    connection.close()


def test_worker_requests_fresh_session_after_closed_connection(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    stop = asyncio.Event()

    class ReaderStub:
        client = SimpleNamespace(is_connected=False)

        async def fetch_recent(self, count=20):
            raise ConnectionError("connection closed")

    pipeline = EmergencyPipeline(connection, FakeRewriter(), FakeSender())

    assert asyncio.run(run_forever(ReaderStub(), pipeline, stop, interval_seconds=0.001)) is True
    assert connection.execute("SELECT status FROM worker_health").fetchone() == ("error",)
    metrics = dict(connection.execute("SELECT key, value FROM service_state").fetchall())
    assert metrics["last_poll_error_type"] == "ConnectionError"
    connection.close()


def test_unknown_send_result_is_not_retried(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")

    class UncertainSender:
        calls = 0

        async def verify_destination(self):
            pass

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


def test_telegram_preflight_failure_keeps_delivery_retryable(tmp_path):
    connection = open_store(str(tmp_path / "state.db"))
    source = post("В Оренбуржье объявлена опасность атаки БПЛА.")

    class PreflightSender(FakeSender):
        checks = 0

        async def verify_destination(self):
            self.checks += 1
            if self.checks == 1:
                raise ConnectionError("temporary Telegram outage")

    sender = PreflightSender()
    pipeline = EmergencyPipeline(connection, FakeRewriter(), sender)
    assert not asyncio.run(pipeline.process(source, NOW))
    assert connection.execute("SELECT status FROM deliveries").fetchone()[0] == "pending"
    assert asyncio.run(pipeline.process(source, NOW))
    assert len(sender.sent) == 1
    connection.close()
