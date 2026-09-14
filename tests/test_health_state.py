from datetime import UTC, datetime, timedelta

from app.services.health_state import HealthStateStore, build_daily_report, build_stale_alert, check_liveness


def test_successful_and_failed_runs_update_small_daily_health_state(tmp_path) -> None:
    store = HealthStateStore(tmp_path / "health.json", "Asia/Yekaterinburg")
    first = datetime(2026, 9, 15, 5, tzinfo=UTC)
    state = store.load(first)
    state = store.record_success(
        state, first, publishable_facts=1, telegram_collected=2, max_collected=3, publication=False,
    )
    state = store.record_failure(state, first + timedelta(hours=1))

    assert state.last_successful_run_at == first
    assert state.consecutive_failures == 1
    assert state.daily.runs == 2
    assert state.daily.successful_runs == 1
    assert state.daily.failed_runs == 1
    assert state.daily.publications == 0
    assert state.daily.publishable_facts == 1
    assert state.daily.telegram_collected == 2
    assert state.daily.max_collected == 3


def test_daily_report_and_liveness_are_deterministic(tmp_path) -> None:
    store = HealthStateStore(tmp_path / "health.json", "Asia/Yekaterinburg")
    now = datetime(2026, 9, 15, 20, tzinfo=UTC)
    state = store.record_success(
        store.load(now), now, publishable_facts=4, telegram_collected=5, max_collected=6, publication=True,
    )

    assert build_daily_report(state, "Asia/Yekaterinburg") == (
        "📊 Fuel Monitor — 16 сентября\n\n"
        "Запусков: 1\nУспешных: 1\nОшибок: 0\nПубликаций: 1\nНовых фактов: 4\n"
        "Telegram сообщений собрано: 5\nMAX сообщений собрано: 6\n\nПоследний успешный запуск: 01:00"
    )
    assert check_liveness(now + timedelta(hours=1, minutes=59), state).status == "healthy"
    assert check_liveness(now + timedelta(hours=2, minutes=1), state).status == "stale"
    assert "Последний успешный: 2026-09-16 01:00" in build_stale_alert(state, "Asia/Yekaterinburg")
