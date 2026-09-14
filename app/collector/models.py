from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class CollectedMessage:
    platform: Literal["telegram", "max"]
    source_chat_id: int
    source_message_id: int
    message_date: datetime
    text: str
    source_name: str | None = None
