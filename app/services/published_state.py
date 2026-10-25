"""Persistent source-message state stored in a checkout of the runtime-state branch."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


class PublishedStateError(RuntimeError):
    """Raised when published-message state cannot be safely read or updated."""


@dataclass(frozen=True)
class PublishedMessageState:
    published_messages: dict[str, dict[str, str]]
    published_slots: dict[str, str]
    fingerprint: str | None


class PublishedMessageStore:
    VERSION = 2

    def __init__(self, path: str | Path, retention_days: int = 14) -> None:
        self.path = Path(path)
        self.retention = timedelta(days=retention_days)

    def load(self) -> PublishedMessageState:
        if not self.path.exists():
            return PublishedMessageState({}, {}, None)
        try:
            raw = self.path.read_bytes()
            payload = json.loads(raw)
            version = payload.get("version")
            if version not in (1, self.VERSION) or not isinstance(payload.get("published_messages"), dict):
                raise ValueError("invalid state shape")
            messages = payload["published_messages"]
            for key, value in messages.items():
                if not self._valid_key(key) or not isinstance(value, dict):
                    raise ValueError("invalid state entry")
                self._parse_timestamp(value.get("published_at"))
                self._parse_timestamp(value.get("source_date"))
            slots = payload.get("published_slots", {})
            if not isinstance(slots, dict):
                raise ValueError("invalid published slots")
            for slot, published_at in slots.items():
                self._parse_utc_slot(slot)
                self._parse_timestamp(published_at)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PublishedStateError("published-message state is malformed or unreadable") from exc
        return PublishedMessageState(messages, slots, self._fingerprint(raw))

    def has_published_slot(self, state: PublishedMessageState, slot_end: datetime) -> bool:
        return self._slot_key(slot_end) in state.published_slots

    def record_published(
        self,
        state: PublishedMessageState,
        source_dates: dict[str, datetime],
        published_at: datetime,
        *,
        slot_end: datetime | None = None,
    ) -> None:
        if published_at.tzinfo is None:
            raise ValueError("published timestamp must be timezone-aware")
        current = self.load()
        if current.fingerprint != state.fingerprint:
            raise PublishedStateError("published-message state changed during this run")
        messages = dict(current.published_messages)
        slots = dict(current.published_slots)
        timestamp = published_at.astimezone(UTC).isoformat()
        for key, source_date in source_dates.items():
            if not self._valid_key(key) or source_date.tzinfo is None:
                raise ValueError("source identity and timestamp must be valid")
            messages[key] = {
                "published_at": timestamp,
                "source_date": source_date.astimezone(UTC).isoformat(),
            }
        cutoff = published_at.astimezone(UTC) - self.retention
        messages = {
            key: value
            for key, value in messages.items()
            if self._parse_timestamp(value["published_at"]) >= cutoff
        }
        if slot_end is not None:
            slots[self._slot_key(slot_end)] = timestamp
        slots = {
            slot: value
            for slot, value in slots.items()
            if self._parse_timestamp(value) >= cutoff
        }
        payload = {
            "version": self.VERSION,
            "published_messages": dict(sorted(messages.items())),
            "published_slots": dict(sorted(slots.items())),
        }
        self._write_atomically(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _valid_key(key: object) -> bool:
        return isinstance(key, str) and len(key.split("|")) == 3 and all(key.split("|"))

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("timestamp is missing")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError("timestamp is timezone-naive")
        return timestamp

    @classmethod
    def _parse_utc_slot(cls, value: object) -> datetime:
        timestamp = cls._parse_timestamp(value)
        if timestamp.utcoffset() != timedelta(0) or any(
            (timestamp.minute, timestamp.second, timestamp.microsecond)
        ):
            raise ValueError("publication slot must be an exact UTC hour")
        return timestamp

    @classmethod
    def _slot_key(cls, slot_end: datetime) -> str:
        if slot_end.tzinfo is None:
            raise ValueError("publication slot must be timezone-aware")
        return cls._parse_utc_slot(slot_end.astimezone(UTC).isoformat()).isoformat()

    @staticmethod
    def _fingerprint(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _write_atomically(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            raise PublishedStateError("published-message state could not be saved") from exc
