from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class ContextSource(str, Enum):
    RETRIEVER = "retriever"
    TOOL = "tool"
    AGENT = "agent"
    MEMORY = "memory"
    MCP = "mcp"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ProvenanceMetadata:
    source_url: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
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
    status: Literal["VALID", "MISSING", "INCOMPLETE"]
    missing_fields: tuple[str, ...] = ()
    details: str = ""


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    status: Literal["FRESH", "STALE", "UNKNOWN"]
    details: str = ""
    detected_date: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextEntry:
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
    id: int
    entry: ContextEntry
    provenance_result: ValidationResult | None
    freshness_result: FreshnessResult | None
    chain_hash: str
    previous_hash: str
    config_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
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
