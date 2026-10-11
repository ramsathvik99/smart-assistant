"""
Smart Assistant — Privacy-Preserving Admin Metrics & Health Monitor
Provides system observability, database health, API latency, and service metrics
WITHOUT exposing any user private conversations or memory contents.
"""

import time
import psutil
import threading
from typing import Dict, Any, List
from collections import deque

from core.db_pool import get_db_pool

class AdminMetricsTracker:
    """
    In-memory and aggregated metrics collector.
    Strictly sanitizes data to prevent user privacy leakage.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AdminMetricsTracker, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._start_time = time.time()
        self._request_count = 0
        self._error_count = 0
        self._endpoint_counts: Dict[str, int] = {}
        self._latencies: deque = deque(maxlen=1000)
        self._active_sessions = set()
        self._metrics_lock = threading.Lock()
        self._initialized = True

    def record_request(self, endpoint: str, duration_ms: float, status_code: int, user_id: int = None):
        """Record an API request metric."""
        with self._metrics_lock:
            self._request_count += 1
            self._endpoint_counts[endpoint] = self._endpoint_counts.get(endpoint, 0) + 1
            self._latencies.append(duration_ms)
            if status_code >= 400:
                self._error_count += 1
            if user_id:
                self._active_sessions.add(int(user_id))

    def get_system_health(self) -> Dict[str, Any]:
        """Returns non-sensitive system health status."""
        pool = get_db_pool()
        db_healthy = pool.is_healthy()
        pool_stats = pool.get_stats()

        # System resource usage
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        with self._metrics_lock:
            total_reqs = self._request_count
            total_errors = self._error_count
            avg_latency = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.0
            p95_latency = sorted(self._latencies)[int(len(self._latencies) * 0.95)] if self._latencies else 0.0
            error_rate = round((total_errors / total_reqs * 100.0) if total_reqs > 0 else 0.0, 2)
            active_users_count = len(self._active_sessions)
            endpoint_stats = dict(self._endpoint_counts)

        # Database statistics (row counts only, no private text)
        db_summary = {
            "connected": db_healthy,
            "pool": pool_stats,
            "registered_users": 0,
            "total_memories": 0,
            "total_conversations": 0
        }

        if db_healthy:
            try:
                with pool.get_cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM users")
                    db_summary["registered_users"] = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM memory_facts")
                    db_summary["total_memories"] = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM conversations")
                    db_summary["total_conversations"] = cur.fetchone()[0]
            except Exception:
                pass

        return {
            "status": "healthy" if db_healthy and error_rate < 15.0 else "degraded",
            "uptime_seconds": round(time.time() - self._start_time, 2),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "server": {
                "cpu_percent": cpu_pct,
                "memory_percent": mem.percent,
                "memory_available_mb": round(mem.available / (1024 * 1024), 2)
            },
            "api_metrics": {
                "total_requests": total_reqs,
                "total_errors": total_errors,
                "error_rate_percent": error_rate,
                "avg_latency_ms": round(avg_latency, 2),
                "p95_latency_ms": round(p95_latency, 2),
                "active_unique_users": active_users_count,
                "popular_endpoints": endpoint_stats
            },
            "database": db_summary
        }


# Global singleton
_metrics_tracker = AdminMetricsTracker()

def get_admin_metrics() -> AdminMetricsTracker:
    return _metrics_tracker
