"""Local-only MAX account setup and chat-access probe.

This script never sends messages. Its session and phone metadata stay under
``.local/max`` and are excluded from Git.
"""

import argparse
import asyncio
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from pymax import Client, ConsoleQrHandler, ExtraConfig, QrAuthFlow, WebClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_WORK_DIR = PROJECT_ROOT / ".local" / "max"
SESSION_NAME = "max_session.db"
WEB_SESSION_NAME = "max_web_session.db"
START_TIMEOUT_SECONDS = 30
PHONE_FILE = MAX_WORK_DIR / "phone.txt"
PUBLIC_CHANNEL_USERNAME = "channel_agzs_orenburg"
PUBLIC_CHANNEL_TITLE = "агзс оренбург сейчас"


def session_path() -> Path:
    return MAX_WORK_DIR / SESSION_NAME


def normalize_russian_phone(value: str) -> str:
    compact = re.sub(r"[\s()-]", "", value)
    if compact.startswith("8"):
        compact = "+7" + compact[1:]
    elif compact.startswith("7"):
        compact = "+" + compact
    if not re.fullmatch(r"\+7\d{10}", compact):
        raise ValueError("Enter a Russian phone number as 8XXXXXXXXXX, 7XXXXXXXXXX, or +7XXXXXXXXXX")
    return compact


def mask_phone(phone: str) -> str:
    return f"{phone[:2]}*******{phone[-2:]}"


def _read_or_prompt_phone() -> str:
    if PHONE_FILE.exists():
        saved_phone = PHONE_FILE.read_text(encoding="utf-8").strip()
        if saved_phone:
            try:
                return normalize_russian_phone(saved_phone)
            except ValueError:
                PHONE_FILE.unlink()
    phone = normalize_russian_phone(input("MAX phone number: ").strip())
    MAX_WORK_DIR.mkdir(parents=True, exist_ok=True)
    MAX_WORK_DIR.chmod(0o700)
    PHONE_FILE.write_text(phone + "\n", encoding="utf-8")
    PHONE_FILE.chmod(0o600)
    return phone


def chat_id(chat: object) -> int:
    return int(getattr(chat, "id"))


def chat_title(chat: object) -> str:
    return str(getattr(chat, "title") or "(без названия)")


def is_public_source(chat: object) -> bool:
    title = chat_title(chat).casefold()
    link = str(getattr(chat, "link", "") or "").casefold()
    return PUBLIC_CHANNEL_TITLE in title or PUBLIC_CHANNEL_USERNAME in link


def selected_probe_ids(chats: list[object], requested_ids: list[int]) -> list[int]:
    if requested_ids:
        return list(dict.fromkeys(requested_ids))
    return [chat_id(chat) for chat in chats if is_public_source(chat)]


def newest_timestamp(messages: list[object]) -> str:
    timestamps = [getattr(message, "time", None) for message in messages]
    values = [int(value) for value in timestamps if isinstance(value, int)]
    if not values:
        return "unknown"
    newest = max(values)
    if newest > 10_000_000_000:
        newest //= 1000
    return datetime.fromtimestamp(newest, UTC).isoformat()


class ExistingWebSessionOnly:
    async def authenticate(self, _app) -> None:
        raise RuntimeError("saved MAX WebClient session is invalid or expired")


async def probe_history(client: Client | WebClient, chats: list[object], requested_ids: list[int]) -> None:
    by_id = {chat_id(chat): chat for chat in chats}
    for requested_id in selected_probe_ids(chats, requested_ids):
        chat = by_id.get(requested_id)
        title = chat_title(chat) if chat is not None else "(не найден среди fetch_chats)"
        try:
            print(f"[MAX] fetching history {requested_id}")
            messages = await client.fetch_history(chat_id=requested_id, backward=5)
        except Exception as exc:
            print(f"{requested_id} | {title} | history unavailable: {type(exc).__name__}")
            continue
        print(
            f"{requested_id} | {title} | messages={len(messages)} "
            f"| newest={newest_timestamp(messages)}"
        )


async def start_and_inspect(client: Client | WebClient, probe: bool, requested_ids: list[int]) -> None:
    started = False
    closed = False

    @client.on_start()
    async def after_login(started_client: Client | WebClient) -> None:
        nonlocal closed, started
        started = True
        try:
            print("[MAX] client started")
            print("[MAX] fetching chats")
            chats = await started_client.fetch_chats()
            if probe:
                await probe_history(started_client, chats, requested_ids)
            else:
                for chat in chats:
                    marker = " [public target]" if is_public_source(chat) else ""
                    print(f"{chat_id(chat)} | {chat_title(chat)}{marker}")
        finally:
            print("[MAX] closing client")
            await started_client.close()
            closed = True

    try:
        print("[MAX] starting client")
        await asyncio.wait_for(client.start(), timeout=START_TIMEOUT_SECONDS)
        if not started:
            raise RuntimeError("saved MAX WebClient session is invalid or unavailable")
    except TimeoutError as exc:
        raise RuntimeError("MAX client start timed out; saved session or network is unavailable") from exc
    finally:
        if not closed:
            print("[MAX] closing client")
            await client.close()


async def run_sms(probe: bool, requested_ids: list[int]) -> None:
    MAX_WORK_DIR.mkdir(parents=True, exist_ok=True)
    MAX_WORK_DIR.chmod(0o700)
    phone = _read_or_prompt_phone()
    print(f"Using MAX phone {mask_phone(phone)}")
    client = Client(
        phone=phone,
        work_dir=str(MAX_WORK_DIR),
        session_name=SESSION_NAME,
        extra_config=ExtraConfig(log_level="WARNING", reconnect=False, telemetry=False),
    )
    await start_and_inspect(client, probe, requested_ids)


async def run_qr(probe: bool, requested_ids: list[int]) -> None:
    MAX_WORK_DIR.mkdir(parents=True, exist_ok=True)
    MAX_WORK_DIR.chmod(0o700)
    session = MAX_WORK_DIR / WEB_SESSION_NAME
    if probe and not session.is_file():
        raise RuntimeError("saved MAX WebClient session is unavailable; run --qr first")
    auth_flow = ExistingWebSessionOnly() if probe else QrAuthFlow(ConsoleQrHandler())
    print("[MAX] opening saved session" if probe else "[MAX] opening QR authorization")
    client = WebClient(
        work_dir=str(MAX_WORK_DIR),
        session_name=WEB_SESSION_NAME,
        auth_flow=auth_flow,
        extra_config=ExtraConfig(log_level="WARNING", reconnect=False, telemetry=False),
    )
    await start_and_inspect(client, probe, requested_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorize a local MAX session and inspect accessible chats.")
    parser.add_argument("--qr", action="store_true", help="Authorize with an ASCII QR code in this terminal.")
    parser.add_argument("--probe", action="store_true", help="Fetch a few messages without printing their text.")
    parser.add_argument(
        "--chat-id",
        action="append",
        type=int,
        default=[],
        help="Chat ID to probe; repeat for multiple chats. Defaults to the public target if found.",
    )
    return parser.parse_args()


def use_web_client(args: argparse.Namespace) -> bool:
    return args.qr or args.probe


def main() -> None:
    args = parse_args()
    runner = run_qr if use_web_client(args) else run_sms
    asyncio.run(runner(args.probe, args.chat_id))


if __name__ == "__main__":
    main()
