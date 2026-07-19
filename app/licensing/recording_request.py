from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class RecordingRequestSource(StrEnum):
    SCAN = "SCAN"
    MANUAL = "MANUAL"
    SHORTCUT = "SHORTCUT"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True, slots=True)
class PendingRecordingRequest:
    order_no: str
    recording_type: str
    source: RecordingRequestSource
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    optional_metadata: dict[str, Any] = field(default_factory=dict)
