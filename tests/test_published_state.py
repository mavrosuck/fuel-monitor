import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.published_state import PublishedMessageStore, PublishedStateError


def test_missing_state_is_empty_and_distinguishes_platform_and_chat_ids(tmp_path) -> None:
    store = PublishedMessageStore(tmp_path / "published-source-messages.json")
    state = store.load()
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    source_dates = {
        "telegram|1|99": now,
        "telegram|2|99": now,
        "max|1|99": now,
    }

    store.record_published(state, source_dates, now)

    assert set(store.load().published_messages) == set(source_dates)


def test_retention_removes_only_old_published_entries(tmp_path) -> None:
    path = tmp_path / "published-source-messages.json"
    old = datetime(2026, 8, 1, tzinfo=UTC)
    path.write_text(json.dumps({"version": 1, "published_messages": {"telegram|1|1": {"published_at": old.isoformat(), "source_date": old.isoformat()}}}), encoding="utf-8")
    store = PublishedMessageStore(path, retention_days=14)
    now = old + timedelta(days=15)

    store.record_published(store.load(), {"telegram|1|2": now}, now)

    assert set(store.load().published_messages) == {"telegram|1|2"}


def test_malformed_state_fails_closed(tmp_path) -> None:
    path = tmp_path / "published-source-messages.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(PublishedStateError, match="malformed"):
        PublishedMessageStore(path).load()


def test_state_update_detects_a_concurrent_change(tmp_path) -> None:
    path = tmp_path / "published-source-messages.json"
    store = PublishedMessageStore(path)
    state = store.load()
    path.write_text('{"version": 1, "published_messages": {}}\n', encoding="utf-8")

    with pytest.raises(PublishedStateError, match="changed during this run"):
        store.record_published(state, {"telegram|1|1": datetime(2026, 9, 14, tzinfo=UTC)}, datetime(2026, 9, 14, tzinfo=UTC))
