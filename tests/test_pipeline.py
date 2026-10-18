from __future__ import annotations

import io
import json

from logtriage.alerts.outputs import JsonlOutput
from logtriage.config import AppConfig
from logtriage.demo import generate_logs
from logtriage.inference.ollama import RulesFallbackProvider
from logtriage.pipeline import TriagePipeline


def test_rules_only_pipeline_groups_repeated_errors() -> None:
    stream = io.StringIO()
    config = AppConfig.load(overrides={"aggregator": {"cooldown_seconds": 999}})
    pipeline = TriagePipeline(config, RulesFallbackProvider(), JsonlOutput(stream=stream))
    try:
        assert pipeline.process_lines(generate_logs("database-failure", repeat=3)) == 2
    finally:
        pipeline.close()
    alerts = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert alerts[0]["occurrences"] == 1
    assert alerts[0]["category"] == "connectivity"
    assert alerts[0]["severity"] == "CRITICAL" or alerts[1]["severity"] == "CRITICAL"


def test_startup_info_does_not_emit_alert() -> None:
    stream = io.StringIO()
    pipeline = TriagePipeline(AppConfig(), RulesFallbackProvider(), JsonlOutput(stream=stream))
    try:
        assert pipeline.process_lines(generate_logs("startup")) == 0
    finally:
        pipeline.close()
    assert stream.getvalue() == ""
