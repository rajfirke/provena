"""Async batch write buffer for high-throughput trail logging."""

from __future__ import annotations

import atexit
import contextlib
import logging
import signal
import threading
import weakref
from collections import deque
from typing import Any, Protocol

_logger = logging.getLogger("provena.buffer")
_active_buffers: weakref.WeakSet[WriteBuffer] = weakref.WeakSet()
_active_buffers_lock = threading.RLock()
_prev_sigterm_handler: Any = None


class _Appendable(Protocol):
    def append(self, record: dict[str, Any]) -> int: ...
    def all_records(self) -> list[dict[str, Any]]: ...


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
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._last_stored_chain_hash: str | None = None

        self._thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="provena-buffer"
        )
        self._thread.start()

        atexit.register(self._atexit_flush)
        self._finalizer = weakref.finalize(
            self, _weak_flush, self._buffer, self._lock, self._backend
        )
        _register_for_sigterm(self)

    @property
    def pending(self) -> int:
        """Number of records waiting to be flushed."""
        return len(self._buffer)

    def __len__(self) -> int:
        return self.pending

    @property
    def pending_records(self) -> list[dict[str, Any]]:
        """Snapshot of records waiting to be flushed."""
        with self._lock:
            return list(self._buffer)

    def full_snapshot(self) -> list[dict[str, Any]]:
        """Backend records plus pending records, as of one consistent instant.

        Holds this buffer's lock across both reads. The background flush
        thread can only move a record from the pending buffer into the
        backend while holding this same lock, so a caller using this method
        instead of separately reading ``backend.all_records()`` and
        ``pending_records`` can never observe a record in neither snapshot.
        """
        with self._lock:
            return self._backend.all_records() + list(self._buffer)

    def settled_tip(self) -> str | None:
        """Stored chain hash of the last flushed record, if nothing is pending.

        A backend may repair the link it stores: PostgreSQL holds an advisory
        lock and recomputes both hashes when the submitted ``previous_hash`` is
        no longer the tip. The caller computed its hash before the flush, so it
        has to learn the stored value or every later record chains off a hash
        the table does not hold.

        Returns ``None`` while records are still pending, because those are
        appended before the caller's next record and it should go on extending
        them rather than jumping back to the last stored row.
        """
        with self._lock:
            if self._buffer:
                return None
            return self._last_stored_chain_hash

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
        _unregister_for_sigterm(self)

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=self._flush_interval)
            with self._lock:
                self._flush_locked()

    def _flush_locked(self) -> int:
        """Flush while holding self._lock. Returns count flushed."""
        count, last_stored = _drain_buffer(self._buffer, self._backend)
        if last_stored is not None:
            self._last_stored_chain_hash = last_stored
        return count

    def _atexit_flush(self) -> None:
        self._stop.set()
        with self._lock:
            self._flush_locked()

    def _sigterm_flush(self) -> None:
        self._stop.set()
        with self._lock:
            self._flush_locked()


def _register_for_sigterm(buffer: WriteBuffer) -> None:
    global _prev_sigterm_handler
    with _active_buffers_lock:
        _active_buffers.add(buffer)
        with contextlib.suppress(OSError, ValueError):
            current = signal.getsignal(signal.SIGTERM)
            if current is not _sigterm_handler:
                _prev_sigterm_handler = current
                signal.signal(signal.SIGTERM, _sigterm_handler)


def _unregister_for_sigterm(buffer: WriteBuffer) -> None:
    with _active_buffers_lock:
        _active_buffers.discard(buffer)


def _sigterm_handler(signum: int, frame: Any) -> None:
    with _active_buffers_lock:
        buffers = tuple(_active_buffers)
    for buffer in buffers:
        buffer._sigterm_flush()
    if callable(_prev_sigterm_handler):
        _prev_sigterm_handler(signum, frame)
    elif _prev_sigterm_handler == signal.SIG_DFL:
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)


def _drain_buffer(
    buffer: deque[dict[str, Any]], backend: _Appendable
) -> tuple[int, str | None]:
    """Flush every record in buffer to backend, in insertion order.

    Stops and logs a warning on the first failure, leaving that record
    (and everything after it) in the buffer rather than dropping it.
    Caller must hold the buffer's lock. Returns the count flushed and the
    stored chain hash of the last record written, or ``None`` if none was.
    """
    count = 0
    last_stored: str | None = None
    while buffer:
        record = buffer[0]
        try:
            backend.append(record)
        except Exception:
            _logger.warning(
                "Failed to flush record (keeping in buffer, %d remaining)",
                len(buffer),
                exc_info=True,
            )
            break
        buffer.popleft()
        # append() writes the stored pair back onto the record, so this is
        # what the table holds, repaired or not. A record carrying no
        # chain_hash leaves the last known tip alone: there is nothing to
        # resync from, and the caller is not chaining these.
        stored = record.get("chain_hash")
        if stored is not None:
            last_stored = stored
        count += 1
    return count, last_stored


def _weak_flush(
    buffer: deque[dict[str, Any]],
    lock: threading.RLock,
    backend: _Appendable,
) -> None:
    """Last-resort flush via weakref.finalize.

    Takes buffer/lock/backend as plain arguments rather than a bound
    method, so the finalizer callback holds no reference to the
    WriteBuffer itself -- weakref.finalize requires that to let the
    object actually become collectible.
    """
    with lock:
        _drain_buffer(buffer, backend)
