import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.emergency_alerts.core import SOURCE_CHANNEL, open_store
from app.emergency_alerts.max_source import PreparedMaxReader
from app.emergency_alerts.service import check_health, serve


@pytest.mark.parametrize("missing", ["EMERGENCY_ENABLED", "EMERGENCY_MAX_PERMISSION_CONFIRMED", "EMERGENCY_SOURCE_VERIFIED"])
def test_service_gates_precede_all_io(monkeypatch, missing):
    for name in ("EMERGENCY_ENABLED", "EMERGENCY_MAX_PERMISSION_CONFIRMED", "EMERGENCY_SOURCE_VERIFIED"):
        monkeypatch.setenv(name, "true")
    monkeypatch.delenv(missing)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        asyncio.run(serve())


def test_cli_preflight_imports_without_max_or_gemini():
    result = subprocess.run([sys.executable, "-c", "import sys; sys.modules['pymax'] = None; sys.modules['google'] = None; import app.emergency_alerts.__main__"], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_history_missing_chat_id_and_overlapping_pages():
    now = int(datetime.now(UTC).timestamp() * 1000)
    calls = []

    def message(identifier, timestamp, chat_id=None):
        return SimpleNamespace(id=identifier, time=timestamp, chat_id=chat_id, text="В Оренбуржье объявлена опасность атаки БПЛА.")

    class Client:
        async def fetch_history(self, **kwargs):
            assert kwargs["chat_id"] == -42
            calls.append(kwargs)
            if len(calls) == 1:
                return [message(3, now), message(2, now - 1000)]
            return [message(2, now - 1000), message(1, now - 1000000)]

    reader = PreparedMaxReader(Client(), -42, lambda identifier: f"{SOURCE_CHANNEL}/{identifier}")
    result = asyncio.run(reader.fetch_recent(2))
    assert {post.post_id for post in result} == {"1", "2", "3"}
    assert calls[1]["from_time"] == now - 1000


def test_history_rejects_stalled_cursor_and_wrong_chat():
    class Client:
        chat_id = None

        async def fetch_history(self, **kwargs):
            return [SimpleNamespace(id=1, time=int(datetime.now(UTC).timestamp()), chat_id=self.chat_id, text="alert")]

    client = Client()
    reader = PreparedMaxReader(client, -42, lambda identifier: f"{SOURCE_CHANNEL}/{identifier}")
    with pytest.raises(RuntimeError, match="cursor stalled"):
        asyncio.run(reader.fetch_recent(1))
    client.chat_id = -43
    with pytest.raises(ValueError, match="verified MChS"):
        asyncio.run(reader.fetch_recent(1))


def test_health_fails_for_stale_error_and_uncertain_delivery(tmp_path, monkeypatch):
    path = str(tmp_path / "health.sqlite3")
    monkeypatch.setenv("EMERGENCY_SQLITE_PATH", path)
    connection = open_store(path)
    with pytest.raises(RuntimeError):
        check_health()
    for timestamp, status in ((datetime.now(UTC) - timedelta(minutes=5), "ok"), (datetime.now(UTC), "error")):
        connection.execute("INSERT OR REPLACE INTO worker_health VALUES (1, ?, ?)", (timestamp.isoformat(), status))
        with pytest.raises(RuntimeError):
            check_health()
    connection.execute("INSERT OR REPLACE INTO worker_health VALUES (1, ?, 'ok')", (datetime.now(UTC).isoformat(),))
    check_health()
    connection.execute("INSERT INTO posts VALUES ('1', 'revision', ?, ?, 'pending')", (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()))
    connection.execute("INSERT INTO deliveries VALUES ('1', 'revision', '@benzinoren', 'claimed', NULL, NULL)")
    with pytest.raises(RuntimeError):
        check_health()
    connection.close()


def test_ineligible_edit_blocks_previously_pending_alert(tmp_path):
    from dataclasses import replace
    from app.emergency_alerts.core import SourcePost, register_post, claim_delivery, TARGET_CHANNEL

    now = datetime.now(UTC)
    post = SourcePost("123", SOURCE_CHANNEL, f"{SOURCE_CHANNEL}/123", now, "В Оренбуржье объявлена опасность атаки БПЛА.")
    connection = open_store(str(tmp_path / "edits.sqlite3"))
    assert register_post(connection, post, now)
    assert not register_post(connection, replace(post, text="Сообщение удалено автором."), now)
    assert claim_delivery(connection, post, TARGET_CHANNEL, now) is None
    assert connection.execute("SELECT status FROM posts").fetchone() == ("review_edit",)
    connection.close()


def test_max_preview_uses_isolated_pipeline_without_telegram(monkeypatch, capsys):
    from app.emergency_alerts import __main__ as cli, max_source
    from app.emergency_alerts.core import SourcePost

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def fetch_recent(self):
            now = datetime.now(UTC)
            fresh = SourcePost("123", SOURCE_CHANNEL, f"{SOURCE_CHANNEL}/123", now, "В Оренбуржье объявлена опасность атаки БПЛА.")
            old = SourcePost("124", SOURCE_CHANNEL, f"{SOURCE_CHANNEL}/124", now - timedelta(hours=1), fresh.text)
            return [fresh, fresh, old]

    def forbidden(*args, **kwargs):
        raise AssertionError("Telegram must never be constructed")

    monkeypatch.setenv("EMERGENCY_MAX_PERMISSION_CONFIRMED", "true")
    monkeypatch.setenv("EMERGENCY_MAX_CHANNEL_ID", "-42")
    monkeypatch.setenv("MAX_SESSION_PATH", "unused")
    monkeypatch.setattr(max_source, "AuthorizedMaxSession", Session)
    monkeypatch.setattr(cli, "EmergencyTelegramSender", forbidden)
    asyncio.run(cli.max_dry_run())
    assert "1 fresh previews" in capsys.readouterr().out
