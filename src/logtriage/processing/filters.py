"""Severity detection and pre-filtering rule engine."""

from __future__ import annotations

import re
from typing import List, Pattern

from logtriage.config import RulesConfig
from logtriage.models import ParsedLogRecord, SeverityLevel


class SeverityFilter:
    """Classifies log severity deterministically and filters out benign/informational logs."""

    def __init__(self, config: RulesConfig) -> None:
        self.critical_patterns: List[Pattern[str]] = [
            re.compile(p) for p in config.critical_patterns
        ]
        self.high_patterns: List[Pattern[str]] = [
            re.compile(p) for p in config.high_patterns
        ]
        self.medium_patterns: List[Pattern[str]] = [
            re.compile(p) for p in config.medium_patterns
        ]
        self.low_patterns: List[Pattern[str]] = [
            re.compile(p) for p in config.low_patterns
        ]
        self.ignore_patterns: List[Pattern[str]] = [
            re.compile(p) for p in config.ignore_patterns
        ]

    def is_ignored(self, text: str) -> bool:
        """Check if line matches any false-positive ignore patterns."""
        for pat in self.ignore_patterns:
            if pat.search(text):
                return True
        return False

    def classify_and_filter(self, record: ParsedLogRecord) -> ParsedLogRecord:
        """Evaluate severity, check false-positive rules, and determine if line is an error candidate."""
        # 1. Blank lines or empty messages are never error candidates
        if not record.message.strip():
            return record.model_copy(
                update={"is_error_candidate": False, "normalized_severity": SeverityLevel.INFO}
            )

        # 2. Check false-positive ignore rules
        full_text = f"{record.raw_line} {record.message}"
        if self.is_ignored(full_text):
            return record.model_copy(
                update={"is_error_candidate": False, "normalized_severity": SeverityLevel.INFO}
            )

        # 3. Match patterns from highest to lowest severity
        assigned_sev = record.normalized_severity

        # Check CRITICAL
        for pat in self.critical_patterns:
            if pat.search(full_text):
                assigned_sev = SeverityLevel.CRITICAL
                break

        # Check HIGH if not already critical
        if assigned_sev < SeverityLevel.CRITICAL:
            for pat in self.high_patterns:
                if pat.search(full_text):
                    assigned_sev = max(assigned_sev, SeverityLevel.HIGH)
                    break

        # Check MEDIUM if below high
        if assigned_sev < SeverityLevel.HIGH:
            for pat in self.medium_patterns:
                if pat.search(full_text):
                    assigned_sev = max(assigned_sev, SeverityLevel.MEDIUM)
                    break

        # Check LOW
        if assigned_sev < SeverityLevel.MEDIUM:
            for pat in self.low_patterns:
                if pat.search(full_text):
                    assigned_sev = SeverityLevel.LOW
                    break

        # 4. Determine if this record should be an error candidate
        # Routine INFO and LOW/DEBUG events MUST NOT trigger LLM inference or error grouping.
        # HIGH and CRITICAL events ALWAYS trigger.
        # MEDIUM (warnings/timeouts/retries) can trigger error candidate status.
        is_candidate = assigned_sev >= SeverityLevel.MEDIUM

        return record.model_copy(
            update={
                "normalized_severity": assigned_sev,
                "is_error_candidate": is_candidate,
            }
        )
