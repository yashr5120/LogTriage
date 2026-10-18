"""Log parsing and normalizer for structured (JSON) and unstructured text logs."""

from __future__ import annotations

import json
import re
from typing import Optional

from logtriage.models import ParsedLogRecord, SeverityLevel

# Common timestamp regexes
ISO_TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
SYSLOG_TIMESTAMP_RE = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"
)

# Standard log level tokens
LOG_LEVEL_RE = re.compile(
    r"\b(FATAL|CRITICAL|PANIC|EMERGENCY|ERROR|ERR|WARN|WARNING|INFO|DEBUG|TRACE|NOTICE)\b",
    re.IGNORECASE,
)

# Component/module patterns like [database], [auth], app.database:, or worker-1:
COMPONENT_RE = re.compile(
    r"(?:\[([a-zA-Z0-9_\-\.\/]+)\]|([a-zA-Z0-9_\-\.]+):|([a-zA-Z0-9_\-]+-\d+):)"
)


class LogParser:
    """Parses raw log lines into normalized ParsedLogRecord instances."""

    def __init__(self, max_line_length: int = 10000) -> None:
        self.max_line_length = max_line_length

    def parse_line(self, line: str, line_number: int) -> ParsedLogRecord:
        """Parse a single raw log line safely."""
        # Sanitize length to avoid memory denial-of-service
        if len(line) > self.max_line_length:
            line = line[: self.max_line_length] + "...[TRUNCATED]"

        stripped = line.strip()
        if not stripped:
            return ParsedLogRecord(
                raw_line=line,
                line_number=line_number,
                message="",
                normalized_severity=SeverityLevel.INFO,
                is_error_candidate=False,
            )

        # Check for JSON log
        if stripped.startswith("{") and stripped.endswith("}"):
            json_record = self._try_parse_json(stripped, line, line_number)
            if json_record is not None:
                return json_record

        # Conventional text log parsing
        return self._parse_text(stripped, line, line_number)

    def _try_parse_json(
        self, stripped: str, raw_line: str, line_number: int
    ) -> Optional[ParsedLogRecord]:
        try:
            data = json.loads(stripped)
            if not isinstance(data, dict):
                return None
        except Exception:
            return None

        # Extract timestamp
        ts = None
        for key in ("timestamp", "time", "@timestamp", "datetime", "date"):
            if key in data and isinstance(data[key], (str, int, float)):
                ts = str(data[key])
                break

        # Extract severity / level
        raw_level = None
        for key in ("level", "severity", "log_level", "levelname", "status"):
            if key in data and isinstance(data[key], str):
                raw_level = data[key]
                break

        # Extract message
        msg = ""
        for key in ("message", "msg", "error", "err", "description", "event"):
            if key in data and data[key] is not None:
                msg = str(data[key])
                break

        # Extract component / service
        component = "unknown"
        for key in ("component", "service", "logger", "app", "name", "module"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                component = data[key].strip()
                break

        norm_sev = SeverityLevel.from_str(raw_level) if raw_level else SeverityLevel.INFO

        return ParsedLogRecord(
            raw_line=raw_line,
            line_number=line_number,
            timestamp=ts,
            raw_level=raw_level,
            normalized_severity=norm_sev,
            component=component,
            message=msg or stripped,
            is_error_candidate=False,  # SeverityFilter will evaluate
            structured_data=data,
        )

    def _parse_text(self, stripped: str, raw_line: str, line_number: int) -> ParsedLogRecord:
        working = stripped
        timestamp: Optional[str] = None
        raw_level: Optional[str] = None
        component: str = "unknown"

        # 1. Match timestamp
        m_iso = ISO_TIMESTAMP_RE.match(working)
        if m_iso:
            timestamp = m_iso.group(1)
            working = working[m_iso.end() :].strip()
        else:
            m_syslog = SYSLOG_TIMESTAMP_RE.match(working)
            if m_syslog:
                timestamp = m_syslog.group(1)
                working = working[m_syslog.end() :].strip()

        # 2. Match log level
        m_level = LOG_LEVEL_RE.search(working)
        if m_level:
            raw_level = m_level.group(1)
            norm_sev = SeverityLevel.from_str(raw_level)
        else:
            norm_sev = SeverityLevel.INFO

        # 3. Match component/logger
        m_comp = COMPONENT_RE.search(working)
        if m_comp:
            for g in m_comp.groups():
                if g:
                    component = g.strip()
                    break

        # If component is still unknown, check for common domain keywords
        if component == "unknown":
            lower = working.lower()
            if "database" in lower or "postgres" in lower or "mysql" in lower or "sql" in lower:
                component = "database"
            elif "auth" in lower or "login" in lower or "credential" in lower:
                component = "auth"
            elif "network" in lower or "http" in lower or "socket" in lower:
                component = "network"
            elif "disk" in lower or "filesystem" in lower or "storage" in lower:
                component = "storage"
            elif "memory" in lower or "oom" in lower:
                component = "memory"

        return ParsedLogRecord(
            raw_line=raw_line,
            line_number=line_number,
            timestamp=timestamp,
            raw_level=raw_level,
            normalized_severity=norm_sev,
            component=component,
            message=working,
            is_error_candidate=False,
            structured_data=None,
        )
