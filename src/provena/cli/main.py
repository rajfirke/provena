from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import click

from provena.trail import ContextTrail, _is_pg_url


@click.group()
@click.option(
    "--db",
    default="provena.db",
    envvar="PROVENA_DB",
    help="Path to Provena database file.",
    type=click.Path(),
)
@click.option(
    "--config",
    "config_path",
    default=None,
    envvar="PROVENA_CONFIG",
    help="Path to provena.toml or provena.yaml config file.",
    type=click.Path(),
)
@click.option(
    "--signing-key",
    default=None,
    envvar="PROVENA_SIGNING_KEY",
    help="HMAC signing key for chain verification.",
)
@click.version_option(package_name="provena")
@click.pass_context
def cli(
    ctx: click.Context,
    db: str,
    config_path: str | None,
    signing_key: str | None,
) -> None:
    """Provena — Context governance for agentic AI systems."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["config_path"] = config_path
    ctx.obj["signing_key"] = signing_key


@cli.command()
@click.option("--source", "-s", default=None, help="Filter by source type.")
@click.option("--limit", "-n", default=20, type=int, help="Max records to show.")
@click.option(
    "--from",
    "start",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Filter records from this date (YYYY-MM-DD).",
)
@click.option(
    "--to",
    "end",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Filter records up to this date (YYYY-MM-DD).",
)
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json"]),
    help="Output format.",
)
@click.pass_context
def audit(
    ctx: click.Context,
    source: str | None,
    limit: int,
    start: datetime | None,
    end: datetime | None,
    fmt: str,
) -> None:
    """Query the context governance audit log."""
    config_path = ctx.obj.get("config_path")
    if config_path:
        trail = ContextTrail(config=config_path)
    else:
        db_path = ctx.obj["db"]
        if not _is_pg_url(db_path) and not os.path.exists(db_path):
            click.echo(f"Database not found: {db_path}", err=True)
            ctx.exit(1)
            return
        trail = ContextTrail(
            storage_path=db_path, signing_key=ctx.obj.get("signing_key")
        )
    try:
        records = trail.query(source=source, limit=limit, start=start, end=end)

        if not records:
            click.echo("No records found.")
            return

        if fmt == "json":
            click.echo(json.dumps(records, indent=2, default=str))
        else:
            _print_table(records)
    finally:
        trail.close()


@cli.command()
@click.pass_context
def verify(ctx: click.Context) -> None:
    """Verify the integrity of the hash-chained audit trail."""
    config_path = ctx.obj.get("config_path")
    if config_path:
        trail = ContextTrail(config=config_path)
    else:
        db_path = ctx.obj["db"]
        if not _is_pg_url(db_path) and not os.path.exists(db_path):
            click.echo(f"Database not found: {db_path}", err=True)
            ctx.exit(1)
            return
        trail = ContextTrail(
            storage_path=db_path, signing_key=ctx.obj.get("signing_key")
        )
    try:
        verdict = trail.verify_chain()

        if verdict.total_records == 0:
            click.echo("EMPTY — No records in the audit trail.")
            return

        if verdict.intact:
            click.echo(
                click.style("PASS", fg="green", bold=True)
                + f" — Chain intact ({verdict.total_records} records verified)"
            )
        else:
            click.echo(
                click.style("FAIL", fg="red", bold=True) + f" — {verdict.details}"
            )
            ctx.exit(1)
    finally:
        trail.close()


@cli.command()
@click.option(
    "--format",
    "fmt",
    default="json",
    type=click.Choice(["json", "text", "csv", "pdf"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Write to file.")
@click.pass_context
def report(ctx: click.Context, fmt: str, output: str | None) -> None:
    """Generate a context governance compliance report."""
    config_path = ctx.obj.get("config_path")
    if config_path:
        trail = ContextTrail(config=config_path)
        db_path = config_path  # Use config path for report metadata
    else:
        db_path = ctx.obj["db"]
        if not _is_pg_url(db_path) and not os.path.exists(db_path):
            click.echo(f"Database not found: {db_path}", err=True)
            ctx.exit(1)
            return
        trail = ContextTrail(
            storage_path=db_path, signing_key=ctx.obj.get("signing_key")
        )
    try:
        summary = trail.summary()
        verdict = trail.verify_chain()

        report_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": db_path,
            "total_records": summary["total"],
            "chain_integrity": {
                "status": "INTACT" if verdict.intact else "BROKEN",
                "records_verified": verdict.total_records,
                "broken_at": verdict.broken_at,
            },
            "provenance": summary.get("provenance", {}),
            "freshness": summary.get("freshness", {}),
            "sources": summary.get("sources", {}),
            "signed": summary.get("signed", False),
        }

        if fmt == "pdf":
            from provena.report import generate_pdf_report

            pdf_path = output or "provena-report.pdf"
            generate_pdf_report(trail, pdf_path)
            click.echo(f"PDF report written to {pdf_path}")
        elif fmt == "json":
            content = json.dumps(report_data, indent=2)
            if output:
                with open(output, "w") as f:
                    f.write(content)
                click.echo(f"Report written to {output}")
            else:
                click.echo(content)
        elif fmt == "csv":
            content = trail.export(format="csv")
            if output:
                with open(output, "w") as f:
                    f.write(content)
                click.echo(f"Report written to {output}")
            else:
                click.echo(content)
        else:
            content = _format_text_report(report_data)
            if output:
                with open(output, "w") as f:
                    f.write(content)
                click.echo(f"Report written to {output}")
            else:
                click.echo(content)
    finally:
        trail.close()


@cli.command()
@click.option(
    "--max-age", default=365, type=int, help="Delete records older than this many days."
)
@click.option(
    "--archive",
    default=None,
    type=click.Path(),
    help="Export deleted records to this file before deletion.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be deleted without making changes.",
)
@click.pass_context
def retain(
    ctx: click.Context, max_age: int, archive: str | None, dry_run: bool
) -> None:
    """Apply retention policy — delete old records with optional archive."""
    config_path = ctx.obj.get("config_path")
    if config_path:
        trail = ContextTrail(config=config_path)
    else:
        db_path = ctx.obj["db"]
        if not _is_pg_url(db_path) and not os.path.exists(db_path):
            click.echo(f"Database not found: {db_path}", err=True)
            ctx.exit(1)
            return
        trail = ContextTrail(
            storage_path=db_path, signing_key=ctx.obj.get("signing_key")
        )
    try:
        from provena.retention import RetentionEngine

        engine = RetentionEngine(trail, retention_days=max_age)
        result = engine.execute(archive_path=archive, dry_run=dry_run)

        if dry_run:
            click.echo(result.details)
        elif result.deleted == 0:
            click.echo("No records exceed the retention period.")
        else:
            if result.archive_path:
                click.echo(
                    f"Archived {result.archived} records to {result.archive_path}"
                )
            click.echo(
                click.style("DONE", fg="green", bold=True)
                + f" — Deleted {result.deleted} records older than {max_age} days"
            )
    except ValueError as e:
        click.echo(str(e), err=True)
        ctx.exit(1)
    finally:
        trail.close()


@cli.command()
@click.pass_context
def summary(ctx: click.Context) -> None:
    """Show a quick summary of the audit trail."""
    config_path = ctx.obj.get("config_path")
    if config_path:
        trail = ContextTrail(config=config_path)
    else:
        db_path = ctx.obj["db"]
        if not _is_pg_url(db_path) and not os.path.exists(db_path):
            click.echo(f"Database not found: {db_path}", err=True)
            ctx.exit(1)
            return
        trail = ContextTrail(
            storage_path=db_path, signing_key=ctx.obj.get("signing_key")
        )
    try:
        s = trail.summary()
        h = trail.health()

        click.echo(f"Records:    {s['total']}")
        click.echo(f"Backend:    {h.get('backend', 'unknown')}")
        click.echo(f"Signed:     {'Yes' if s.get('signed') else 'No'}")

        if s["total"] > 0:
            click.echo("")
            click.echo("Provenance:")
            for status, count in sorted(s.get("provenance", {}).items()):
                click.echo(f"  {status:12s} {count}")

            click.echo("")
            click.echo("Freshness:")
            for status, count in sorted(s.get("freshness", {}).items()):
                click.echo(f"  {status:12s} {count}")

            click.echo("")
            click.echo("Sources:")
            for src, count in sorted(s.get("sources", {}).items()):
                click.echo(f"  {src:12s} {count}")
    finally:
        trail.close()


@cli.group()
def mcp() -> None:
    """MCP server commands."""


@mcp.command()
@click.option(
    "--db",
    default=None,
    envvar="PROVENA_DB",
    help="Path to Provena database file.",
    type=click.Path(),
)
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio"]),
    help="MCP transport type.",
)
@click.pass_context
def serve(ctx: click.Context, db: str | None, transport: str) -> None:
    """Start the Provena MCP governance server."""
    try:
        from provena.mcp_server import configure, create_server
    except ImportError:
        click.echo(
            "fastmcp is required for the MCP server. "
            "Install with: pip install provena[mcp]",
            err=True,
        )
        ctx.exit(1)
        return

    db_path = db or ctx.parent.parent.obj.get("db", "provena.db")  # type: ignore[union-attr]
    signing_key = ctx.parent.parent.obj.get("signing_key")  # type: ignore[union-attr]

    trail = ContextTrail(storage_path=db_path, signing_key=signing_key)
    configure(trail)

    server = create_server()
    server.run(transport=transport)


@cli.command()
@click.option(
    "--from",
    "from_path",
    required=True,
    help="Source: SQLite file path or PostgreSQL connection URL.",
)
@click.option(
    "--to",
    "to_path",
    required=True,
    help="Destination: SQLite file path or PostgreSQL connection URL.",
)
@click.option(
    "--batch-size",
    default=500,
    type=int,
    help="Number of records per batch.",
)
@click.pass_context
def migrate(
    ctx: click.Context,
    from_path: str,
    to_path: str,
    batch_size: int,
) -> None:
    """Migrate trail data between storage backends."""
    src = _open_backend(from_path)
    dst = _open_backend(to_path)
    try:
        records = src.all_records()
        total = len(records)
        if total == 0:
            click.echo("Source is empty — nothing to migrate.")
            return

        id_map: dict[int, int] = {}
        for i in range(0, total, batch_size):
            batch = records[i : i + batch_size]
            for record in batch:
                src_id = record.pop("id")
                dst_id = dst.append(record)
                id_map[src_id] = dst_id
            click.echo(f"  Migrated {min(i + batch_size, total)}/{total} records")

        for src_id, dst_id in id_map.items():
            annotations = src.get_annotations(src_id)
            for ann in annotations:
                dst.add_annotation(
                    record_id=dst_id,
                    note=ann["note"],
                    reviewer=ann.get("reviewer", ""),
                    timestamp=ann["timestamp"],
                )

        dst_trail = ContextTrail(
            storage_path=to_path,
            signing_key=ctx.obj.get("signing_key"),
        )
        verdict = dst_trail.verify_chain()
        dst_trail.close()

        if verdict.intact:
            click.echo(
                click.style("PASS", fg="green", bold=True)
                + f" — Migrated {total} records, chain intact"
            )
        else:
            click.echo(
                click.style("FAIL", fg="red", bold=True)
                + f" — Chain broken at record {verdict.broken_at}"
            )
            ctx.exit(1)
    finally:
        src.close()
        dst.close()


def _open_backend(path: str) -> Any:
    if path.startswith("postgresql://") or path.startswith("postgres://"):
        from provena.storage_pg import PostgreSQLBackend

        return PostgreSQLBackend(conninfo=path)
    from provena.storage import SQLiteBackend

    return SQLiteBackend(path=path)


def _print_table(records: list[dict[str, Any]]) -> None:
    try:
        import rich  # noqa: F401

        _print_rich_table(records)
    except ImportError:
        _print_plain_table(records)


def _print_rich_table(records: list[dict[str, Any]]) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="Provena Audit Trail")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Timestamp", width=20)
    table.add_column("Source", style="cyan")
    table.add_column("Name")
    table.add_column("Hash", style="dim", width=12)
    table.add_column("Provenance")
    table.add_column("Freshness")

    for r in records:
        ts = r.get("timestamp", "")[:19]
        ch = r.get("content_hash", "")[:12]
        prov = r.get("provenance_status", "?")
        fresh = r.get("freshness_status", "?")

        prov_style = {"VALID": "green", "MISSING": "red", "INCOMPLETE": "yellow"}.get(
            prov, ""
        )
        fresh_style = {"FRESH": "green", "STALE": "red", "UNKNOWN": "dim"}.get(
            fresh, ""
        )

        table.add_row(
            str(r.get("id", "")),
            ts,
            r.get("source", ""),
            r.get("source_name", ""),
            ch,
            f"[{prov_style}]{prov}[/{prov_style}]" if prov_style else prov,
            f"[{fresh_style}]{fresh}[/{fresh_style}]" if fresh_style else fresh,
        )

    Console().print(table)


def _print_plain_table(records: list[dict[str, Any]]) -> None:
    header = f"{'ID':>5}  {'Timestamp':20s}  {'Source':12s}  {'Name':15s}  {'Hash':12s}  {'Prov':12s}  {'Fresh':7s}"
    click.echo(header)
    click.echo("-" * len(header))
    for r in records:
        click.echo(
            f"{r.get('id', ''):>5}  "
            f"{r.get('timestamp', '')[:19]:20s}  "
            f"{r.get('source', ''):12s}  "
            f"{r.get('source_name', ''):15s}  "
            f"{r.get('content_hash', '')[:12]:12s}  "
            f"{r.get('provenance_status', '?'):12s}  "
            f"{r.get('freshness_status', '?'):7s}"
        )


def _format_text_report(data: dict[str, Any]) -> str:
    lines = [
        "=" * 50,
        "PROVENA GOVERNANCE REPORT",
        "=" * 50,
        f"Generated: {data['generated_at']}",
        f"Database:  {data['database']}",
        f"Records:   {data['total_records']}",
        f"Signed:    {'Yes' if data.get('signed') else 'No'}",
        "",
        "Chain Integrity:",
        f"  Status:   {data['chain_integrity']['status']}",
        f"  Verified: {data['chain_integrity']['records_verified']} records",
    ]

    if data["chain_integrity"]["broken_at"] is not None:
        lines.append(f"  Broken at record: {data['chain_integrity']['broken_at']}")

    lines.append("")
    lines.append("Provenance:")
    for status, count in sorted(data.get("provenance", {}).items()):
        lines.append(f"  {status:12s} {count}")

    lines.append("")
    lines.append("Freshness:")
    for status, count in sorted(data.get("freshness", {}).items()):
        lines.append(f"  {status:12s} {count}")

    lines.append("")
    lines.append("Sources:")
    for src, count in sorted(data.get("sources", {}).items()):
        lines.append(f"  {src:12s} {count}")

    lines.append("=" * 50)
    return "\n".join(lines)
