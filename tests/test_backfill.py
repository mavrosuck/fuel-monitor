import ast
from pathlib import Path


def test_backfill_is_explicitly_excluded_from_ai_and_summary_processing() -> None:
    source = Path("app/collector/message_handler.py").read_text(encoding="utf-8")
    ast.parse(source)
    backfill_section = source[source.index("async def store_backfill") : source.index("async def retry_pending")]
    assert "is_ai_processed=True" in backfill_section
    assert "has_new_fuel_information=False" in backfill_section
