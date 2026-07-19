"""Core ContextTrail class for logging and auditing context inputs."""

from __future__ import annotations

import csv
import functools
import inspect
import io
import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
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
from provena.policy import (
    EnforcementLevel,
    Policy,
    PolicyEngine,
    PolicyViolation,
)
from provena.storage import InMemoryBackend, SQLiteBackend
from provena.validators.freshness import FreshnessChecker
from provena.validators.provenance import ProvenanceValidator

_logger = logging.getLogger("provena")

F = TypeVar("F", bound=Callable[..., Any])

_DISABLED = os.environ.get("PROVENA_DISABLED", "").lower() in ("1", "true", "yes")


class ContextTrail:
    """Tamper-evident audit trail for AI agent context inputs.

    Logs every context input with provenance validation, freshness checking,
    and SHA-256 hash chaining. Supports both programmatic logging via ``log()``
    and automatic tracking via the ``@trail.track()`` decorator.

    Can be used as a context manager to ensure the storage backend is closed.
    """

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
        policies: list[Policy] | None = None,
        config: dict[str, Any] | str | Path | None = None,
    ) -> None:
        """Initialize a ContextTrail.

        Args:
            storage_path: File path for the SQLite database.
            backend: Storage backend type, ``"sqlite"``, ``"memory"``, or
                ``"postgresql"``.
            required_fields: Provenance fields to require for VALID status.
            max_age_days: Content older than this is marked STALE.
            temporal_detection: Enable regex-based date detection in content text.
            max_content_bytes: Truncate content beyond this size.
            signing_key: HMAC key for signed hash chains. Also read from
                ``PROVENA_SIGNING_KEY`` env var.
            otel_enabled: Emit OpenTelemetry spans for each logged entry.
            otel_service_name: Service name for OTel spans.
            strict_mode: If True, governance errors propagate as exceptions.
            on_error: Optional callback invoked on governance errors.
            policies: List of Policy objects to enforce on every logged entry.
            config: Configuration dict, or path to a ``.toml``/``.yaml`` file.

        Raises:
            ValueError: If max_age_days or max_content_bytes is less than 1.
        """
        if config is not None:
            if isinstance(config, (str, Path)):
                config = _load_config_file(config)
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
        self._policy_engine = PolicyEngine(policies)
        self._update_signing_policies()
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
        elif backend == "postgresql" or _is_pg_url(storage_path):
            from provena.storage_pg import PostgreSQLBackend

            self._backend = PostgreSQLBackend(conninfo=storage_path)  # type: ignore[assignment]
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
        policy_config = config.get("policies", [])

        max_age = freshness.get("max_age_days", 90)
        max_bytes = config.get("max_content_bytes", 65536)
        _validate_config(max_age_days=max_age, max_content_bytes=max_bytes)

        self._strict = config.get("strict_mode", False)
        self._on_error = None
        self._max_content_bytes = max_bytes
        self._error_count = 0
        self._lock = threading.Lock()
        key_value = chain.get("signing_key")
        key_env = chain.get("signing_key_env")
        if key_env and key_value is None:
            key_value = os.environ.get(key_env)
        key = _resolve_signing_key(key_value)
        self._hasher = ChainHasher(signing_key=key)
        self._policy_engine = (
            PolicyEngine.from_config(policy_config) if policy_config else PolicyEngine()
        )
        self._update_signing_policies()
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
        storage_path = storage.get("path", "provena.db")
        if backend_type == "sqlite" and _is_pg_url(storage_path):
            backend_type = "postgresql"

        if _DISABLED or backend_type == "memory":
            self._backend = InMemoryBackend()
        elif backend_type == "postgresql":
            from provena.storage_pg import PostgreSQLBackend

            self._backend = PostgreSQLBackend(  # type: ignore[assignment]
                conninfo=storage_path,
                pool_size=storage.get("pool_size", 5),
            )
        else:
            self._backend = SQLiteBackend(path=storage_path)

        last = self._backend.get_last()
        self._previous_hash = str(last["chain_hash"]) if last else GENESIS_HASH

    def _update_signing_policies(self) -> None:
        from provena.policy import require_signing

        updated = []
        for policy in self._policy_engine.policies:
            if policy.name == "require_signing":
                updated.append(
                    require_signing(
                        enforcement=policy.enforcement,
                        _signed_ref=[self._hasher.is_signed],
                    )
                )
            else:
                updated.append(policy)
        self._policy_engine = PolicyEngine(list(updated))

    @property
    def error_count(self) -> int:
        """Number of governance errors encountered during this trail's lifetime."""
        return self._error_count

    @property
    def is_signed(self) -> bool:
        """Whether this trail uses HMAC-signed hash chains."""
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
        """Log a context input to the audit trail.

        Computes a content hash, validates provenance, checks freshness,
        and appends a hash-chained record to storage.

        Args:
            content: The raw context content (string or bytes).
            source: A ContextSource enum value or string like ``"tool:api"``.
            source_name: Optional explicit source name.
            provenance: Optional origin metadata for validation.
            metadata: Arbitrary key-value pairs to attach to the record.

        Returns:
            The created TrailRecord, or None if a non-strict error occurred.
        """
        try:
            return self._log_internal(
                content,
                source,
                source_name,
                provenance=provenance,
                metadata=metadata,
            )
        except PolicyViolation:
            raise
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
        policy_engine: PolicyEngine | None = None,
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
        self._enforce_policies(trail_record, engine=policy_engine)

        return trail_record

    def _enforce_policies(
        self, record: TrailRecord, *, engine: PolicyEngine | None = None
    ) -> None:
        evaluation = (engine or self._policy_engine).evaluate(record)

        for result in evaluation.results:
            if result.passed:
                continue
            if result.enforcement == EnforcementLevel.WARN:
                _logger.warning(
                    "Policy '%s' violation (WARN): %s",
                    result.policy_name,
                    result.details,
                )

        if evaluation.decision == "DENY":
            blocking = next(
                r
                for r in evaluation.violations
                if r.enforcement == EnforcementLevel.BLOCK
            )
            raise PolicyViolation(
                policy_name=blocking.policy_name,
                record=record,
                details=blocking.details,
            )

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
        policies: list[Policy] | None = None,
    ) -> Callable[[F], F]:
        """Decorator that automatically logs function return values to the trail.

        Supports both sync and async functions. The decorated function's return
        value is passed through unchanged.

        Args:
            source: A ContextSource enum value or string identifying the source.
            source_name: Optional explicit source name.
            content_extractor: Optional callable to extract loggable content
                from the return value.
            policies: Optional per-decorator policy override. When provided,
                these policies are used instead of the trail-level policies
                for calls through this decorator.

        Returns:
            A decorator that wraps the target function with trail logging.
        """
        override_engine = PolicyEngine(policies) if policies is not None else None

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
                        policy_engine=override_engine,
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
                    policy_engine=override_engine,
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
        policy_engine: PolicyEngine | None = None,
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
                    policy_engine=policy_engine,
                )
        except PolicyViolation:
            raise
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
        """Verify the integrity of the entire hash chain.

        Recomputes every chain hash from the genesis hash forward and checks
        each against the stored value.

        Returns:
            A ChainVerdict indicating whether the chain is intact.
        """
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
        """Query the audit trail with optional filters.

        Args:
            source: Filter by context source type.
            start: Include only records at or after this timestamp.
            end: Include only records at or before this timestamp.
            provenance_status: Filter by provenance validation status.
            freshness_status: Filter by freshness check status.
            limit: Maximum number of records to return.

        Returns:
            A list of record dictionaries matching the filters.
        """
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
        """Add a human oversight annotation to a trail record.

        Args:
            record_id: The ID of the record to annotate.
            note: The annotation text.
            reviewer: Optional name of the reviewer.

        Returns:
            The ID of the created annotation.
        """
        ts = datetime.now(timezone.utc).isoformat()
        return self._backend.add_annotation(record_id, note, reviewer, ts)

    def get_annotations(self, record_id: int) -> list[dict[str, Any]]:
        """Return all annotations for ``record_id`` in insertion order.

        Returns an empty list if the record does not exist or has no
        annotations (does not raise).
        """
        return self._backend.get_annotations(record_id)

    def summary(self) -> dict[str, Any]:
        """Generate an aggregate summary of the audit trail.

        Returns:
            A dictionary with total count, provenance/freshness/source
            breakdowns, and signing status.
        """
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
        """Export all trail records in the specified format.

        Args:
            format: Output format, either ``"json"`` or ``"csv"``.

        Returns:
            The serialized trail data as a string.
        """
        records = self._backend.all_records()

        if format == "json_with_annotations":
            annotations: dict[str, list[dict[str, Any]]] = {}
            for record in records:
                record_id = record["id"]
                anns = self._backend.get_annotations(record_id)
                if anns:
                    annotations[str(record_id)] = anns
            payload: dict[str, Any] = {"records": records}
            if annotations:
                payload["annotations"] = annotations
            return json.dumps(payload, indent=2, default=str)

        if format == "json":
            return json.dumps(records, indent=2, default=str)

        if format == "csv":
            output = io.StringIO()
            fieldnames = [
                "id",
                "timestamp",
                "source",
                "source_name",
                "content_hash",
                "provenance_status",
                "freshness_status",
                "chain_hash",
            ]
            writer = csv.writer(output)
            writer.writerow(fieldnames)

            for record in records:
                writer.writerow([record.get(field, "") for field in fieldnames])

            return output.getvalue()

        return json.dumps(records, default=str)

    def health(self) -> dict[str, Any]:
        """Return a health-check dictionary for the trail.

        Returns:
            A dictionary with status, record count, backend type,
            signing state, and error count.
        """
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
        """Close the storage backend and release resources."""
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
        """Enter the context manager, returning this trail."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit the context manager, closing the storage backend."""
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


def _is_pg_url(path: str) -> bool:
    return isinstance(path, str) and (
        path.startswith("postgresql://") or path.startswith("postgres://")
    )


def _load_config_file(path: str | Path) -> dict[str, Any]:
    """Load configuration from a TOML or YAML file."""
    filepath = Path(path)
    if not filepath.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")

    suffix = filepath.suffix.lower()

    if suffix == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        with open(filepath, "rb") as f:
            return dict(tomllib.load(f))

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML config files. "
                "Install with: pip install provena[yaml]"
            ) from None
        with open(filepath) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(
                f"YAML config must be a mapping, got {type(data).__name__}"
            )
        return data

    raise ValueError(
        f"Unsupported config file format: '{suffix}'. "
        "Use .toml, .yaml, or .yml"
    )
