"""Core domain models for the Log & Error Triage Engine."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SeverityLevel(str, Enum):
    """Normalized log and alert severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @classmethod
    def from_str(cls, val: str) -> "SeverityLevel":
        norm = val.strip().upper()
        if norm in cls.__members__:
            return cls[norm]
        # Common aliases
        if norm in ("FATAL", "PANIC", "EMERGENCY"):
            return cls.CRITICAL
        if norm in ("ERROR", "ERR"):
            return cls.HIGH
        if norm in ("WARN", "WARNING"):
            return cls.MEDIUM
        if norm in ("DEBUG", "TRACE", "NOTICE", "VERBOSE"):
            return cls.LOW
        return cls.INFO

    @property
    def rank(self) -> int:
        """Numeric rank for severity comparison (higher = more critical)."""
        ranks = {
            SeverityLevel.CRITICAL: 50,
            SeverityLevel.HIGH: 40,
            SeverityLevel.MEDIUM: 30,
            SeverityLevel.LOW: 20,
            SeverityLevel.INFO: 10,
        }
        return ranks[self]

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, SeverityLevel):
            return self.rank >= other.rank
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, SeverityLevel):
            return self.rank > other.rank
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, SeverityLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, SeverityLevel):
            return self.rank < other.rank
        return NotImplemented


class ParsedLogRecord(BaseModel):
    """Normalized representation of a single log line."""

    model_config = ConfigDict(frozen=True)

    raw_line: str
    line_number: int
    timestamp: Optional[str] = None
    raw_level: Optional[str] = None
    normalized_severity: SeverityLevel = SeverityLevel.INFO
    component: str = "unknown"
    message: str = ""
    is_error_candidate: bool = False
    structured_data: Optional[Dict[str, Any]] = None


class ErrorContext(BaseModel):
    """Assembled multiline context for an error event or traceback."""

    event_id: str
    initial_record: ParsedLogRecord
    lines: List[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    is_traceback: bool = False
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    token_estimate: int = 0
    flushed_reason: Optional[str] = None

    def get_full_context_text(self) -> str:
        """Return the combined multiline context text."""
        return "\n".join(self.lines)


class GroupedEvent(BaseModel):
    """Aggregated cluster of matching errors within a sliding window."""

    fingerprint: str
    first_seen: str  # ISO 8601 UTC
    last_seen: str  # ISO 8601 UTC
    occurrences: int = 1
    representative_context: ErrorContext
    latest_context: ErrorContext
    highest_severity: SeverityLevel
    successful_analyses: int = 0
    last_alert_time: Optional[float] = None  # monotonic or epoch float
    last_alert_occurrences: int = 0
    processing_status: str = "pending"  # pending, analyzing, analyzed, cooldown, expired


class AnalysisResult(BaseModel):
    """Schema for structured model or rules-based analysis."""

    severity: SeverityLevel
    component: str
    summary: str
    category: str
    confidence: Optional[float] = None


class Alert(BaseModel):
    """Canonical alert output structure."""

    event_id: str
    fingerprint: str
    timestamp: str  # ISO 8601 UTC
    first_seen: str  # ISO 8601 UTC
    last_seen: str  # ISO 8601 UTC
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    component: str
    summary: str
    category: str
    confidence: Optional[float] = None
    occurrences: int
    status: str  # "analyzed", "rules_only", "inference_failed"
    analysis_source: str  # "ollama", "rules_fallback"
    model: str
    inference_latency_ms: Optional[float] = None
    context_sample: Optional[List[str]] = None
