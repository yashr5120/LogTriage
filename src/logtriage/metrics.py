"""Thread-safe telemetry and metrics collection for the triage pipeline."""

from __future__ import annotations

import platform
import sys
import threading
import time
from typing import Any, Dict, List, Optional


class MetricsCollector:
    """Thread-safe metrics aggregator for log processing and inference operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.start_time: float = time.time()
        self.lines_ingested: int = 0
        self.lines_filtered: int = 0
        self.candidate_error_lines: int = 0
        self.unique_fingerprints: int = 0
        self.duplicate_occurrences: int = 0
        self.alerts_emitted: int = 0
        self.inference_attempts: int = 0
        self.inference_successes: int = 0
        self.inference_failures: int = 0
        self.inference_latencies_ms: List[float] = []
        self.queue_overflows: int = 0
        self.current_queue_depth: int = 0

    def record_ingested(self, count: int = 1) -> None:
        with self._lock:
            self.lines_ingested += count

    def record_filtered(self, count: int = 1) -> None:
        with self._lock:
            self.lines_filtered += count

    def record_candidate_error(self, count: int = 1) -> None:
        with self._lock:
            self.candidate_error_lines += count

    def record_group_update(self, is_new: bool, count: int = 1) -> None:
        with self._lock:
            if is_new:
                self.unique_fingerprints += 1
            else:
                self.duplicate_occurrences += count

    def record_alert_emitted(self, count: int = 1) -> None:
        with self._lock:
            self.alerts_emitted += count

    def record_inference_attempt(self) -> None:
        with self._lock:
            self.inference_attempts += 1

    def record_inference_result(self, success: bool, latency_ms: Optional[float] = None) -> None:
        with self._lock:
            if success:
                self.inference_successes += 1
            else:
                self.inference_failures += 1
            if latency_ms is not None:
                self.inference_latencies_ms.append(latency_ms)

    def record_queue_depth(self, depth: int) -> None:
        with self._lock:
            self.current_queue_depth = depth

    def record_queue_overflow(self, count: int = 1) -> None:
        with self._lock:
            self.queue_overflows += count

    def get_summary(self) -> Dict[str, Any]:
        """Compute summary statistics including percentiles and throughput."""
        with self._lock:
            elapsed = max(0.001, time.time() - self.start_time)
            throughput = self.lines_ingested / elapsed
            latencies = sorted(self.inference_latencies_ms)
            p50 = latencies[len(latencies) // 2] if latencies else 0.0
            p95_idx = int(len(latencies) * 0.95)
            p95 = latencies[p95_idx] if latencies else 0.0
            avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

            reduction_ratio = (
                (self.duplicate_occurrences / (self.lines_ingested or 1))
                if self.lines_ingested > 0
                else 0.0
            )

            return {
                "elapsed_seconds": round(elapsed, 2),
                "lines_ingested": self.lines_ingested,
                "lines_filtered": self.lines_filtered,
                "candidate_error_lines": self.candidate_error_lines,
                "unique_fingerprints": self.unique_fingerprints,
                "duplicate_occurrences": self.duplicate_occurrences,
                "duplicate_reduction_ratio": round(reduction_ratio, 4),
                "alerts_emitted": self.alerts_emitted,
                "throughput_lines_per_sec": round(throughput, 1),
                "inference_attempts": self.inference_attempts,
                "inference_successes": self.inference_successes,
                "inference_failures": self.inference_failures,
                "inference_latency_p50_ms": round(p50, 2),
                "inference_latency_p95_ms": round(p95, 2),
                "inference_latency_avg_ms": round(avg_lat, 2),
                "queue_overflows": self.queue_overflows,
                "current_queue_depth": self.current_queue_depth,
                "environment": {
                    "python_version": sys.version.split()[0],
                    "platform": platform.platform(),
                    "system": platform.system(),
                },
            }
