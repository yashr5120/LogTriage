"""Base interface and outcome types for inference providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel

from logtriage.models import AnalysisResult, ErrorContext


class InferenceOutcome(BaseModel):
    """Encapsulates the complete result of an inference or fallback invocation."""

    result: AnalysisResult
    status: str  # "analyzed", "rules_only", "inference_failed"
    source: str  # "ollama", "rules_fallback"
    model_name: str
    latency_ms: Optional[float] = None
    raw_response: Optional[str] = None
    error_message: Optional[str] = None


class BaseInferenceProvider(ABC):
    """Abstract base class for diagnostic inference engines."""

    @abstractmethod
    def analyze(self, context: ErrorContext, occurrences: int) -> InferenceOutcome:
        """Analyze an error context and return structured diagnostics."""
        pass

    @abstractmethod
    def check_health(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify provider availability and return status, message, and metadata."""
        pass
