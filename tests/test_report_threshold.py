from datetime import UTC, datetime, timedelta

from app.database.models import SourceMessage
from app.services.report_service import (
    filter_information_messages,
    publication_allowed,
    unique_information_messages,
)


def message(message_id: int, text: str, date: datetime, *, fact: bool = True, processed: bool = True) -> SourceMessage:
    return SourceMessage(
        chat_id=1,
        chat_username="source",
        telegram_message_id=message_id,
        message_text=text,
        message_date=date,
        is_ai_processed=processed,
        has_new_fuel_information=fact,
    )


def test_four_facts_do_not_allow_publication() -> None:
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    facts = [message(index, f"Факт {index}", now - timedelta(minutes=index)) for index in range(4)]
    assert not publication_allowed(facts, 5)


def test_five_facts_allow_publication() -> None:
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    facts = [message(index, f"Факт {index}", now - timedelta(minutes=index)) for index in range(5)]
    assert publication_allowed(facts, 5)


def test_repost_is_counted_once() -> None:
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    messages = [message(1, "На АЗС есть АИ-95", now - timedelta(minutes=5)), message(2, "На   АЗС есть АИ-95", now)]
    assert len(unique_information_messages(messages)) == 1


def test_backfill_and_non_facts_are_excluded_from_hour() -> None:
    end = datetime(2026, 8, 28, 12, tzinfo=UTC)
    start = end - timedelta(hours=1)
    current_fact = message(1, "Есть АИ-95", end - timedelta(minutes=5))
    backfill = message(2, "Старое сообщение", end - timedelta(minutes=10), fact=False, processed=True)
    question = message(3, "Где АИ-95?", end - timedelta(minutes=15), fact=False, processed=True)
    old_fact = message(4, "Давний факт", end - timedelta(hours=2))
    filtered = filter_information_messages([current_fact, backfill, question, old_fact], start, end)
    assert filtered == [current_fact]
