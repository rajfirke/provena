"""Async batch write buffer for high-throughput trail logging."""

from __future__ import annotations

import atexit
import contextlib
import signal
import threading
import weakref
from collections import deque
from typing import Any, Protocol


class _Appendable(Protocol):
    def append(self, record: dict[str, Any]) -> int: ...


class WriteBuffer:
    """Thread-safe write buffer that batches storage backend writes.

    Records are appended to an in-memory deque (sub-microsecond) and
    flushed to the storage backend periodically by a background daemon
    thread or when the buffer reaches capacity.
    """

    def __init__(
        self,
        backend: _Appendable,
        buffer_size: int = 500,
        flush_interval: float = 1.0,
    ) -> None:
        self._backend = backend
        self._buffer: deque[dict[str, Any]] = deque()
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="provena-buffer"
        )
        self._thread.start()

        atexit.register(self._atexit_flush)
        self._finalizer = weakref.finalize(
            self, _weak_flush, self._buffer, self._lock, self._backend
        )

        with contextlib.suppress(OSError, ValueError):
            signal.signal(signal.SIGTERM, self._sigterm_handler)

    @property
    def pending(self) -> int:
        """Number of records waiting to be flushed."""
        return len(self._buffer)

    def append(self, record: dict[str, Any]) -> None:
        """Append a record to the buffer. Triggers flush if buffer is full."""
        with self._lock:
            self._buffer.append(record)
            if len(self._buffer) >= self._buffer_size:
                self._flush_locked()

    def flush(self) -> int:
        """Flush all buffered records to the backend. Returns count flushed."""
        with self._lock:
            return self._flush_locked()

    def close(self) -> None:
        """Stop the background thread and flush remaining records."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._lock:
            self._flush_locked()

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=self._flush_interval)
            with self._lock:
                self._flush_locked()

    def _flush_locked(self) -> int:
        """Flush while holding self._lock. Returns count flushed."""
        count = 0
        while self._buffer:
            record = self._buffer.popleft()
            self._backend.append(record)
            count += 1
        return count

    def _atexit_flush(self) -> None:
        self._stop.set()
        with self._lock:
            self._flush_locked()

    def _sigterm_handler(self, signum: int, frame: Any) -> None:
        self._stop.set()
        with self._lock:
            self._flush_locked()


def _weak_flush(
    buffer: deque[dict[str, Any]],
    lock: threading.Lock,
    backend: _Appendable,
) -> None:
    """Last-resort flush via weakref.finalize."""
    with lock:
        while buffer:
            record = buffer.popleft()
            backend.append(record)
