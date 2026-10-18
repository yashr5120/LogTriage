"""Machine-readable and human-readable alert sinks."""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TextIO

from logtriage.models import Alert


class AlertOutput(ABC):
    @abstractmethod
    def emit(self, alert: Alert) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class JsonlOutput(AlertOutput):
    """Write one complete alert JSON object per line."""

    def __init__(self, stream: TextIO = sys.stdout, file_path: str | None = None) -> None:
        self._stream = stream
        self._handle = (
            Path(file_path).open("a", encoding="utf-8") if file_path else None
        )

    def emit(self, alert: Alert) -> None:
        line = json.dumps(alert.model_dump(mode="json"), ensure_ascii=False)
        print(line, file=self._stream, flush=True)
        if self._handle:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle:
            self._handle.close()


class ConsoleOutput(AlertOutput):
    def emit(self, alert: Alert) -> None:
        print(
            f"[{alert.severity}] {alert.component}: {alert.summary} "
            f"(occurrences={alert.occurrences}, status={alert.status})"
        )

    def close(self) -> None:
        return
