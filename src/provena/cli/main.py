from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import click

from provena.trail import ContextTrail


@click.group()
@click.option(
    "--db",
    default="provena.db",
    envvar="PROVENA_DB",
    help="Path to Provena database file.",
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
def cli(ctx: click.Context, db: str, signing_key: str | None) -> None:
    """Provena — Context governance for agentic AI systems."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["signing_key"] = signing_key


@cli.command()
@click.option("--source", "-s", default=None, help="Filter by source type.")
@click.option("--limit", "-n", default=20, type=int, help="Max records to show.")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json"]),
    help="Output format.",
)
@click.pass_context
def audit(ctx: click.Context, source: str | None, limit: int, fmt: str) -> None:
    """Query the context governance audit log."""
    db_path = ctx.obj["db"]
    if not os.path.exists(db_path):
        click.echo(f"Database not found: {db_path}", err=True)
        ctx.exit(1)
        return

    trail = ContextTrail(storage_path=db_path, signing_key=ctx.obj.get("signing_key"))
    try:
        records = trail.query(source=source, limit=limit)

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
    db_path = ctx.obj["db"]
    if not os.path.exists(db_path):
        click.echo(f"Database not found: {db_path}", err=True)
        ctx.exit(1)
        return

    trail = ContextTrail(storage_path=db_path, signing_key=ctx.obj.get("signing_key"))
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
    type=click.Choice(["json", "text"]),
    help="Output format.",
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Write to file.")
@click.pass_context
def report(ctx: click.Context, fmt: str, output: str | None) -> None:
    """Generate a context governance compliance report."""
    db_path = ctx.obj["db"]
    if not os.path.exists(db_path):
        click.echo(f"Database not found: {db_path}", err=True)
        ctx.exit(1)
        return

    trail = ContextTrail(storage_path=db_path, signing_key=ctx.obj.get("signing_key"))
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

        if fmt == "json":
            content = json.dumps(report_data, indent=2)
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
@click.pass_context
def summary(ctx: click.Context) -> None:
    """Show a quick summary of the audit trail."""
    db_path = ctx.obj["db"]
    if not os.path.exists(db_path):
        click.echo(f"Database not found: {db_path}", err=True)
        ctx.exit(1)
        return

    trail = ContextTrail(storage_path=db_path, signing_key=ctx.obj.get("signing_key"))
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


def _print_table(records: list[dict]) -> None:
    try:
        import rich  # noqa: F401

        _print_rich_table(records)
    except ImportError:
        _print_plain_table(records)


def _print_rich_table(records: list[dict]) -> None:
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


def _print_plain_table(records: list[dict]) -> None:
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


def _format_text_report(data: dict) -> str:
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
