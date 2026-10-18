"""Command-line interface for Smart Local Log & Error Triage Engine."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from logtriage.alerts.outputs import ConsoleOutput, JsonlOutput
from logtriage.alerts.storage import AlertStore
from logtriage.config import AppConfig
from logtriage.demo import SCENARIOS, generate_logs
from logtriage.inference.ollama import OllamaProvider, RulesFallbackProvider
from logtriage.ingestion.sources import FileSource, StdinSource, follow_file
from logtriage.pipeline import TriagePipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logtriage")
    parser.add_argument("--config", default=None)
    parser.add_argument("--rules-only", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "follow"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--input", default="-")
        cmd.add_argument("--rules-only", action="store_true")
        cmd.add_argument("--output", choices=("console", "jsonl"), default=None)
        cmd.add_argument("--output-file", default=None)
        cmd.add_argument("--sqlite", default=None)
    demo = sub.add_parser("demo")
    demo.add_argument("--scenario", choices=tuple(SCENARIOS), default="database-failure")
    demo.add_argument("--repeat", type=int, default=1)
    demo.add_argument("--output", choices=("console", "jsonl"), default="console")
    demo.add_argument("--output-file", default=None)
    sub.add_parser("doctor")
    sub.add_parser("validate-config")
    bench = sub.add_parser("benchmark")
    bench.add_argument("--scenario", choices=tuple(SCENARIOS), default="database-failure")
    bench.add_argument("--repeat", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AppConfig.load(args.config)
    logging.basicConfig(level=config.log_level, stream=sys.stderr)
    if args.command == "validate-config":
        print(config.model_dump_json(indent=2))
        return 0
    if args.command == "doctor":
        ok, message, details = OllamaProvider(config.ollama).check_health()
        print(json.dumps({"ollama": message, "details": details}, indent=2))
        return 0 if ok else 1
    if args.command == "benchmark":
        return _benchmark(config, args)
    provider = RulesFallbackProvider() if (
        args.rules_only or getattr(args, "rules_only", False) or args.command == "demo"
    ) else OllamaProvider(config.ollama)
    output_name = getattr(args, "output", None) or config.output.format
    output = (
        JsonlOutput(file_path=getattr(args, "output_file", None) or config.output.file_path)
        if output_name == "jsonl"
        else ConsoleOutput()
    )
    store_path = getattr(args, "sqlite", None) or config.output.sqlite_path
    store = AlertStore(store_path) if store_path else None
    pipeline = TriagePipeline(config, provider, output, store)
    try:
        if args.command == "demo":
            lines = generate_logs(args.scenario, args.repeat)
        elif args.command == "follow":
            lines = follow_file(args.input, config.aggregator.poll_interval_seconds)
        elif args.input == "-":
            lines = StdinSource()
        else:
            lines = FileSource(args.input)
        pipeline.process_lines(lines)
    except KeyboardInterrupt:
        return 130
    finally:
        pipeline.close()
    return 0


def _benchmark(config: AppConfig, args: argparse.Namespace) -> int:
    lines = list(generate_logs(args.scenario, args.repeat))
    started = time.perf_counter()
    pipeline = TriagePipeline(config, RulesFallbackProvider(), ConsoleOutput())
    try:
        pipeline.process_lines(lines)
        summary = pipeline.metrics.get_summary()
    finally:
        pipeline.close()
    summary.update({"scenario": args.scenario, "sample_size": len(lines),
                    "elapsed_processing_seconds": time.perf_counter() - started})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
