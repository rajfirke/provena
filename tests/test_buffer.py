"""Tests for the async batch write buffer and buffered ContextTrail."""

from __future__ import annotations

import time

from provena import ContextTrail
from provena.buffer import WriteBuffer
from provena.storage import InMemoryBackend


class TestWriteBuffer:
    def test_append_and_flush(self):
        backend = InMemoryBackend()
        buf = WriteBuffer(backend, buffer_size=100, flush_interval=60)
        buf.append(
            {
                "content_hash": "a",
                "source": "r",
                "source_name": "t",
                "timestamp": "2026-07-20T00:00:00Z",
                "chain_hash": "c",
                "previous_hash": "p",
            }
        )
        assert buf.pending == 1
        assert backend.count() == 0
        count = buf.flush()
        assert count == 1
        assert backend.count() == 1
        assert buf.pending == 0
        buf.close()

    def test_auto_flush_on_buffer_full(self):
        backend = InMemoryBackend()
        buf = WriteBuffer(backend, buffer_size=3, flush_interval=60)
        for i in range(3):
            buf.append(
                {
                    "content_hash": f"h{i}",
                    "source": "r",
                    "source_name": "t",
                    "timestamp": "2026-07-20T00:00:00Z",
                    "chain_hash": f"c{i}",
                    "previous_hash": f"p{i}",
                }
            )
        assert backend.count() == 3
        assert buf.pending == 0
        buf.close()

    def test_close_flushes_remaining(self):
        backend = InMemoryBackend()
        buf = WriteBuffer(backend, buffer_size=100, flush_interval=60)
        for i in range(5):
            buf.append(
                {
                    "content_hash": f"h{i}",
                    "source": "r",
                    "source_name": "t",
                    "timestamp": "2026-07-20T00:00:00Z",
                    "chain_hash": f"c{i}",
                    "previous_hash": f"p{i}",
                }
            )
        assert backend.count() == 0
        buf.close()
        assert backend.count() == 5

    def test_periodic_flush(self):
        backend = InMemoryBackend()
        buf = WriteBuffer(backend, buffer_size=1000, flush_interval=0.1)
        buf.append(
            {
                "content_hash": "a",
                "source": "r",
                "source_name": "t",
                "timestamp": "2026-07-20T00:00:00Z",
                "chain_hash": "c",
                "previous_hash": "p",
            }
        )
        assert backend.count() == 0
        time.sleep(0.3)
        assert backend.count() == 1
        buf.close()

    def test_flush_empty_buffer(self):
        backend = InMemoryBackend()
        buf = WriteBuffer(backend, buffer_size=100, flush_interval=60)
        assert buf.flush() == 0
        buf.close()


class TestContextTrailBuffered:
    def test_buffered_log_and_flush(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=100, flush_interval=60
        )
        trail.log("data1", source="retriever")
        trail.log("data2", source="tool")
        assert trail._buffer is not None
        assert trail._buffer.pending == 2
        trail.flush()
        assert trail._buffer.pending == 0
        assert trail.summary()["total"] == 2
        trail.close()

    def test_buffered_close_flushes(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=100, flush_interval=60
        )
        for i in range(10):
            trail.log(f"data{i}", source="retriever")
        trail.close()
        # After close, records should have been flushed
        # Can't query after close, but buffer should be empty

    def test_buffered_chain_integrity(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=100, flush_interval=60
        )
        for i in range(20):
            trail.log(f"record {i}", source="retriever")
        trail.flush()
        verdict = trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 20
        trail.close()

    def test_buffered_auto_flush_on_full(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=5, flush_interval=60
        )
        for i in range(5):
            trail.log(f"data{i}", source="retriever")
        assert trail.summary()["total"] == 5
        trail.close()

    def test_unbuffered_by_default(self):
        trail = ContextTrail(backend="memory")
        assert trail._buffer is None
        trail.log("data", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()

    def test_buffered_health_includes_buffer_info(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=100, flush_interval=60
        )
        trail.log("data", source="retriever")
        h = trail.health()
        assert h["buffered"] is True
        assert "buffer_pending" in h
        assert h["buffer_pending"] == 1
        trail.close()

    def test_unbuffered_health_no_buffer_pending(self):
        trail = ContextTrail(backend="memory")
        h = trail.health()
        assert h["buffered"] is False
        assert "buffer_pending" not in h
        trail.close()

    def test_buffered_config_dict(self):
        trail = ContextTrail(
            config={
                "storage": {"backend": "memory", "buffered": True, "buffer_size": 10},
            }
        )
        assert trail._buffer is not None
        trail.log("data", source="retriever")
        trail.flush()
        assert trail.summary()["total"] == 1
        trail.close()

    def test_flush_returns_zero_when_unbuffered(self):
        trail = ContextTrail(backend="memory")
        assert trail.flush() == 0
        trail.close()


class TestBenchmarks:
    def test_log_10k_entries_under_10s(self):
        trail = ContextTrail(
            backend="memory", buffered=True, buffer_size=500, flush_interval=60
        )
        start = time.monotonic()
        for i in range(10_000):
            trail.log(f"benchmark entry {i} " + "x" * 1000, source="retriever")
        trail.flush()
        elapsed = time.monotonic() - start
        assert elapsed < 10, f"10K entries took {elapsed:.2f}s (limit: 10s)"
        assert trail.summary()["total"] == 10_000
        trail.close()

    def test_verify_10k_chain_under_5s(self):
        trail = ContextTrail(backend="memory")
        for i in range(10_000):
            trail.log(f"entry {i}", source="retriever")
        start = time.monotonic()
        verdict = trail.verify_chain()
        elapsed = time.monotonic() - start
        assert verdict.intact
        assert elapsed < 5, f"Verify 10K took {elapsed:.2f}s (limit: 5s)"
        trail.close()
