from pathlib import Path


def test_preview_does_not_import_or_use_bot_publisher() -> None:
    source = Path("app/publisher/preview.py").read_text(encoding="utf-8")
    assert "TelegramPublisher" not in source
    assert ".publish(" not in source
