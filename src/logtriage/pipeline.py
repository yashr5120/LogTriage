"""End-to-end rules-first log triage pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from logtriage.alerts.outputs import AlertOutput
from logtriage.alerts.storage import AlertStore
from logtriage.config import AppConfig
from logtriage.inference.base import BaseInferenceProvider
from logtriage.metrics import MetricsCollector
from logtriage.models import Alert, ErrorContext
from logtriage.processing.aggregator import SlidingWindowAggregator
from logtriage.processing.filters import SeverityFilter
from logtriage.processing.parser import LogParser
from logtriage.processing.traceback import TracebackAssembler
from logtriage.redaction import Redactor

logger = logging.getLogger("logtriage.pipeline")


class TriagePipeline:
    def __init__(
        self,
        config: AppConfig,
        provider: BaseInferenceProvider,
        output: AlertOutput,
        store: AlertStore | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self.config = config
        self.parser = LogParser(config.aggregator.max_line_length)
        self.filter = SeverityFilter(config.rules)
        self.assembler = TracebackAssembler(config.aggregator)
        self.aggregator = SlidingWindowAggregator(config.aggregator)
        self.provider = provider
        self.output = output
        self.store = store
        self.metrics = metrics or MetricsCollector()
        self.redactor = Redactor(config.redaction)
        self._line_number = 0

    def process_lines(self, lines: Iterable[str]) -> int:
        emitted = 0
        for line in lines:
            self._line_number += 1
            self.metrics.record_ingested()
            record = self.filter.classify_and_filter(
                self.parser.parse_line(line.rstrip("\r\n"), self._line_number)
            )
            if not record.is_error_candidate:
                self.metrics.record_filtered()
            else:
                self.metrics.record_candidate_error()
            for context in self.assembler.process_record(record):
                emitted += self._process_context(context)
        for context in self.assembler.flush():
            emitted += self._process_context(context)
        return emitted

    def _process_context(self, context: ErrorContext) -> int:
        context = context.model_copy(update={
            "lines": self.redactor.redact_lines(context.lines),
        })
        group, is_new, should_alert = self.aggregator.ingest_context(context)
        self.metrics.record_group_update(is_new)
        if not should_alert:
            return 0
        self.metrics.record_inference_attempt()
        outcome = self.provider.analyze(group.latest_context, group.occurrences)
        self.metrics.record_inference_result(outcome.status == "analyzed", outcome.latency_ms)
        result = outcome.result
        group.successful_analyses += outcome.status == "analyzed"
        group.processing_status = outcome.status
        alert = Alert(
            event_id=context.event_id,
            fingerprint=group.fingerprint,
            timestamp=_utc_now(),
            first_seen=group.first_seen,
            last_seen=group.last_seen,
            severity=max(group.highest_severity, result.severity).value,
            component=result.component,
            summary=result.summary,
            category=result.category,
            confidence=result.confidence,
            occurrences=group.occurrences,
            status=outcome.status,
            analysis_source=outcome.source,
            model=outcome.model_name,
            inference_latency_ms=outcome.latency_ms,
            context_sample=context.lines,
        )
        self.output.emit(alert)
        if self.store:
            self.store.save(alert)
        self.metrics.record_alert_emitted()
        return 1

    def close(self) -> None:
        self.output.close()
        if self.store:
            self.store.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
