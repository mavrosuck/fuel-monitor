from pathlib import Path


def test_workflow_defaults_to_dry_run_and_only_updates_state_for_publish() -> None:
    workflow = Path(".github/workflows/main.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert "type: boolean" in workflow
    assert "DRY_RUN: ${{ inputs.publish && '0' || '1' }}" in workflow
    assert "group: fuel-monitor-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "if: ${{ inputs.publish }}" in workflow
    assert "Runtime state changed remotely; refusing to overwrite it." in workflow
    assert "schedule:" not in workflow
