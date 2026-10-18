"""Smart Local Log & Error Triage Engine.

An offline-first, edge-capable background service that continuously ingests system
and application logs, detects critical failures, groups repeated errors,
isolates relevant stack traces, and uses a locally hosted Gemma model through Ollama
to generate concise diagnostic alerts.
"""

__version__ = "0.1.0"
