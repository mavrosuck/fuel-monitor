from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


SOURCE_CHANNEL = "https://max.ru/id5610084427_gos"
SOURCE_CHAT_ID = -69537682153611
TARGET_CHANNEL = "@benzinoren"
ORENBURG_TIME = ZoneInfo("Asia/Yekaterinburg")
MAX_AGE = timedelta(minutes=15)


@dataclass(frozen=True)
class SourcePost:
    post_id: str
    channel_url: str
    post_url: str
    published_at: datetime
    text: str


def classify(post: SourcePost) -> str | None:
    if post.channel_url != SOURCE_CHANNEL or not post.post_id or post.published_at.tzinfo is None:
        return None
    parsed = urlparse(post.post_url)
    if parsed.scheme != "https" or parsed.netloc != "max.ru" or parsed.query or parsed.fragment:
        return None
    if post.post_url != SOURCE_CHANNEL:
        return None
    body = re.sub(r"\s+", " ", post.text).strip()
    if not body or len(body) > 3500:
        return None
    lower = body.casefold().replace("ё", "е")
    if not re.search(r"оренбург|оренбурж", lower):
        return None
    if re.search(r"координат|траектори|местонахождени[ея] (?:пво|бпла)|позиц(?:ия|ии) пво|направлени[ея] полет|дислокац|воинск", lower):
        return None
    if re.search(r"учебн|тренировочн|учени[ея]|проверка системы оповещения|фейк|ложн(?:ая|ое|ый) тревог", lower):
        return None
    if re.search(r"предположительн|возможн(?:о|ая|ый)|планиру|не подтвержден|слух", lower):
        return None
    road = re.search(r"(?:перекры|закры|огранич|прекращ|возобнов|откры|восстанов|снят|отмен).{0,100}(?:дорог|трасс|движени|проезд)|(?:дорог|трасс|движени|проезд).{0,100}(?:перекры|закры|огранич|прекращ|возобнов|откры|восстанов|снят|отмен)", lower)
    threat = re.search(r"(?:беспилотн|бпла|ракетн|воздушн|авиационн).{0,60}(?:опасност|угроз|атак)|(?:опасност|угроз|атак).{0,60}(?:беспилотн|бпла|ракетн|воздушн|авиационн)", lower)
    cancellation = re.search(r"(?:отбой|отмена|отменен|отменена|снята|снят).{0,75}(?:бпла|беспилотн|ракетн|воздушн|авиационн).{0,35}(?:опасност|угроз|атак)", lower)
    kover = re.search(r"(?:режим.{0,15})?ковер", lower) and re.search(r"введ|объяв|действ|отмен|снят|отбой", lower)
    return body if road or threat or cancellation or kover else None


def event_transition(post: SourcePost) -> str | None:
    body = classify(post)
    if body is None:
        return None
    lower = body.casefold().replace("ё", "е")
    if "ковер" in lower:
        return "kover_lifted" if re.search(r"отмен|снят|отбой", lower) else "kover_introduced"
    if re.search(r"(?:бпла|беспилотн|ракетн|воздушн|авиационн).{0,60}(?:опасност|угроз|атак)|(?:опасност|угроз|атак).{0,60}(?:бпла|беспилотн|ракетн|воздушн|авиационн)", lower):
        return "threat_cleared" if re.search(r"отбой|отмен|снят", lower) else "threat_announced"
    return "road_reopened" if re.search(r"возобнов|откры|восстанов|снят|отмен", lower) else "road_restricted"


def render(post: SourcePost, rewritten: str) -> str:
    if classify(post) is None or not rewritten.strip():
        raise ValueError("post is not eligible")
    body = _editorial_body(rewritten, event_transition(post))
    if not body:
        raise ValueError("post has no publishable editorial body")
    message = f"❗️ <b>{html.escape(_headline(post))}</b>\n\n{html.escape(body)}"
    if len(message) > 4096:
        raise ValueError("emergency message exceeds Telegram limit")
    return message


def _headline(post: SourcePost) -> str:
    transition = event_transition(post)
    text = post.text.casefold().replace("ё", "е")
    if transition == "threat_announced":
        if "бпла" in text or "беспилот" in text:
            return "Опасность атаки БПЛА объявлена в Оренбуржье"
        return "В Оренбургской области объявлена опасность"
    if transition == "threat_cleared":
        if "бпла" in text or "беспилот" in text:
            return "Отбой опасности атаки БПЛА в Оренбургской области"
        return "Отбой опасности в Оренбургской области"
    if transition == "road_restricted":
        return "Ограничение движения на дорогах в Оренбургской области"
    if transition == "road_reopened":
        return "Движение на дорогах в Оренбургской области восстановлено"
    if transition == "kover_introduced":
        return "В Оренбурге введён режим «Ковёр»"
    if transition == "kover_lifted":
        return "В Оренбурге отменён режим «Ковёр»"
    raise ValueError("post has no editorial headline")


def _editorial_body(text: str, transition: str | None) -> str:
    paragraphs = []
    for raw_paragraph in re.split(r"\n\s*\n", text.strip()):
        lines = []
        for raw_line in raw_paragraph.splitlines():
            line = raw_line.strip()
            if not line or _is_metadata_line(line):
                continue
            line = re.sub(r"https?://\S+", "", line, flags=re.IGNORECASE)
            line = re.sub(r"(?<!\w)#[\w-]+", "", line)
            line = re.sub(r"\s+", " ", line).strip(" ,;:-")
            if line:
                lines.append(line)
        paragraph = " ".join(lines)
        if paragraph:
            paragraphs.append(paragraph)
    if transition in {"road_restricted", "road_reopened"} and len(paragraphs) == 1:
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", paragraphs[0]) if sentence.strip()]
        if len(sentences) > 1 and sum("км" in sentence.casefold() for sentence in sentences) >= 2:
            paragraphs = sentences
    return "\n\n".join(paragraphs)


def _is_metadata_line(line: str) -> bool:
    lowered = line.casefold()
    return bool(re.match(r"(?:источник|id(?: публикации)?(?: max)?|max(?: chat_id)?|post_id|uuid|timestamp)\s*:", lowered))


def revision(post: SourcePost) -> str:
    return hashlib.sha256(post.text.encode("utf-8")).hexdigest()


def open_store(path: str) -> sqlite3.Connection:
    store_path = Path(path).expanduser()
    if not store_path.is_absolute() or store_path == Path(":memory:"):
        raise ValueError("emergency SQLite path must be absolute and persistent")
    store_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(store_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    file_stat = store_path.lstat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
        raise ValueError("emergency SQLite file must be private and regular")
    connection = sqlite3.connect(str(store_path), isolation_level=None, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY,
            revision TEXT NOT NULL,
            published_at TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deliveries (
            post_id TEXT NOT NULL,
            revision TEXT NOT NULL,
            destination TEXT NOT NULL CHECK(destination = '@benzinoren'),
            status TEXT NOT NULL,
            remote_id TEXT,
            sent_at TEXT,
            PRIMARY KEY (post_id, revision, destination)
        );
        CREATE TABLE IF NOT EXISTS worker_health (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS service_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def register_post(connection: sqlite3.Connection, post: SourcePost, now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if classify(post) is None:
        if post.channel_url == SOURCE_CHANNEL:
            with transaction(connection):
                connection.execute(
                    "UPDATE posts SET status='review_edit' WHERE post_id=? AND revision<>?",
                    (post.post_id, revision(post)),
                )
        return False
    age = now.astimezone(UTC) - post.published_at.astimezone(UTC)
    status = "pending" if timedelta(0) <= age <= MAX_AGE else "stale"
    current_revision = revision(post)
    with transaction(connection):
        previous = connection.execute("SELECT revision, status FROM posts WHERE post_id=?", (post.post_id,)).fetchone()
        if previous and previous[0] == current_revision:
            if status != "pending" and previous[1] == "pending":
                connection.execute("UPDATE posts SET status='stale' WHERE post_id=?", (post.post_id,))
            if status != "pending" or previous[1] != "pending":
                return False
            delivery = connection.execute(
                "SELECT status FROM deliveries WHERE post_id=? AND revision=? AND destination=?",
                (post.post_id, current_revision, TARGET_CHANNEL),
            ).fetchone()
            return bool(delivery and delivery[0] == "pending")
        if previous:
            status = "review_edit"
        connection.execute(
            "INSERT INTO posts VALUES (?, ?, ?, ?, ?) ON CONFLICT(post_id) DO UPDATE SET revision=excluded.revision, published_at=excluded.published_at, detected_at=excluded.detected_at, status=excluded.status",
            (post.post_id, current_revision, post.published_at.isoformat(), now.isoformat(), status),
        )
        if status == "pending":
            connection.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?, ?, 'pending', NULL, NULL)", (post.post_id, current_revision, TARGET_CHANNEL))
    return status == "pending"


def initialize_without_backfill(
    connection: sqlite3.Connection,
    posts: list[SourcePost],
    now: datetime,
) -> int:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    with transaction(connection):
        initialized = connection.execute(
            "SELECT value FROM service_state WHERE key='initialized_at'"
        ).fetchone()
        if initialized:
            return 0
        recorded = 0
        for post in posts:
            if classify(post) is None:
                continue
            cursor = connection.execute(
                "INSERT OR IGNORE INTO posts VALUES (?, ?, ?, ?, 'baseline')",
                (
                    post.post_id,
                    revision(post),
                    post.published_at.isoformat(),
                    now.isoformat(),
                ),
            )
            recorded += cursor.rowcount
        connection.execute(
            "INSERT INTO service_state VALUES ('initialized_at', ?)",
            (now.isoformat(),),
        )
    return recorded


def record_baseline_observations(
    connection: sqlite3.Connection,
    posts: list[SourcePost],
    now: datetime,
) -> int:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    recorded = 0
    with transaction(connection):
        for post in posts:
            if classify(post) is None:
                continue
            current_revision = revision(post)
            previous = connection.execute(
                "SELECT revision FROM posts WHERE post_id=?",
                (post.post_id,),
            ).fetchone()
            if previous is None:
                connection.execute(
                    "INSERT INTO posts VALUES (?, ?, ?, ?, 'baseline')",
                    (
                        post.post_id,
                        current_revision,
                        post.published_at.isoformat(),
                        now.isoformat(),
                    ),
                )
                recorded += 1
            elif previous[0] != current_revision:
                connection.execute(
                    "UPDATE posts SET revision=?, published_at=?, detected_at=?, status='review_edit' WHERE post_id=?",
                    (
                        current_revision,
                        post.published_at.isoformat(),
                        now.isoformat(),
                        post.post_id,
                    ),
                )
    return recorded


def claim_delivery(connection: sqlite3.Connection, post: SourcePost, destination: str, now: datetime) -> str | None:
    if destination != TARGET_CHANNEL:
        raise ValueError("unauthorized emergency destination")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    with transaction(connection):
        row = connection.execute("SELECT revision, published_at, status FROM posts WHERE post_id=?", (post.post_id,)).fetchone()
        if not row or row[0] != revision(post) or row[2] != "pending":
            return None
        published_at = datetime.fromisoformat(row[1])
        if not timedelta(0) <= now.astimezone(UTC) - published_at.astimezone(UTC) <= MAX_AGE:
            connection.execute("UPDATE posts SET status='stale' WHERE post_id=?", (post.post_id,))
            return None
        cursor = connection.execute(
            "UPDATE deliveries SET status='claimed' WHERE post_id=? AND revision=? AND destination=? AND status='pending'",
            (post.post_id, row[0], TARGET_CHANNEL),
        )
        return row[0] if cursor.rowcount == 1 else None


def confirm_delivery(connection: sqlite3.Connection, post: SourcePost, claimed_revision: str, remote_id: str, sent_at: datetime) -> None:
    if not remote_id or sent_at.tzinfo is None:
        raise ValueError("remote id and timezone-aware sent time required")
    with transaction(connection):
        cursor = connection.execute(
            "UPDATE deliveries SET status='sent', remote_id=?, sent_at=? WHERE post_id=? AND revision=? AND destination=? AND status='claimed'",
            (remote_id, sent_at.isoformat(), post.post_id, claimed_revision, TARGET_CHANNEL),
        )
        if cursor.rowcount != 1:
            raise ValueError("delivery was not claimed")


def record_removal(connection: sqlite3.Connection, post_id: str) -> None:
    with transaction(connection):
        connection.execute("UPDATE posts SET status='review_removed' WHERE post_id=?", (post_id,))
