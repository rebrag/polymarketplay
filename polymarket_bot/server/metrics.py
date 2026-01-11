from __future__ import annotations

import os
import threading
import time
from typing import Optional

import requests

from polymarket_bot.config import CLOB_URL


class LatencyMonitor:
    def __init__(self, url: str, interval_s: float, timeout_s: float) -> None:
        self._url = url
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._latency_ms: Optional[float] = None
        self._status_code: Optional[int] = None
        self._error: Optional[str] = None
        self._updated_at: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pm_latency_monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._session.close()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "latency_ms": self._latency_ms,
                "status_code": self._status_code,
                "error": self._error,
                "updated_at": self._updated_at,
                "url": self._url,
            }

    def _loop(self) -> None:
        while not self._stop.is_set():
            start = time.perf_counter()
            status_code: Optional[int] = None
            error: Optional[str] = None
            try:
                resp = self._session.get(self._url, timeout=self._timeout_s)
                status_code = resp.status_code
                resp.close()
                latency_ms = (time.perf_counter() - start) * 1000.0
            except Exception as exc:
                latency_ms = None
                error = str(exc)
            now = time.time()
            with self._lock:
                self._latency_ms = latency_ms
                self._status_code = status_code
                self._error = error
                self._updated_at = now
            self._stop.wait(self._interval_s)


def _read_float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


latency_monitor = LatencyMonitor(
    url=os.getenv("POLY_LATENCY_URL", CLOB_URL),
    interval_s=_read_float_env("POLY_LATENCY_INTERVAL_S", 5.0),
    timeout_s=_read_float_env("POLY_LATENCY_TIMEOUT_S", 3.0),
)
