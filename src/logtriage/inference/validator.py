"""Strict schema validation and safe recovery for model responses."""

from __future__ import annotations

import json
import re
from typing import Optional

from logtriage.models import AnalysisResult, SeverityLevel


class ValidationException(Exception):
    """Raised when model response cannot be validated or safely repaired."""
    pass


def extract_json_block(text: str) -> str:
    """Extract JSON object from markdown fences or bracket boundaries."""
    # Look for ```json ... ```
    m_fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if m_fence:
        return m_fence.group(1).strip()

    # Look for raw outer braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()

    return text.strip()


def validate_model_response(
    raw_response: str, initial_severity: SeverityLevel
) -> AnalysisResult:
    """Validate and sanitize JSON response from LLM according to strict schema."""
    if not raw_response or not raw_response.strip():
        raise ValidationException("Model returned an empty response")

    json_text = extract_json_block(raw_response)

    try:
        data = json.loads(json_text)
    except Exception as exc:
        raise ValidationException(f"Invalid JSON in model response: {exc}") from exc

    if not isinstance(data, dict):
        raise ValidationException("Model response is not a JSON object")

    # 1. Mandatory fields
    for field in ("severity", "component", "summary", "category"):
        if field not in data or data[field] is None:
            raise ValidationException(f"Missing mandatory field '{field}' in model response")

    # 2. Validate severity
    raw_sev = str(data["severity"]).strip().upper()
    try:
        sev = SeverityLevel[raw_sev]
    except KeyError as exc:
        raise ValidationException(f"Unsupported severity value: {raw_sev}") from exc

    # Enforce rule: LLM cannot silently downgrade an explicitly critical event
    if initial_severity == SeverityLevel.CRITICAL and sev < SeverityLevel.CRITICAL:
        sev = SeverityLevel.CRITICAL

    # 3. Component length and content
    comp = str(data["component"]).strip()
    if not comp or len(comp) > 64:
        comp = comp[:64] if comp else "unknown"

    # 4. Summary length and structure
    summary = str(data["summary"]).strip()
    if not summary:
        raise ValidationException("Summary field is empty")
    if len(summary) > 300:
        summary = summary[:297] + "..."
    # Ensure one sentence: if multiple sentences, take the first sentence
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    if sentences:
        summary = sentences[0]

    # 5. Category
    cat = str(data["category"]).strip().lower()
    if not cat or len(cat) > 64:
        cat = "unknown"

    # 6. Confidence (optional float 0.0 to 1.0)
    confidence: Optional[float] = None
    if "confidence" in data and data["confidence"] is not None:
        try:
            val = float(data["confidence"])
            if 0.0 <= val <= 1.0:
                confidence = round(val, 2)
        except (ValueError, TypeError):
            confidence = None

    return AnalysisResult(
        severity=sev,
        component=comp,
        summary=summary,
        category=cat,
        confidence=confidence,
    )
