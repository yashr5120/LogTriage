"""Optional SQLite alert history using parameterized statements."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from logtriage.models import Alert


class AlertStore:
    def __init__(self, path: str) -> None:
        self._connection = sqlite3.connect(Path(path))
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                timestamp TEXT NOT NULL, severity TEXT NOT NULL,
                component TEXT NOT NULL, occurrences INTEGER NOT NULL,
                payload TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    def save(self, alert: Alert) -> None:
        payload = json.dumps(alert.model_dump(mode="json"), ensure_ascii=False)
        self._connection.execute(
            """INSERT OR REPLACE INTO alerts
            (event_id, fingerprint, timestamp, severity, component, occurrences, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (alert.event_id, alert.fingerprint, alert.timestamp, alert.severity,
             alert.component, alert.occurrences, payload),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
