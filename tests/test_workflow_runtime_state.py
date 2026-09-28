from pathlib import Path


def test_workflow_restores_and_safely_updates_independent_runtime_state_files() -> None:
    workflow = Path(".github/workflows/main.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert "type: boolean" in workflow
    assert "schedule:" in workflow
    assert 'cron: "7,17,27,37,47,57 * * * *"' in workflow
    assert 'cron: "23 * * * *"' in workflow
    assert "DRY_RUN: ${{ github.event_name == 'schedule' && github.event.schedule == '23 * * * *' && '0' || github.event_name == 'workflow_dispatch' && inputs.publish && '0' || '1' }}" in workflow
    assert "group: fuel-monitor-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "HEALTH_STATE_PATH: ${{ github.workspace }}/.runtime-state/health.json" in workflow
    assert 'git show "$state_head:published-source-messages.json"' in workflow
    assert 'git show "$state_head:health.json"' in workflow
    assert 'HealthStateStore(".runtime-state/health.json", "Asia/Yekaterinburg").load(datetime.now(UTC))' in workflow
    assert "if: ${{ (github.event_name == 'schedule' && github.event.schedule == '23 * * * *') || (github.event_name == 'workflow_dispatch' && inputs.publish) && (success() || failure()) }}" in workflow
    assert 'cp .runtime-state/published-source-messages.json "$state_worktree/published-source-messages.json"' in workflow
    assert 'cp .runtime-state/health.json "$state_worktree/health.json"' in workflow
    assert 'git -C "$state_worktree" add published-source-messages.json health.json' in workflow
    assert "Runtime state files are unavailable; no state commit created." in workflow
    assert "Runtime state unchanged; no state commit created." in workflow
    assert "Runtime state changed remotely; refusing to overwrite it." in workflow
    assert "git -C \"$state_worktree\" push --force" not in workflow
    assert "git -C \"$state_worktree\" push origin --force" not in workflow
