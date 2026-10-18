"""Compatibility helpers for serializing canonical alerts."""

from __future__ import annotations

import json

from logtriage.models import Alert


def alert_to_json(alert: Alert) -> str:
    return json.dumps(alert.model_dump(mode="json"), ensure_ascii=False)


def alert_to_dict(alert: Alert) -> dict[str, object]:
    return alert.model_dump(mode="json")
