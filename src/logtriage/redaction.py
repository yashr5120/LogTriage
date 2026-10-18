"""Secret and sensitive data redaction filter.

Applies configurable regex patterns to scrub credentials, tokens, passwords,
and private keys from log content before it is sent to local LLMs or stored on disk.
Note: Regex-based redaction is a defense-in-depth safeguard and cannot guarantee
the elimination of all arbitrary secrets or unstructured confidential data.
"""

from __future__ import annotations

import re
from typing import List, Pattern

from logtriage.config import RedactionConfig


class Redactor:
    """Compiled regex redactor for sanitizing log messages and contexts."""

    def __init__(self, config: RedactionConfig) -> None:
        self.enabled = config.enabled
        self.mask = config.mask
        self._compiled: List[Pattern[str]] = []
        if self.enabled:
            for pat in config.patterns:
                try:
                    self._compiled.append(re.compile(pat))
                except re.error:
                    # Ignore invalid patterns and continue with valid ones
                    pass

    def redact_text(self, text: str) -> str:
        """Redact sensitive patterns from a single string."""
        if not self.enabled or not text:
            return text

        scrubbed = text
        for pattern in self._compiled:
            scrubbed = pattern.sub(self.mask, scrubbed)
        return scrubbed

    def redact_lines(self, lines: List[str]) -> List[str]:
        """Redact sensitive patterns from a list of log lines."""
        if not self.enabled:
            return lines
        return [self.redact_text(line) for line in lines]
