import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts.max_setup import (
    START_TIMEOUT_SECONDS,
    SESSION_NAME,
    WEB_SESSION_NAME,
    is_public_source,
    mask_phone,
    newest_timestamp,
    normalize_russian_phone,
    parse_args,
    selected_probe_ids,
    start_and_inspect,
    use_web_client,
)


def chat(chat_id: int, title: str | None, link: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=chat_id, title=title, link=link)


def test_public_source_matches_title_or_link() -> None:
    assert is_public_source(chat(1, "АГЗС Оренбург Сейчас"))
    assert is_public_source(chat(2, "Другое", "https://max.ru/channel_agzs_orenburg"))
    assert not is_public_source(chat(3, "Другое"))


def test_probe_ids_prefer_explicit_selection() -> None:
    chats = [chat(1, "АГЗС Оренбург Сейчас"), chat(2, "Другой")]
    assert selected_probe_ids(chats, [2, 2, 1]) == [2, 1]
    assert selected_probe_ids(chats, []) == [1]


def test_newest_timestamp_does_not_use_message_text() -> None:
    messages = [
        SimpleNamespace(time=1_700_000_000, text="secret one"),
        SimpleNamespace(time=1_700_000_001_000, text="secret two"),
    ]
    assert newest_timestamp(messages) == datetime.fromtimestamp(1_700_000_001, UTC).isoformat()


@pytest.mark.parametrize(
    ("entered", "normalized"),
    [
        ("89228043505", "+79228043505"),
        ("79228043505", "+79228043505"),
        ("+79228043505", "+79228043505"),
    ],
)
def test_normalize_russian_phone(entered: str, normalized: str) -> None:
    assert normalize_russian_phone(entered) == normalized


def test_normalize_russian_phone_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        normalize_russian_phone("+89228043505")


def test_mask_phone_never_returns_full_phone() -> None:
    phone = "+79228043505"
    assert mask_phone(phone) == "+7*******05"
    assert phone not in mask_phone(phone)


def test_qr_session_is_separate_from_sms_session() -> None:
    assert SESSION_NAME == "max_session.db"
    assert WEB_SESSION_NAME == "max_web_session.db"


def test_qr_argument_selects_web_authorization(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["max_setup.py", "--qr"])
    assert parse_args().qr


def test_probe_selects_saved_web_session(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["max_setup.py", "--probe"])
    assert use_web_client(parse_args())


def test_start_timeout_is_finite(monkeypatch) -> None:
    class HangingClient:
        def on_start(self):
            return lambda callback: callback

        async def start(self) -> None:
            await asyncio.Event().wait()

        async def close(self) -> None:
            pass

    monkeypatch.setattr("scripts.max_setup.START_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(start_and_inspect(HangingClient(), False, []))
    assert START_TIMEOUT_SECONDS == 30


def test_certifi_bundle_is_selected_when_no_system_override_exists() -> None:
    assert os.environ.get("SSL_CERT_FILE")
