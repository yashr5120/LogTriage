"""Ollama API integration and deterministic rules-only fallback provider."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from logtriage.config import OllamaConfig
from logtriage.inference.base import BaseInferenceProvider, InferenceOutcome
from logtriage.inference.prompt import SYSTEM_PROMPT, build_triage_prompt
from logtriage.inference.validator import ValidationException, validate_model_response
from logtriage.models import AnalysisResult, ErrorContext

logger = logging.getLogger("logtriage.inference")


class RulesFallbackProvider(BaseInferenceProvider):
    """Deterministic, rules-based triage provider requiring no external AI service."""

    def __init__(self, model_name: str = "rules-engine-v1") -> None:
        self.model_name = model_name

    def analyze(self, context: ErrorContext, occurrences: int) -> InferenceOutcome:
        start_t = time.perf_counter()
        del occurrences
        init_rec = context.initial_record
        msg = init_rec.message.strip()
        sev = init_rec.normalized_severity
        comp = init_rec.component

        category = "unknown"
        lower_msg = msg.lower()
        lower_ctx = context.get_full_context_text().lower()

        if (
            "connection refused" in lower_ctx
            or "cannot connect" in lower_ctx
            or "timeout" in lower_ctx
        ):
            category = "connectivity"
            summary = f"Service failed to establish a network or database connection ({comp})."
        elif "outofmemory" in lower_ctx or "oom" in lower_ctx or "memory" in lower_ctx:
            category = "memory"
            summary = "The process encountered an out-of-memory condition."
        elif (
            "authentication" in lower_ctx
            or "login" in lower_ctx
            or "permission" in lower_ctx
            or "unauthorized" in lower_ctx
        ):
            category = "authentication"
            summary = "Authentication or permission check failed for the requested operation."
        elif "disk" in lower_ctx or "space" in lower_ctx or "filesystem" in lower_ctx:
            category = "storage"
            summary = "Storage or filesystem operation failed due to insufficient space or I/O error."
        elif context.is_traceback or "traceback" in lower_ctx:
            category = "crash"
            exc = context.exception_type or "UnhandledException"
            summary = f"Unhandled {exc} resulted in an application crash."
        elif "syntax" in lower_msg or "parse" in lower_msg:
            category = "syntax"
            summary = "Encountered a syntax or serialization error while processing payload."
        else:
            category = "system"
            clean_msg = re.sub(r"\s+", " ", msg)
            if len(clean_msg) > 100:
                clean_msg = clean_msg[:97] + "..."
            summary = f"Diagnostic event observed: {clean_msg}"

        # Ensure summary is a single concise sentence
        if not summary.endswith("."):
            summary += "."

        latency_ms = (time.perf_counter() - start_t) * 1000.0

        res = AnalysisResult(
            severity=sev,
            component=comp,
            summary=summary,
            category=category,
            confidence=None,  # Do not invent confidence in rules fallback
        )
        return InferenceOutcome(
            result=res,
            status="rules_only",
            source="rules_fallback",
            model_name=self.model_name,
            latency_ms=round(latency_ms, 2),
        )

    def check_health(self) -> Tuple[bool, str, Dict[str, Any]]:
        return True, "Rules fallback engine is active and operational.", {"provider": "rules"}


class OllamaProvider(BaseInferenceProvider):
    """Local Gemma LLM provider communicating with local Ollama daemon."""

    def __init__(self, config: OllamaConfig) -> None:
        self.host = config.host.rstrip("/")
        self.model_name = config.model
        self.timeout = config.timeout_seconds
        self.max_retries = config.max_retries
        self.backoff_factor = config.backoff_factor
        self.fallback_engine = RulesFallbackProvider(model_name=f"{self.model_name}-fallback")

    def check_health(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify Ollama connectivity and model availability."""
        url = f"{self.host}/api/tags"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LogTriage-Doctor/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status != 200:
                    return False, f"Ollama HTTP {resp.status}", {}
                payload = json.loads(resp.read().decode("utf-8"))

            models = payload.get("models", [])
            installed_names = [m.get("name") for m in models if isinstance(m, dict)]

            matching_model = None
            for m in models:
                if m.get("name") == self.model_name or m.get("model") == self.model_name:
                    matching_model = m
                    break

            if matching_model:
                details = matching_model.get("details", {})
                quant = details.get("quantization_level", "unknown")
                family = details.get("family", "unknown")
                size_bytes = matching_model.get("size", 0)
                size_gb = round(size_bytes / (1024**3), 2)
                return True, f"Ollama is online. Model '{self.model_name}' available ({quant}, {size_gb} GB).", {
                    "installed": True,
                    "model": self.model_name,
                    "quantization": quant,
                    "family": family,
                    "size_gb": size_gb,
                    "all_installed_models": installed_names,
                }
            else:
                return False, f"Ollama is running, but model '{self.model_name}' is not found.", {
                    "installed": False,
                    "configured_model": self.model_name,
                    "all_installed_models": installed_names,
                }

        except Exception as exc:
            return False, f"Failed to connect to Ollama at {self.host}: {exc}", {
                "error": str(exc),
                "host": self.host,
            }

    def analyze(self, context: ErrorContext, occurrences: int) -> InferenceOutcome:
        """Execute local inference with timeout, retry backoff, and validation."""
        start_t = time.perf_counter()
        prompt = build_triage_prompt(context, occurrences)
        url = f"{self.host}/api/generate"

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 256,
            },
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        last_error: Optional[str] = None
        raw_output: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                sleep_sec = self.backoff_factor ** attempt
                time.sleep(sleep_sec)

            try:
                req = urllib.request.Request(
                    url,
                    data=body_bytes,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    if response.status == 200:
                        resp_data = json.loads(response.read().decode("utf-8"))
                        raw_output = resp_data.get("response", "")
                        break
                    else:
                        last_error = f"HTTP {response.status}"
            except urllib.error.HTTPError as http_err:
                last_error = f"HTTP {http_err.code}: {http_err.reason}"
            except urllib.error.URLError as url_err:
                last_error = f"URLError: {url_err.reason}"
            except TimeoutError:
                last_error = "Inference request timed out"
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"

        latency_ms = (time.perf_counter() - start_t) * 1000.0

        # Attempt schema validation if we received a response
        if raw_output:
            try:
                res = validate_model_response(
                    raw_output, context.initial_record.normalized_severity
                )
                return InferenceOutcome(
                    result=res,
                    status="analyzed",
                    source="ollama",
                    model_name=self.model_name,
                    latency_ms=round(latency_ms, 2),
                    raw_response=raw_output,
                )
            except ValidationException as val_exc:
                logger.warning(
                    "Model response failed validation: %s. Emitting rules fallback.", val_exc
                )
                last_error = f"Validation failed: {val_exc}"

        # If inference or validation failed, fall back safely
        logger.warning(
            "Ollama inference unavailable or failed (%s). Using rules-only fallback.",
            last_error,
        )
        fb_outcome = self.fallback_engine.analyze(context, occurrences)
        return InferenceOutcome(
            result=fb_outcome.result,
            status="inference_failed" if raw_output is not None else "rules_only",
            source="rules_fallback",
            model_name=self.model_name,
            latency_ms=round(latency_ms, 2),
            raw_response=raw_output,
            error_message=last_error,
        )
