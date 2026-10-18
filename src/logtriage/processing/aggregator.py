"""Sliding-window deduplication, event grouping, and priority dispatch."""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from logtriage.config import AggregatorConfig
from logtriage.models import ErrorContext, GroupedEvent
from logtriage.processing.fingerprint import LogFingerprinter


class SlidingWindowAggregator:
    """Bounded, sliding-window event aggregator with cooldown and escalation alerts."""

    def __init__(self, config: AggregatorConfig) -> None:
        self.sliding_window = config.sliding_window_seconds
        self.cooldown = config.cooldown_seconds
        self.max_groups = config.max_groups

        # LRU cache: fingerprint -> GroupedEvent
        self._groups: OrderedDict[str, GroupedEvent] = OrderedDict()
        # Track epoch timestamp when group was last updated: fingerprint -> float
        self._group_last_update: Dict[str, float] = {}

    def ingest_context(
        self, context: ErrorContext, now: Optional[float] = None
    ) -> Tuple[GroupedEvent, bool, bool]:
        """Ingest an ErrorContext.

        Returns:
            Tuple of:
            - grouped_event: The GroupedEvent instance
            - is_new_group: True if this is the first observation of this fingerprint
            - should_alert: True if an alert should be emitted immediately (first seen, escalation, or cooldown passed)
        """
        current_time = now if now is not None else time.time()
        self._evict_expired(current_time)

        fp = LogFingerprinter.compute_fingerprint(context)
        iso_now = datetime.now(timezone.utc).isoformat()

        if fp in self._groups:
            # Update existing group
            group = self._groups[fp]
            self._groups.move_to_end(fp)
            self._group_last_update[fp] = current_time

            group.occurrences += 1
            group.last_seen = iso_now
            group.latest_context = context

            # Check severity escalation
            escalated = False
            incoming_sev = context.initial_record.normalized_severity
            if incoming_sev > group.highest_severity:
                group.highest_severity = incoming_sev
                escalated = True

            # Check alert cooldown
            time_since_alert = (
                (current_time - group.last_alert_time)
                if group.last_alert_time is not None
                else float("inf")
            )

            # Trigger alert if escalated OR cooldown has elapsed
            should_alert = False
            if escalated:
                should_alert = True
            elif time_since_alert >= self.cooldown:
                should_alert = True

            if should_alert:
                group.last_alert_time = current_time
                group.last_alert_occurrences = group.occurrences

            return group, False, should_alert

        # First occurrence creates a new group
        if len(self._groups) >= self.max_groups:
            # Evict oldest group (LRU policy to guarantee bounded memory)
            oldest_fp, _ = self._groups.popitem(last=False)
            self._group_last_update.pop(oldest_fp, None)

        new_group = GroupedEvent(
            fingerprint=fp,
            first_seen=iso_now,
            last_seen=iso_now,
            occurrences=1,
            representative_context=context,
            latest_context=context,
            highest_severity=context.initial_record.normalized_severity,
            successful_analyses=0,
            last_alert_time=current_time,
            last_alert_occurrences=1,
            processing_status="pending",
        )
        self._groups[fp] = new_group
        self._group_last_update[fp] = current_time

        return new_group, True, True

    def _evict_expired(self, current_time: float) -> None:
        """Evict groups whose sliding window has passed without activity."""
        expired_fps: List[str] = []
        for fp, last_update in self._group_last_update.items():
            if current_time - last_update > self.sliding_window:
                expired_fps.append(fp)

        for fp in expired_fps:
            self._groups.pop(fp, None)
            self._group_last_update.pop(fp, None)

    def get_group(self, fingerprint: str) -> Optional[GroupedEvent]:
        """Retrieve an active group by fingerprint."""
        return self._groups.get(fingerprint)

    def get_all_groups(self) -> List[GroupedEvent]:
        """Return all active groups."""
        return list(self._groups.values())
