"""Bounded, line-oriented input sources for the triage pipeline."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path


class IterableSource:
    """Adapt an iterable of strings to the source interface."""

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = lines

    def __iter__(self) -> Iterator[str]:
        return iter(self._lines)


class StdinSource:
    """Read stdin incrementally without buffering the complete stream."""

    def __iter__(self) -> Iterator[str]:
        yield from sys.stdin


class FileSource:
    """Read a regular file incrementally and refuse directories."""

    def __init__(self, path: str | Path, encoding: str = "utf-8") -> None:
        self.path = Path(path)
        self.encoding = encoding

    def __iter__(self) -> Iterator[str]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Input log file does not exist: {self.path}")
        with self.path.open("r", encoding=self.encoding, errors="replace") as handle:
            yield from handle


def follow_file(
    path: str | Path,
    poll_interval: float = 0.25,
    encoding: str = "utf-8",
) -> Iterator[str]:
    """Tail a file, handling truncation and inode-based rotation."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Input log file does not exist: {target}")
    with target.open("r", encoding=encoding, errors="replace") as handle:
        identity = _identity(target)
        while True:
            line = handle.readline()
            if line:
                yield line
                continue
            try:
                current = _identity(target)
                if current != identity or target.stat().st_size < handle.tell():
                    handle.close()
                    handle = target.open("r", encoding=encoding, errors="replace")
                    identity = current
                    continue
            except FileNotFoundError:
                pass
            time.sleep(poll_interval)


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino
