"""Traceback and multiline error-context assembler."""

from __future__ import annotations

import re
import time
import uuid
from typing import List, Optional

from logtriage.config import AggregatorConfig
from logtriage.models import ErrorContext, ParsedLogRecord

# Traceback markers
TRACEBACK_START_RE = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)
STACK_FRAME_RE = re.compile(r'^\s+File "([^"]+)", line (\d+), in (.+)')
EXCEPTION_LINE_RE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_\.]*(?:Error|Exception|Fault|Panic|Failure))(?::\s*(.*))?$"
)
CAUSED_BY_RE = re.compile(r"^(?:Caused by:|During handling of the above exception)", re.IGNORECASE)


class TracebackAssembler:
    """Assembles multiline stack traces and contextual error lines into bounded ErrorContext objects."""

    def __init__(self, config: AggregatorConfig) -> None:
        self.max_context_lines = config.max_context_lines
        self.max_token_budget = config.max_token_budget
        self.inactivity_timeout = config.inactivity_timeout_seconds

        self._active_context: Optional[ErrorContext] = None
        self._last_line_time: float = time.time()

    def process_record(
        self, record: ParsedLogRecord, now: Optional[float] = None
    ) -> List[ErrorContext]:
        """Ingest a record. Returns completed/flushed ErrorContexts if ready."""
        current_time = now if now is not None else time.time()
        flushed_events: List[ErrorContext] = []

        # 1. Check inactivity timeout on existing active context
        if self._active_context is not None:
            if current_time - self._last_line_time >= self.inactivity_timeout:
                ev = self._finalize_active("inactivity_timeout")
                if ev:
                    flushed_events.append(ev)

        raw = record.raw_line
        is_tb_start = bool(TRACEBACK_START_RE.search(raw))
        is_stack_line = bool(
            raw.startswith("  ")
            or STACK_FRAME_RE.match(raw)
            or CAUSED_BY_RE.match(raw.strip())
        )
        is_exception_line = bool(EXCEPTION_LINE_RE.match(raw.strip()))

        # 2. If we are currently accumulating a traceback/error context:
        if self._active_context is not None:
            # Check if this line continues the current error context
            if is_tb_start:
                # A new traceback starts immediately; finalize current and start new
                ev = self._finalize_active("new_traceback_start")
                if ev:
                    flushed_events.append(ev)
                self._start_new_context(record, is_traceback=True)
                self._last_line_time = current_time
                return flushed_events

            if self._active_context.is_traceback:
                if is_stack_line or is_exception_line or raw.startswith("    "):
                    self._append_line(record.raw_line)
                    if is_exception_line:
                        m = EXCEPTION_LINE_RE.match(raw.strip())
                        if m:
                            self._active_context.exception_type = m.group(1)
                            self._active_context.exception_message = m.group(2) or ""
                    # Check limits
                    if self._check_limits_exceeded():
                        ev = self._finalize_active("limit_exceeded")
                        if ev:
                            flushed_events.append(ev)
                    self._last_line_time = current_time
                    return flushed_events
                else:
                    # Non-stack line encountered: finalize the traceback
                    ev = self._finalize_active("traceback_ended")
                    if ev:
                        flushed_events.append(ev)
                    # Now continue processing the current line as a potential new candidate
            else:
                # Active context was a regular multiline error
                if record.is_error_candidate and record.normalized_severity == self._active_context.initial_record.normalized_severity:
                    self._append_line(record.raw_line)
                    if self._check_limits_exceeded():
                        ev = self._finalize_active("limit_exceeded")
                        if ev:
                            flushed_events.append(ev)
                    self._last_line_time = current_time
                    return flushed_events
                else:
                    ev = self._finalize_active("error_sequence_ended")
                    if ev:
                        flushed_events.append(ev)

        # 3. Not currently accumulating an active context (or just finalized)
        if is_tb_start:
            self._start_new_context(record, is_traceback=True)
            self._last_line_time = current_time
        elif record.is_error_candidate:
            # Start error context
            self._start_new_context(record, is_traceback=False)
            self._last_line_time = current_time

            # If it's a standalone single-line critical/high error that is not multiline,
            # we keep it active briefly for possible continuation lines or finalize immediately
            # if it's already complete.
            # To avoid latency on single-line errors when no continuation comes, we can finalize
            # during next line or flush.

        return flushed_events

    def _start_new_context(self, record: ParsedLogRecord, is_traceback: bool) -> None:
        self._active_context = ErrorContext(
            event_id=str(uuid.uuid4()),
            initial_record=record,
            lines=[record.raw_line],
            start_line=record.line_number,
            end_line=record.line_number,
            is_traceback=is_traceback,
            exception_type=None,
            exception_message=None,
            token_estimate=self._estimate_tokens(record.raw_line),
        )

    def _append_line(self, raw_line: str) -> None:
        if self._active_context is None:
            return
        self._active_context.lines.append(raw_line)
        self._active_context.end_line += 1
        self._active_context.token_estimate += self._estimate_tokens(raw_line)

    def _estimate_tokens(self, text: str) -> int:
        """Conservative character-budget token estimate (~4 characters per token)."""
        return max(1, len(text) // 4)

    def _check_limits_exceeded(self) -> bool:
        if self._active_context is None:
            return False
        if len(self._active_context.lines) >= self.max_context_lines:
            return True
        if self._active_context.token_estimate >= self.max_token_budget:
            return True
        return False

    def _finalize_active(self, reason: str) -> Optional[ErrorContext]:
        if self._active_context is None:
            return None
        ctx = self._active_context
        ctx.flushed_reason = reason
        self._active_context = None
        return ctx

    def flush(self) -> List[ErrorContext]:
        """Flush any currently held active context (e.g. at EOF)."""
        ev = self._finalize_active("stream_end")
        return [ev] if ev else []
