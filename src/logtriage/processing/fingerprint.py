"""Stable log error fingerprinting with volatile token normalization."""

from __future__ import annotations

import hashlib
import os
import re
from typing import List

from logtriage.models import ErrorContext

# Regex patterns for volatile tokens
TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
HEX_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{4,16}\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
REQUEST_ID_RE = re.compile(r"\b(?:req|request|task|span|trace)[_\-][0-9a-zA-Z]{6,36}\b")
EPHEMERAL_PORT_RE = re.compile(r"(:\d{4,5})\b")
IP_PORT_RE = re.compile(r"(\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\d+\b")
STACK_LINE_RE = re.compile(r'File "([^"]+)", line \d+, in (\w+)')


class LogFingerprinter:
    """Generates stable, content-derived fingerprints for deduplicating error events."""

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Strip volatile and ephemeral tokens from error strings."""
        s = TIMESTAMP_RE.sub("<TS>", text)
        s = HEX_ADDR_RE.sub("<ADDR>", s)
        s = UUID_RE.sub("<UUID>", s)
        s = REQUEST_ID_RE.sub("<REQ_ID>", s)
        s = IP_PORT_RE.sub(r"\1:<PORT>", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @classmethod
    def normalize_stack_frame(cls, frame_line: str) -> str:
        """Normalize stack frame lines by removing line numbers and full directories."""
        m = STACK_LINE_RE.search(frame_line)
        if m:
            filepath = m.group(1)
            filename = os.path.basename(filepath)
            func_name = m.group(2)
            return f"{filename}:{func_name}"
        return cls.normalize_text(frame_line)

    @classmethod
    def compute_fingerprint(cls, context: ErrorContext) -> str:
        """Compute a deterministic SHA-256 fingerprint from the ErrorContext."""
        component = context.initial_record.component.lower()
        tokens: List[str] = [f"comp:{component}"]

        if context.exception_type:
            tokens.append(f"exc:{context.exception_type}")

        if context.is_traceback:
            # Extract normalized frame indicators
            frames: List[str] = []
            for line in context.lines:
                if 'File "' in line:
                    frames.append(cls.normalize_stack_frame(line))
            if frames:
                # Top frames + bottom frame
                frame_summary = "-".join(frames[-3:])
                tokens.append(f"frames:{frame_summary}")

        # Add normalized message from initial record
        init_msg = cls.normalize_text(context.initial_record.message)
        tokens.append(f"msg:{init_msg}")

        canonical_repr = "|".join(tokens)
        digest = hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
        return digest[:16]
