"""Streaming log source adapters."""

from .sources import FileSource, IterableSource, StdinSource, follow_file

__all__ = ["FileSource", "IterableSource", "StdinSource", "follow_file"]
