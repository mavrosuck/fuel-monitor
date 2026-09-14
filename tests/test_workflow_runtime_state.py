from pathlib import Path


def test_workflow_supports_safe_manual_and_scheduled_production_runs() -> None:
    workflow = Path(".github/workflows/main.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert "type: boolean" in workflow
    assert "- cron: '23 * * * *'" in workflow
    assert "DRY_RUN: ${{ (github.event_name == 'schedule' || inputs.publish) && '0' || '1' }}" in workflow
    assert "group: fuel-monitor-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "if: ${{ github.event_name == 'schedule' || inputs.publish }}" in workflow
    assert "Runtime state changed remotely; refusing to overwrite it." in workflow
