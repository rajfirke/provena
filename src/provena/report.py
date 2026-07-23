"""Compliance report generator for EU AI Act and OWASP ASI06."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def generate_report(
    trail: Any,
    *,
    format: str = "json",
    title: str = "Provena Governance Compliance Report",
) -> str:
    """Generate a compliance report from a ContextTrail.

    Args:
        trail: The ContextTrail instance to report on.
        format: Output format — ``"json"``, ``"text"``, or ``"pdf"``.
        title: Report title (used in text and PDF formats).

    Returns:
        The report content as a string. For PDF, returns the raw bytes
        as a string (use ``generate_pdf_report`` for file output).
    """
    data = _collect_report_data(trail, title=title)

    if format == "json":
        return json.dumps(data, indent=2, default=str)
    if format == "text":
        return _render_text(data)
    if format == "pdf":
        return _render_pdf_string(data)
    raise ValueError(
        f"Unsupported format '{format}'. Valid formats are: text, json, pdf."
    )


def generate_pdf_report(
    trail: Any,
    output_path: str,
    *,
    title: str = "Provena Governance Compliance Report",
) -> str:
    """Generate a PDF compliance report and write it to a file.

    Args:
        trail: The ContextTrail instance to report on.
        output_path: File path for the PDF output.
        title: Report title.

    Returns:
        The output file path.

    Raises:
        ImportError: If ``fpdf2`` is not installed.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError(
            "fpdf2 is required for PDF reports. Install with: pip install provena[pdf]"
        ) from None

    data = _collect_report_data(trail, title=title)
    pdf = _build_pdf(data, FPDF)
    pdf.output(output_path)
    return output_path


def _collect_report_data(trail: Any, *, title: str = "") -> dict[str, Any]:
    summary = trail.summary()
    verdict = trail.verify_chain()
    total = summary["total"]
    prov = summary.get("provenance", {})
    fresh = summary.get("freshness", {})

    valid_count = prov.get("VALID", 0)
    stale_count = fresh.get("STALE", 0)

    compliance_score = 0
    checks_passed = 0
    checks_total = 4
    issues: list[str] = []

    if verdict.intact:
        checks_passed += 1
    else:
        issues.append(
            f"Hash chain broken at record {verdict.broken_at} — "
            "tamper-evident logging compromised (Art. 12)"
        )

    if total > 0 and valid_count == total:
        checks_passed += 1
    elif total > 0:
        pct = round(valid_count / total * 100)
        issues.append(
            f"Only {pct}% of records have valid provenance — "
            "data lineage incomplete (Art. 10)"
        )

    if total > 0 and stale_count / total <= 0.1:
        checks_passed += 1
    elif total > 0:
        issues.append(
            f"{stale_count} stale records detected — "
            "context freshness monitoring needed"
        )

    if summary.get("signed", False):
        checks_passed += 1
    else:
        issues.append(
            "Trail is not HMAC-signed — "
            "consider enabling signing for tamper resistance (Art. 12)"
        )

    if checks_total > 0:
        compliance_score = round(checks_passed / checks_total * 100)

    return {
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compliance_score": compliance_score,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "issues": issues,
        "chain_integrity": {
            "status": "INTACT" if verdict.intact else "BROKEN",
            "records_verified": verdict.total_records,
            "broken_at": verdict.broken_at,
        },
        "summary": {
            "total_records": total,
            "provenance": prov,
            "freshness": fresh,
            "sources": summary.get("sources", {}),
            "signed": summary.get("signed", False),
        },
        "eu_ai_act": {
            "article_10": {
                "name": "Data Governance",
                "status": "PASS" if valid_count == total and total > 0 else "REVIEW",
                "detail": f"{valid_count}/{total} records with valid provenance",
            },
            "article_12": {
                "name": "Record-Keeping",
                "status": "PASS" if verdict.intact else "FAIL",
                "detail": (
                    f"Chain intact ({verdict.total_records} records)"
                    if verdict.intact
                    else f"Chain broken at record {verdict.broken_at}"
                ),
            },
            "article_13": {
                "name": "Transparency",
                "status": "PASS" if total > 0 else "REVIEW",
                "detail": f"{total} records with source tracking",
            },
            "article_14": {
                "name": "Human Oversight",
                "status": "PRESENT",
                "detail": "Annotation API available (trail.annotate)",
            },
        },
    }


def _render_text(data: dict[str, Any]) -> str:
    lines = [
        "=" * 60,
        data["title"].center(60),
        "=" * 60,
        f"Generated: {data['generated_at']}",
        "",
        f"COMPLIANCE SCORE: {data['compliance_score']}% "
        f"({data['checks_passed']}/{data['checks_total']} checks passed)",
        "",
    ]

    if data["issues"]:
        lines.append("ISSUES:")
        for issue in data["issues"]:
            lines.append(f"  ! {issue}")
        lines.append("")

    ci = data["chain_integrity"]
    lines.extend(
        [
            "CHAIN INTEGRITY:",
            f"  Status:   {ci['status']}",
            f"  Verified: {ci['records_verified']} records",
        ]
    )
    if ci["broken_at"] is not None:
        lines.append(f"  Broken:   record {ci['broken_at']}")
    lines.append("")

    s = data["summary"]
    lines.extend(
        [
            "SUMMARY:",
            f"  Records:  {s['total_records']}",
            f"  Signed:   {'Yes' if s['signed'] else 'No'}",
        ]
    )
    lines.append("")
    lines.append("  Provenance:")
    for status, count in sorted(s.get("provenance", {}).items()):
        lines.append(f"    {status:12s} {count}")
    lines.append("  Freshness:")
    for status, count in sorted(s.get("freshness", {}).items()):
        lines.append(f"    {status:12s} {count}")
    lines.append("  Sources:")
    for src, count in sorted(s.get("sources", {}).items()):
        lines.append(f"    {src:12s} {count}")
    lines.append("")

    lines.append("EU AI ACT COMPLIANCE:")
    for key, article in data["eu_ai_act"].items():
        lines.append(
            f"  {key.upper():12s} {article['name']:20s} "
            f"[{article['status']}] {article['detail']}"
        )

    lines.append("=" * 60)
    return "\n".join(lines)


def _render_pdf_string(data: dict[str, Any]) -> str:
    return _render_text(data)


def _build_pdf(data: dict[str, Any], fpdf_class: type) -> Any:
    pdf = fpdf_class()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, data["title"], new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0,
        6,
        f"Generated: {data['generated_at']}",
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 14)
    score = data["compliance_score"]
    pdf.cell(
        0,
        10,
        f"Compliance Score: {score}% ({data['checks_passed']}/{data['checks_total']})",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    if data["issues"]:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Issues", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for issue in data["issues"]:
            pdf.multi_cell(0, 6, f"  - {issue}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Chain Integrity", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    ci = data["chain_integrity"]
    pdf.cell(
        0,
        6,
        f"Status: {ci['status']}  |  Records: {ci['records_verified']}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    s = data["summary"]
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0,
        6,
        f"Total: {s['total_records']}  |  Signed: {'Yes' if s['signed'] else 'No'}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    for label, breakdown in [
        ("Provenance", s.get("provenance", {})),
        ("Freshness", s.get("freshness", {})),
        ("Sources", s.get("sources", {})),
    ]:
        items = ", ".join(f"{k}: {v}" for k, v in sorted(breakdown.items()))
        pdf.cell(0, 6, f"  {label}: {items}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "EU AI Act Compliance", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for key, article in data["eu_ai_act"].items():
        pdf.cell(
            0,
            6,
            f"  {key.upper()} - {article['name']}: "
            f"[{article['status']}] {article['detail']}",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    return pdf
