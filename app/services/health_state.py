"""Small versioned liveness state, independent from published-source state."""

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.formatter import MONTHS


class HealthStateError(RuntimeError):
    """Raised when health state cannot be safely read or updated."""


@dataclass(frozen=True)
class DailyHealth:
    date: str
    runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    publications: int = 0
    publishable_facts: int = 0
    telegram_collected: int = 0
    max_collected: int = 0


@dataclass(frozen=True)
class HealthState:
    last_successful_run_at: datetime | None
    last_run_at: datetime | None
    consecutive_failures: int
    daily: DailyHealth
    last_daily_report_date: str | None = None


@dataclass(frozen=True)
class Liveness:
    status: str
    last_successful_run_at: datetime | None


class HealthStateStore:
    VERSION = 1

    def __init__(self, path: str | Path, timezone: str) -> None:
        self.path = Path(path)
        self.timezone = timezone

    def load(self, now: datetime) -> HealthState:
        self._require_aware(now)
        if not self.path.exists():
            return HealthState(None, None, 0, DailyHealth(self._local_date(now)))
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                raise ValueError("unsupported version")
            daily = payload["daily"]
            state = HealthState(
                self._timestamp(payload.get("last_successful_run_at")),
                self._timestamp(payload.get("last_run_at")),
                self._non_negative(payload["consecutive_failures"]),
                DailyHealth(
                    date=self._date(daily["date"]),
                    runs=self._non_negative(daily["runs"]),
                    successful_runs=self._non_negative(daily["successful_runs"]),
                    failed_runs=self._non_negative(daily["failed_runs"]),
                    publications=self._non_negative(daily["publications"]),
                    publishable_facts=self._non_negative(daily["publishable_facts"]),
                    telegram_collected=self._non_negative(daily["telegram_collected"]),
                    max_collected=self._non_negative(daily["max_collected"]),
                ),
                self._optional_date(payload.get("last_daily_report_date")),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HealthStateError("health state is malformed or unreadable") from exc
        return state

    def record_success(
        self, state: HealthState, now: datetime, *, publishable_facts: int, telegram_collected: int,
        max_collected: int, publication: bool,
    ) -> HealthState:
        return self._record(
            state, now, successful=True, publishable_facts=publishable_facts,
            telegram_collected=telegram_collected, max_collected=max_collected, publication=publication,
        )

    def record_failure(self, state: HealthState, now: datetime) -> HealthState:
        return self._record(state, now, successful=False, publishable_facts=0, telegram_collected=0, max_collected=0, publication=False)

    def _record(
        self, state: HealthState, now: datetime, *, successful: bool, publishable_facts: int,
        telegram_collected: int, max_collected: int, publication: bool,
    ) -> HealthState:
        self._require_aware(now)
        if min(publishable_facts, telegram_collected, max_collected) < 0:
            raise ValueError("health counters must be non-negative")
        daily = state.daily if state.daily.date == self._local_date(now) else DailyHealth(self._local_date(now))
        updated_daily = DailyHealth(
            date=daily.date,
            runs=daily.runs + 1,
            successful_runs=daily.successful_runs + int(successful),
            failed_runs=daily.failed_runs + int(not successful),
            publications=daily.publications + int(publication),
            publishable_facts=daily.publishable_facts + publishable_facts,
            telegram_collected=daily.telegram_collected + telegram_collected,
            max_collected=daily.max_collected + max_collected,
        )
        updated = HealthState(
            last_successful_run_at=now.astimezone(UTC) if successful else state.last_successful_run_at,
            last_run_at=now.astimezone(UTC),
            consecutive_failures=0 if successful else state.consecutive_failures + 1,
            daily=updated_daily,
            last_daily_report_date=state.last_daily_report_date,
        )
        self._write(updated)
        return updated

    def _write(self, state: HealthState) -> None:
        payload = {
            "version": self.VERSION,
            "last_successful_run_at": self._iso(state.last_successful_run_at),
            "last_run_at": self._iso(state.last_run_at),
            "consecutive_failures": state.consecutive_failures,
            "daily": asdict(state.daily),
            "last_daily_report_date": state.last_daily_report_date,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            raise HealthStateError("health state could not be saved") from exc

    def _local_date(self, now: datetime) -> str:
        return now.astimezone(ZoneInfo(self.timezone)).date().isoformat()

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("health timestamp must be timezone-aware")

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("invalid timestamp")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timezone-naive timestamp")
        return parsed

    @staticmethod
    def _date(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid date")
        return datetime.fromisoformat(value).date().isoformat()

    @staticmethod
    def _optional_date(value: object) -> str | None:
        return None if value is None else HealthStateStore._date(value)

    @staticmethod
    def _non_negative(value: object) -> int:
        if not isinstance(value, int) or value < 0:
            raise ValueError("invalid counter")
        return value

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value is not None else None


def build_daily_report(state: HealthState, timezone: str) -> str:
    date = datetime.fromisoformat(state.daily.date).date()
    last = state.last_successful_run_at
    last_text = last.astimezone(ZoneInfo(timezone)).strftime("%H:%M") if last else "нет"
    return "\n".join(
        [
            f"📊 Fuel Monitor — {date.day} {MONTHS[date.month - 1]}",
            "",
            f"Запусков: {state.daily.runs}",
            f"Успешных: {state.daily.successful_runs}",
            f"Ошибок: {state.daily.failed_runs}",
            f"Публикаций: {state.daily.publications}",
            f"Новых фактов: {state.daily.publishable_facts}",
            f"Telegram сообщений собрано: {state.daily.telegram_collected}",
            f"MAX сообщений собрано: {state.daily.max_collected}",
            "",
            f"Последний успешный запуск: {last_text}",
        ]
    )


def check_liveness(now: datetime, state: HealthState, max_age: timedelta = timedelta(hours=2)) -> Liveness:
    if now.tzinfo is None:
        raise ValueError("liveness timestamp must be timezone-aware")
    last = state.last_successful_run_at
    return Liveness("healthy" if last is not None and now.astimezone(UTC) - last <= max_age else "stale", last)


def build_stale_alert(state: HealthState, timezone: str) -> str:
    last = state.last_successful_run_at
    last_text = last.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M") if last else "нет"
    return f"🚨 Fuel Monitor\nНет успешного запуска более 2 часов.\nПоследний успешный: {last_text}"
