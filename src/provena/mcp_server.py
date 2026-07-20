"""MCP server exposing governance data to agents via tools and resources."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None

from provena.trail import ContextTrail

_trail: ContextTrail | None = None
_trail_lock = threading.Lock()

_MCP_IMPORT_ERROR = (
    "fastmcp is required for the MCP server. Install with: pip install provena[mcp]"
)


def configure(trail: ContextTrail) -> None:
    """Bind a ContextTrail instance for the MCP server to use."""
    global _trail
    with _trail_lock:
        _trail = trail


def get_trail() -> ContextTrail:
    """Return the configured trail, creating a default one if needed."""
    global _trail
    if _trail is not None:
        return _trail
    with _trail_lock:
        if _trail is None:
            _trail = ContextTrail(
                storage_path=os.environ.get("PROVENA_DB", "provena.db"),
                signing_key=os.environ.get("PROVENA_SIGNING_KEY"),
            )
        return _trail


def create_server(name: str = "provena-governance") -> Any:
    """Create and return a configured FastMCP server instance."""
    if FastMCP is None:
        raise ImportError(_MCP_IMPORT_ERROR)

    mcp = FastMCP(name)

    @mcp.resource("provena://health")
    def governance_health() -> str:
        """System health status for the governance trail."""
        return json.dumps(get_trail().health())

    @mcp.resource("provena://summary")
    def governance_summary() -> str:
        """Governance statistics: record counts, provenance/freshness breakdown."""
        return json.dumps(get_trail().summary())

    @mcp.resource("provena://chain/status")
    def chain_status() -> str:
        """Hash chain integrity status."""
        v = get_trail().verify_chain()
        return json.dumps(
            {
                "intact": v.intact,
                "total_records": v.total_records,
                "broken_at": v.broken_at,
                "details": v.details,
            }
        )

    @mcp.tool()
    def check_freshness(source: str | None = None, limit: int = 10) -> str:
        """Check freshness status of recent context entries."""
        trail = get_trail()
        records = trail.query(
            source=source,
            freshness_status=None,
            limit=limit,
        )
        stale = [r for r in records if r.get("freshness_status") == "STALE"]
        fresh = [r for r in records if r.get("freshness_status") == "FRESH"]
        unknown = [r for r in records if r.get("freshness_status") == "UNKNOWN"]
        result: dict[str, Any] = {
            "total_checked": len(records),
            "fresh": len(fresh),
            "stale": len(stale),
            "unknown": len(unknown),
            "recommendation": (
                "All context is fresh."
                if not stale
                else f"{len(stale)} stale entries detected — consider refreshing."
            ),
        }
        if stale:
            result["stale_entries"] = [
                {"id": r["id"], "source": r["source"], "source_name": r["source_name"]}
                for r in stale
            ]
        return json.dumps(result)

    @mcp.tool()
    def verify_chain() -> str:
        """Verify the integrity of the hash-chained audit trail."""
        v = get_trail().verify_chain()
        return json.dumps(
            {
                "status": "PASS" if v.intact else "FAIL",
                "total_records": v.total_records,
                "broken_at": v.broken_at,
                "details": v.details,
                "recommendation": (
                    "Chain intact — all records verified."
                    if v.intact
                    else f"Chain broken at record {v.broken_at} — investigate tampering."
                ),
            }
        )

    @mcp.tool()
    def list_violations(
        source: str | None = None,
        limit: int = 20,
    ) -> str:
        """List context entries with governance violations (STALE/MISSING/INCOMPLETE)."""
        trail = get_trail()
        stale = trail.query(source=source, freshness_status="STALE", limit=limit)
        missing = trail.query(source=source, provenance_status="MISSING", limit=limit)
        incomplete = trail.query(
            source=source, provenance_status="INCOMPLETE", limit=limit
        )

        violations = []
        seen_ids: set[int] = set()
        for r in stale + missing + incomplete:
            rid = r["id"]
            if rid not in seen_ids:
                seen_ids.add(rid)
                violations.append(
                    {
                        "id": rid,
                        "source": r["source"],
                        "source_name": r["source_name"],
                        "provenance_status": r.get("provenance_status", "?"),
                        "freshness_status": r.get("freshness_status", "?"),
                    }
                )

        return json.dumps(
            {
                "total_violations": len(violations),
                "violations": violations[:limit],
                "recommendation": (
                    "No governance violations found."
                    if not violations
                    else f"{len(violations)} violations — review and remediate."
                ),
            }
        )

    @mcp.tool()
    def get_summary() -> str:
        """Get governance statistics for the audit trail."""
        s = get_trail().summary()
        total = s["total"]
        prov = s.get("provenance", {})
        fresh = s.get("freshness", {})
        valid_pct = round(prov.get("VALID", 0) / total * 100) if total > 0 else 0
        fresh_pct = round(fresh.get("FRESH", 0) / total * 100) if total > 0 else 0
        return json.dumps(
            {
                **s,
                "provenance_valid_pct": valid_pct,
                "freshness_fresh_pct": fresh_pct,
                "recommendation": (
                    f"{valid_pct}% provenance valid, {fresh_pct}% fresh."
                    if total > 0
                    else "No records in the audit trail."
                ),
            }
        )

    @mcp.tool()
    def check_provenance(source: str | None = None, limit: int = 10) -> str:
        """Check provenance compliance for recent context entries."""
        trail = get_trail()
        records = trail.query(source=source, limit=limit)
        valid = [r for r in records if r.get("provenance_status") == "VALID"]
        missing = [r for r in records if r.get("provenance_status") == "MISSING"]
        incomplete = [r for r in records if r.get("provenance_status") == "INCOMPLETE"]
        return json.dumps(
            {
                "total_checked": len(records),
                "valid": len(valid),
                "missing": len(missing),
                "incomplete": len(incomplete),
                "recommendation": (
                    "All entries have valid provenance."
                    if not missing and not incomplete
                    else f"{len(missing)} missing, {len(incomplete)} incomplete — attach provenance metadata."
                ),
            }
        )

    @mcp.prompt()
    def governance_check() -> str:
        """Standard prompt for agent self-audit of governance status."""
        return (
            "Before proceeding, check the governance status of your context:\n"
            "1. Call check_freshness() to verify no stale context\n"
            "2. Call check_provenance() to verify source metadata\n"
            "3. Call verify_chain() to confirm audit trail integrity\n"
            "Report any violations before making decisions."
        )

    return mcp
