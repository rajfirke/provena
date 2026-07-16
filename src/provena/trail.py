from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from provena.exporters.otel import OTelExporter
from provena.hasher import GENESIS_HASH, ChainHasher
from provena.models import (
    ChainVerdict,
    ContextEntry,
    ContextSource,
    ProvenanceMetadata,
    TrailRecord,
)
from provena.storage import InMemoryBackend, SQLiteBackend
from provena.validators.freshness import FreshnessChecker
from provena.validators.provenance import ProvenanceValidator

_logger = logging.getLogger("provena")

F = TypeVar("F", bound=Callable[..., Any])

_DISABLED = os.environ.get("PROVENA_DISABLED", "").lower() in ("1", "true", "yes")


class ContextTrail:
    def __init__(
        self,
        *,
        storage_path: str = "provena.db",
        backend: str = "sqlite",
        required_fields: list[str] | tuple[str, ...] | None = None,
        max_age_days: int = 90,
        temporal_detection: bool = True,
        max_content_bytes: int = 65536,
        signing_key: str | bytes | None = None,
        otel_enabled: bool = False,
        otel_service_name: str = "provena",
        strict_mode: bool = False,
        on_error: Callable[[Exception], None] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        if config:
            self._apply_config(config)
            return

        _validate_config(max_age_days=max_age_days, max_content_bytes=max_content_bytes)

        self._strict = strict_mode
        self._on_error = on_error
        self._max_content_bytes = max_content_bytes
        self._error_count = 0
        self._lock = threading.Lock()

        key = _resolve_signing_key(signing_key)
        self._hasher = ChainHasher(signing_key=key)
        self._validator = ProvenanceValidator(required_fields=required_fields)
        self._freshness = FreshnessChecker(
            max_age_days=max_age_days,
            temporal_detection=temporal_detection,
        )
        self._otel = OTelExporter(
            enabled=otel_enabled,
            service_name=otel_service_name,
        )

        self._backend: InMemoryBackend | SQLiteBackend
        if _DISABLED or backend == "memory":
            self._backend = InMemoryBackend()
        else:
            self._backend = SQLiteBackend(path=storage_path)

        last = self._backend.get_last()
        self._previous_hash: str = last["chain_hash"] if last else GENESIS_HASH

    def _apply_config(self, config: dict[str, Any]) -> None:
        storage = config.get("storage", {})
        provenance = config.get("provenance", {})
        freshness = config.get("freshness", {})
        chain = config.get("hash_chain", {})
        otel = config.get("otel", {})

        max_age = freshness.get("max_age_days", 90)
        max_bytes = config.get("max_content_bytes", 65536)
        _validate_config(max_age_days=max_age, max_content_bytes=max_bytes)

        self._strict = config.get("strict_mode", False)
        self._on_error = None
        self._max_content_bytes = max_bytes
        self._error_count = 0
        self._lock = threading.Lock()

        key = _resolve_signing_key(chain.get("signing_key"))
        self._hasher = ChainHasher(signing_key=key)
        self._validator = ProvenanceValidator(
            required_fields=provenance.get("required_fields")
        )
        self._freshness = FreshnessChecker(
            max_age_days=max_age,
            temporal_detection=freshness.get("temporal_detection", True),
        )
        self._otel = OTelExporter(
            enabled=otel.get("enabled", False),
            service_name=otel.get("service_name", "provena"),
        )

        backend_type = storage.get("backend", "sqlite")
        if _DISABLED or backend_type == "memory":
            self._backend = InMemoryBackend()
        else:
            self._backend = SQLiteBackend(path=storage.get("path", "provena.db"))

        last = self._backend.get_last()
        self._previous_hash = str(last["chain_hash"]) if last else GENESIS_HASH

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def is_signed(self) -> bool:
        return self._hasher.is_signed

    def log(
        self,
        content: str | bytes,
        source: ContextSource | str,
        source_name: str = "",
        *,
        provenance: ProvenanceMetadata | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrailRecord | None:
        try:
            return self._log_internal(
                content,
                source,
                source_name,
                provenance=provenance,
                metadata=metadata,
            )
        except Exception as exc:
            self._handle_error(exc)
            return None

    def _log_internal(
        self,
        content: str | bytes,
        source: ContextSource | str,
        source_name: str = "",
        *,
        provenance: ProvenanceMetadata | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrailRecord:
        entry = ContextEntry.create(
            content=content,
            source=source,
            source_name=source_name,
            provenance=provenance,
            metadata=metadata,
            max_content_bytes=self._max_content_bytes,
        )

        prov_result = self._validator.validate(entry)
        content_str = content if isinstance(content, str) else None
        fresh_result = self._freshness.check(entry, content=content_str)

        with self._lock:
            prev_hash = self._previous_hash
            chain_hash = self._hasher.compute_chain_hash(
                previous_hash=prev_hash,
                content_hash=entry.content_hash,
                source=entry.source.value,
                timestamp=entry.timestamp.isoformat(),
            )

            record_data = {
                "content_hash": entry.content_hash,
                "source": entry.source.value,
                "source_name": entry.source_name,
                "timestamp": entry.timestamp.isoformat(),
                "provenance_json": json.dumps(
                    entry.provenance.to_dict() if entry.provenance else None
                ),
                "provenance_status": prov_result.status,
                "missing_fields": ",".join(prov_result.missing_fields),
                "freshness_status": fresh_result.status,
                "chain_hash": chain_hash,
                "previous_hash": prev_hash,
                "metadata_json": json.dumps(entry.metadata),
                "content_type": entry.content_type,
                "truncated": entry.truncated,
            }

            record_id = self._backend.append(record_data)
            self._previous_hash = chain_hash

        trail_record = TrailRecord(
            id=record_id,
            entry=entry,
            provenance_result=prov_result,
            freshness_result=fresh_result,
            chain_hash=chain_hash,
            previous_hash=prev_hash,
        )

        self._emit_otel(trail_record)

        return trail_record

    def _emit_otel(self, record: TrailRecord) -> None:
        try:
            self._otel.emit(record)
        except Exception:
            _logger.debug("OTel emit failed (non-fatal)", exc_info=True)

    def track(
        self,
        source: ContextSource | str,
        source_name: str = "",
        *,
        content_extractor: Callable[..., str | bytes | list[Any]] | None = None,
    ) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            if _DISABLED:
                return func

            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    result = await func(*args, **kwargs)
                    self._track_result(
                        result,
                        source,
                        source_name,
                        content_extractor=content_extractor,
                    )
                    return result

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = func(*args, **kwargs)
                self._track_result(
                    result,
                    source,
                    source_name,
                    content_extractor=content_extractor,
                )
                return result

            return sync_wrapper  # type: ignore[return-value]

        return decorator

    def _track_result(
        self,
        result: Any,
        source: ContextSource | str,
        source_name: str,
        *,
        content_extractor: Callable[..., Any] | None = None,
    ) -> None:
        try:
            items = self._extract_content(result, content_extractor)
            provenance = self._extract_provenance(result)
            for content in items:
                self._log_internal(
                    content=content,
                    source=source,
                    source_name=source_name,
                    provenance=provenance,
                )
        except Exception as exc:
            self._handle_error(exc)

    def _extract_content(
        self,
        result: Any,
        extractor: Callable[..., Any] | None = None,
    ) -> list[str | bytes]:
        if result is None:
            return []

        if extractor is not None:
            extracted = extractor(result)
            if isinstance(extracted, list):
                return [str(item) for item in extracted]
            return [str(extracted)]

        if isinstance(result, (str, bytes)):
            return [result]

        if isinstance(result, (list, tuple)):
            return [self._item_to_content(item) for item in result]

        if isinstance(result, dict):
            return [json.dumps(result, default=str)]

        if hasattr(result, "page_content"):
            return [str(result.page_content)]

        if hasattr(result, "text"):
            return [str(result.text)]

        return [str(result)]

    def _item_to_content(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        if hasattr(item, "page_content"):
            return str(item.page_content)
        if hasattr(item, "text"):
            return str(item.text)
        return str(item)

    def _extract_provenance(self, result: Any) -> ProvenanceMetadata | None:
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            meta = result.metadata
            return ProvenanceMetadata(
                source_url=meta.get("source") or meta.get("source_url"),
                author=meta.get("author"),
                created_at=None,
                version=meta.get("version"),
            )
        return None

    def verify_chain(self) -> ChainVerdict:
        records = self._backend.all_records()
        if not records:
            return ChainVerdict(intact=True, total_records=0, details="Empty trail")

        previous_hash = GENESIS_HASH
        for record in records:
            expected = self._hasher.compute_chain_hash(
                previous_hash=previous_hash,
                content_hash=record["content_hash"],
                source=record["source"],
                timestamp=record["timestamp"],
            )
            if expected != record["chain_hash"]:
                return ChainVerdict(
                    intact=False,
                    total_records=len(records),
                    broken_at=record["id"],
                    details=f"Chain broken at record {record['id']}",
                )
            previous_hash = record["chain_hash"]

        return ChainVerdict(
            intact=True,
            total_records=len(records),
            details="Chain intact",
        )

    def query(
        self,
        *,
        source: ContextSource | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        provenance_status: str | None = None,
        freshness_status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        source_str = source.value if isinstance(source, ContextSource) else source
        return self._backend.query(
            source=source_str,
            start=start,
            end=end,
            provenance_status=provenance_status,
            freshness_status=freshness_status,
            limit=limit,
        )

    def annotate(
        self,
        record_id: int,
        note: str,
        reviewer: str = "",
    ) -> int:
        ts = datetime.now(timezone.utc).isoformat()
        return self._backend.add_annotation(record_id, note, reviewer, ts)

    def summary(self) -> dict[str, Any]:
        records = self._backend.all_records()
        total = len(records)
        if total == 0:
            return {"total": 0, "provenance": {}, "freshness": {}, "sources": {}}

        prov_counts: dict[str, int] = {}
        fresh_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for r in records:
            status = r.get("provenance_status", "MISSING")
            prov_counts[status] = prov_counts.get(status, 0) + 1
            fstatus = r.get("freshness_status", "UNKNOWN")
            fresh_counts[fstatus] = fresh_counts.get(fstatus, 0) + 1
            src = r.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1

        return {
            "total": total,
            "provenance": prov_counts,
            "freshness": fresh_counts,
            "sources": source_counts,
            "signed": self._hasher.is_signed,
        }

    def export(self, format: str = "json") -> str:
        records = self._backend.all_records()
        if format == "json":
            return json.dumps(records, indent=2, default=str)
        return json.dumps(records, default=str)

    def health(self) -> dict[str, Any]:
        try:
            count = self._backend.count()
            return {
                "status": "healthy",
                "record_count": count,
                "backend": type(self._backend).__name__,
                "signed": self._hasher.is_signed,
                "errors": self._error_count,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
                "errors": self._error_count,
            }

    def close(self) -> None:
        self._backend.close()

    def _handle_error(self, exc: Exception) -> None:
        self._error_count += 1
        _logger.warning("Provena governance error: %s", exc)
        if self._on_error is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self._on_error(exc)
        if self._strict:
            raise
        return None

    def __enter__(self) -> ContextTrail:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _validate_config(max_age_days: int = 90, max_content_bytes: int = 65536) -> None:
    if max_age_days < 1:
        raise ValueError(f"max_age_days must be >= 1, got {max_age_days}")
    if max_content_bytes < 1:
        raise ValueError(f"max_content_bytes must be >= 1, got {max_content_bytes}")


def _resolve_signing_key(key: str | bytes | None) -> bytes | None:
    if key is None:
        env_key = os.environ.get("PROVENA_SIGNING_KEY")
        if env_key:
            return env_key.encode("utf-8")
        return None
    if isinstance(key, str):
        return key.encode("utf-8")
    return key
