import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.collector.message_handler import BatchProcessOutcome
from app.scheduler import hourly_job


class FakeHandler:
    def __init__(self, outcome: BatchProcessOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    async def process_pending_batch(self) -> BatchProcessOutcome:
        self.calls += 1
        return self.outcome


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def publish(self, text: str) -> int:
        self.calls.append(text)
        return 99


class FakeSession:
    def add(self, value) -> None:
        self.added = value

    async def commit(self) -> None:
        self.committed = True


class FakeSessions:
    def __init__(self) -> None:
        self.session = FakeSession()

    def __call__(self):
        session = self.session

        class Context:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                return False

        return Context()


def test_zero_messages_skips_publisher_and_report_service(monkeypatch) -> None:
    handler = FakeHandler(BatchProcessOutcome(0, []))
    publisher = FakePublisher()
    asyncio.run(hourly_job.run_hourly_job(FakeSessions(), publisher, handler, 5, "Asia/Yekaterinburg"))
    assert handler.calls == 1
    assert publisher.calls == []


def test_five_or_more_facts_create_one_publication(monkeypatch) -> None:
    class FakeReportService:
        def __init__(self, *_args) -> None:
            pass

        async def build_summary_for_message_ids(self, ids):
            assert len(ids) == 5
            now = datetime.now(UTC)
            return "summary", 5, now, now

    monkeypatch.setattr(hourly_job, "ReportService", FakeReportService)
    handler = FakeHandler(BatchProcessOutcome(5, [1, 2, 3, 4, 5]))
    publisher = FakePublisher()
    sessions = FakeSessions()
    asyncio.run(hourly_job.run_hourly_job(sessions, publisher, handler, 5, "Asia/Yekaterinburg"))
    assert publisher.calls == ["summary"]
    assert sessions.session.committed
