"""Deterministic synthetic scenarios used by demos and benchmarks."""

from __future__ import annotations

from collections.abc import Iterable

SCENARIOS = {
    "database-failure": [
        "2026-10-18 10:12:03 INFO Application started",
        "2026-10-18 10:12:06 ERROR Database connection failed",
        "2026-10-18 10:12:06 ERROR Connection refused at 127.0.0.1:5432",
        "2026-10-18 10:12:08 CRITICAL Service startup aborted",
    ],
    "traceback": [
        "2026-10-18 10:12:03 ERROR Traceback (most recent call last):",
        '  File "worker.py", line 42, in run',
        "    raise ValueError('bad input')",
        "ValueError: bad input",
    ],
    "startup": [
        "2026-10-18 10:12:03 INFO Application started",
        "2026-10-18 10:12:04 INFO Configuration loaded",
        "2026-10-18 10:12:05 INFO Ready",
    ],
    "oom": ["2026-10-18 10:12:03 ERROR OutOfMemoryError allocating buffer"],
}


def generate_logs(scenario: str = "database-failure", repeat: int = 1) -> Iterable[str]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'. Choose from: {', '.join(SCENARIOS)}")
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    for _ in range(repeat):
        yield from SCENARIOS[scenario]
