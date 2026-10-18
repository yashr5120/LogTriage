"""Configuration management with YAML loading, environment overrides, and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class OllamaConfig(BaseModel):
    """Configuration for local Ollama LLM provider."""

    host: str = "http://127.0.0.1:11434"
    model: str = "gemma2:2b"
    timeout_seconds: float = 15.0
    max_retries: int = 2
    backoff_factor: float = 1.5
    max_concurrent_requests: int = 1


class RulesConfig(BaseModel):
    """Regex pattern configurations for severity classification and filtering."""

    critical_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(fatal|critical|panic|segmentation fault|outofmemoryerror)\b",
            r"(?i)\bcore dumped\b",
        ]
    )
    high_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(error|unhandledexception|unhandled exception|connection refused)\b",
            r"(?i)traceback \(most recent call last\):",
            r"(?i)\bexception\b",
        ]
    )
    medium_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(warn|warning|timeout|timed out|retry attempt)\b",
        ]
    )
    low_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(notice|deprecated|debug)\b",
        ]
    )
    ignore_patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)\b0 errors found\b",
            r"(?i)\berror_code: 0\b",
            r"(?i)\bno errors reported\b",
            r"(?i)\berrors?: none\b",
        ]
    )


class AggregatorConfig(BaseModel):
    """Configuration for sliding-window deduplication and context limits."""

    sliding_window_seconds: float = 30.0
    cooldown_seconds: float = 60.0
    max_groups: int = 5000
    max_queue_size: int = 1000
    max_context_lines: int = 20
    max_token_budget: int = 512
    inactivity_timeout_seconds: float = 2.0
    worker_count: int = 1
    poll_interval_seconds: float = 0.25
    max_line_length: int = 10000


class RedactionConfig(BaseModel):
    """Configuration for credential and sensitive data sanitization."""

    enabled: bool = True
    mask: str = "[REDACTED]"
    patterns: List[str] = Field(
        default_factory=lambda: [
            r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+",
            r"(?i)(password|passwd|secret|api_key|apikey|access_token|private_key)[\s]*[:=][\s]*['\"]?[^'\"\s,;]+",
            r"(?i)postgres(?:ql)?://[^:]+:[^@]+@",
            r"(?i)mongodb(?:\+srv)?://[^:]+:[^@]+@",
            r"(?i)mysql://[^:]+:[^@]+@",
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
            r"\b[A-Za-z0-9+/]{40,}={0,2}\b",  # Generic base64 token/key
        ]
    )


class OutputConfig(BaseModel):
    """Alert destination and format settings."""

    format: str = "console"  # "console" or "jsonl"
    file_path: Optional[str] = None
    sqlite_path: Optional[str] = None


class AppConfig(BaseModel):
    """Root configuration model combining all subsystems."""

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    aggregator: AggregatorConfig = Field(default_factory=AggregatorConfig)
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    log_level: str = "INFO"

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> "AppConfig":
        """Load configuration with precedence: overrides > env vars > yaml file > defaults."""
        data: Dict[str, Any] = {}

        # 1. Load YAML file if provided or if standard locations exist
        target_path: Optional[Path] = None
        if config_path and Path(config_path).is_file():
            target_path = Path(config_path)
        elif Path("config/config.yaml").is_file():
            target_path = Path("config/config.yaml")

        if target_path and target_path.is_file():
            with open(target_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data = loaded

        # 2. Apply environment variable overrides (LOGTRIAGE_*)
        if "LOGTRIAGE_OLLAMA_HOST" in os.environ:
            data.setdefault("ollama", {})["host"] = os.environ["LOGTRIAGE_OLLAMA_HOST"]
        if "LOGTRIAGE_OLLAMA_MODEL" in os.environ:
            data.setdefault("ollama", {})["model"] = os.environ["LOGTRIAGE_OLLAMA_MODEL"]
        if "LOGTRIAGE_OLLAMA_TIMEOUT_SECONDS" in os.environ:
            data.setdefault("ollama", {})["timeout_seconds"] = float(
                os.environ["LOGTRIAGE_OLLAMA_TIMEOUT_SECONDS"]
            )
        if "LOGTRIAGE_SLIDING_WINDOW_SECONDS" in os.environ:
            data.setdefault("aggregator", {})["sliding_window_seconds"] = float(
                os.environ["LOGTRIAGE_SLIDING_WINDOW_SECONDS"]
            )
        if "LOGTRIAGE_COOLDOWN_SECONDS" in os.environ:
            data.setdefault("aggregator", {})["cooldown_seconds"] = float(
                os.environ["LOGTRIAGE_COOLDOWN_SECONDS"]
            )
        if "LOGTRIAGE_MAX_GROUPS" in os.environ:
            data.setdefault("aggregator", {})["max_groups"] = int(
                os.environ["LOGTRIAGE_MAX_GROUPS"]
            )
        if "LOGTRIAGE_MAX_QUEUE_SIZE" in os.environ:
            data.setdefault("aggregator", {})["max_queue_size"] = int(
                os.environ["LOGTRIAGE_MAX_QUEUE_SIZE"]
            )
        if "LOGTRIAGE_OUTPUT_FORMAT" in os.environ:
            data.setdefault("output", {})["format"] = os.environ["LOGTRIAGE_OUTPUT_FORMAT"]
        if "LOGTRIAGE_STORAGE_PATH" in os.environ:
            data.setdefault("output", {})["sqlite_path"] = os.environ["LOGTRIAGE_STORAGE_PATH"]
        if "LOGTRIAGE_LOG_LEVEL" in os.environ:
            data["log_level"] = os.environ["LOGTRIAGE_LOG_LEVEL"]
        if "LOGTRIAGE_REDACTION_ENABLED" in os.environ:
            val = os.environ["LOGTRIAGE_REDACTION_ENABLED"].strip().lower()
            data.setdefault("redaction", {})["enabled"] = val in ("1", "true", "yes")

        # 3. Apply explicit programmatic overrides
        if overrides:
            for k, v in overrides.items():
                if isinstance(v, dict) and k in data and isinstance(data[k], dict):
                    data[k].update(v)
                else:
                    data[k] = v

        return cls.model_validate(data)
