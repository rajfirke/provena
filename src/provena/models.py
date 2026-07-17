"""Data models for context governance records and validation results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class ContextSource(str, Enum):
    """Enumeration of context input source types."""

    RETRIEVER = "retriever"
    TOOL = "tool"
    AGENT = "agent"
    MEMORY = "memory"
    MCP = "mcp"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ProvenanceMetadata:
    """Immutable metadata about the origin and authorship of a context input.

    Attributes:
        source_url: URL where the content was retrieved from.
        author: Author or creator of the content.
        created_at: When the content was originally created or published.
        version: Version identifier for the content.
        extra: Additional key-value metadata.
    """

    source_url: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize non-None fields to a plain dictionary."""
        d: dict[str, Any] = {}
        if self.source_url is not None:
            d["source_url"] = self.source_url
        if self.author is not None:
            d["author"] = self.author
        if self.created_at is not None:
            d["created_at"] = self.created_at.isoformat()
        if self.version is not None:
            d["version"] = self.version
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceMetadata:
        """Reconstruct a ProvenanceMetadata instance from a dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            source_url=data.get("source_url"),
            author=data.get("author"),
            created_at=created_at,
            version=data.get("version"),
            extra=data.get("extra") or {},
        )


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of provenance validation for a context entry.

    Attributes:
        status: One of ``"VALID"``, ``"MISSING"``, or ``"INCOMPLETE"``.
        missing_fields: Names of required fields that were absent.
        details: Human-readable explanation.
    """

    status: Literal["VALID", "MISSING", "INCOMPLETE"]
    missing_fields: tuple[str, ...] = ()
    details: str = ""


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """Result of freshness checking for a context entry.

    Attributes:
        status: One of ``"FRESH"``, ``"STALE"``, or ``"UNKNOWN"``.
        details: Human-readable explanation.
        detected_date: The date used for age calculation, if detected.
    """

    status: Literal["FRESH", "STALE", "UNKNOWN"]
    details: str = ""
    detected_date: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextEntry:
    """Immutable representation of a single context input with its content hash.

    Attributes:
        content_hash: SHA-256 hex digest of the content bytes.
        source: The type of source that produced this context.
        source_name: Human-readable name identifying the specific source.
        timestamp: When this entry was recorded.
        provenance: Optional origin metadata for validation.
        metadata: Arbitrary key-value pairs attached to the entry.
        content_type: The original content type (``"str"``, ``"bytes"``, or ``"json"``).
        truncated: Whether the content was truncated to fit max_content_bytes.
    """

    content_hash: str
    source: ContextSource
    source_name: str
    timestamp: datetime
    provenance: ProvenanceMetadata | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    content_type: str = "str"
    truncated: bool = False

    @classmethod
    def create(
        cls,
        content: str | bytes,
        source: ContextSource | str,
        source_name: str = "",
        *,
        provenance: ProvenanceMetadata | None = None,
        metadata: dict[str, Any] | None = None,
        max_content_bytes: int = 65536,
        timestamp: datetime | None = None,
    ) -> ContextEntry:
        """Create a ContextEntry by hashing content and resolving the source.

        Args:
            content: The raw context content to record.
            source: A ContextSource enum or string like ``"tool:api_name"``.
            source_name: Optional explicit name; inferred from source if omitted.
            provenance: Optional origin metadata for validation.
            metadata: Arbitrary key-value pairs to attach.
            max_content_bytes: Truncate content beyond this size. Defaults to 64 KB.
            timestamp: Override the recording timestamp. Defaults to UTC now.

        Returns:
            A new ContextEntry with a computed SHA-256 content hash.
        """
        source_enum, resolved_name = _parse_source(source, source_name)
        content_bytes, content_type, truncated = _prepare_content(
            content, max_content_bytes
        )
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        return cls(
            content_hash=content_hash,
            source=source_enum,
            source_name=resolved_name,
            timestamp=timestamp or datetime.now(timezone.utc),
            provenance=provenance,
            metadata=metadata or {},
            content_type=content_type,
            truncated=truncated,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this entry to a plain dictionary."""
        return {
            "content_hash": self.content_hash,
            "source": self.source.value,
            "source_name": self.source_name,
            "timestamp": self.timestamp.isoformat(),
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "metadata": self.metadata,
            "content_type": self.content_type,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class TrailRecord:
    """A single record in the audit trail linking a ContextEntry to chain hashes.

    Attributes:
        id: Sequential record identifier from the storage backend.
        entry: The context entry that was logged.
        provenance_result: Provenance validation outcome, if checked.
        freshness_result: Freshness check outcome, if checked.
        chain_hash: This record's position in the hash chain.
        previous_hash: The chain hash of the preceding record.
        config_hash: Hash of the trail configuration at recording time.
    """

    id: int
    entry: ContextEntry
    provenance_result: ValidationResult | None
    freshness_result: FreshnessResult | None
    chain_hash: str
    previous_hash: str
    config_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record to a plain dictionary."""
        result: dict[str, Any] = {
            "id": self.id,
            "entry": self.entry.to_dict(),
            "chain_hash": self.chain_hash,
            "previous_hash": self.previous_hash,
            "config_hash": self.config_hash,
        }
        if self.provenance_result:
            result["provenance_result"] = {
                "status": self.provenance_result.status,
                "missing_fields": list(self.provenance_result.missing_fields),
                "details": self.provenance_result.details,
            }
        if self.freshness_result:
            result["freshness_result"] = {
                "status": self.freshness_result.status,
                "details": self.freshness_result.details,
                "detected_date": (
                    self.freshness_result.detected_date.isoformat()
                    if self.freshness_result.detected_date
                    else None
                ),
            }
        return result


@dataclass(frozen=True, slots=True)
class ChainVerdict:
    """Outcome of verifying the integrity of the hash chain.

    Attributes:
        intact: True if every link in the chain is valid.
        total_records: Number of records that were checked.
        broken_at: Record ID where the chain first broke, or None.
        details: Human-readable summary of the verification.
    """

    intact: bool
    total_records: int
    broken_at: int | None = None
    details: str = ""


def _parse_source(
    source: ContextSource | str, source_name: str
) -> tuple[ContextSource, str]:
    if isinstance(source, ContextSource):
        return source, source_name or source.value

    parts = source.split(":", 1)
    try:
        source_enum = ContextSource(parts[0])
    except ValueError:
        source_enum = ContextSource.CUSTOM

    if len(parts) > 1 and not source_name:
        source_name = parts[1] or parts[0]
    elif not source_name:
        source_name = source

    return source_enum, source_name


def _prepare_content(
    content: str | bytes, max_content_bytes: int
) -> tuple[bytes, str, bool]:
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
        content_type = "str"
    elif isinstance(content, bytes):
        content_bytes = content
        content_type = "bytes"
    else:
        content_bytes = json.dumps(content, default=str).encode("utf-8")
        content_type = "json"

    truncated = len(content_bytes) > max_content_bytes
    if truncated:
        content_bytes = content_bytes[:max_content_bytes]

    return content_bytes, content_type, truncated
