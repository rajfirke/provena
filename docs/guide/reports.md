# Compliance Reports

While cryptographic hash chains prove that context data has not been altered,
auditors, compliance officers, and executive teams require structured evidence
summarizing governance health.

Provena includes an automated **Compliance Report Generator** that analyzes
your audit trail, evaluates it against regulatory requirements, computes an
objective **Compliance Score**, and generates executive-ready reports in
**JSON**, **plain text**, or **PDF** formats.

---

## Supported Output Formats

| Format | Output Type | Primary Use Case |
|---|---|---|
| `json` | String (`json.dumps`) | Machine-readable reporting, API responses, SIEM ingestion |
| `text` | String (formatted text) | CI/CD build logs, terminal review, standard output |
| `pdf` | Binary bytes / PDF file | Executive presentation, formal regulatory submissions |

!!! info "PDF Export Requirement"
    Generating PDF reports requires the `fpdf2` library. Install it using the
    optional `pdf` extra:
    ```bash
    pip install provena[pdf]
    ```

---

## Python API

Provena provides two high-level reporting functions in `provena.report`:

```python
from provena.report import generate_report, generate_pdf_report
```

### 1. `generate_report()`

```python
def generate_report(
    trail: Any,
    *,
    format: str = "json",
    title: str = "Provena Governance Compliance Report",
) -> str | bytes:
```

- **`trail`**: The active `ContextTrail` instance to analyze.
- **`format`**: One of `"json"`, `"text"`, or `"pdf"`.
- **`title`**: Custom title appearing in text and PDF reports.
- **Returns**: Formatted `str` (for `json` and `text`) or raw PDF `bytes` (for `pdf`).

#### Quick Example: JSON & Text

```python
from datetime import datetime, timezone
from provena import ContextTrail, ProvenanceMetadata
from provena.report import generate_report

trail = ContextTrail(backend="memory", signing_key="my-secret-key")

# Log governed context
prov = ProvenanceMetadata(
    source_url="https://docs.example.com/api",
    author="platform-team",
    created_at=datetime.now(timezone.utc),
)
trail.log("Configured cluster topology.", source="retriever", provenance=prov)

# Generate JSON report
json_report = generate_report(trail, format="json")
print(json_report)

# Generate Text report
text_report = generate_report(trail, format="text", title="Quarterly Governance Review")
print(text_report)
```

### 2. `generate_pdf_report()`

```python
def generate_pdf_report(
    trail: Any,
    output_path: str,
    *,
    title: str = "Provena Governance Compliance Report",
) -> str:
```

Directly builds a structured PDF document and writes it to disk:

```python
from provena.report import generate_pdf_report

pdf_path = generate_pdf_report(
    trail,
    "reports/quarterly_audit.pdf",
    title="Executive AI Context Governance Report",
)
print(f"Report written to: {pdf_path}")
```

---

## Compliance Scoring Model

Every generated report evaluates **four core governance criteria** based on the
technical state of the audit trail. Each check contributes **25%** toward the
overall **Compliance Score** (0% to 100%):

**Compliance Score** = round((Checks Passed / Total Checks) * 100)

| # | Check Name | Target Criterion | EU AI Act Article |
|---|---|---|---|
| 1 | **Chain Integrity** | Hash chain is unbroken from genesis (`verdict.intact is True`) | **Article 12** (Record-Keeping) |
| 2 | **Data Lineage** | 100% of recorded entries have valid provenance (`valid_count == total`) | **Article 10** (Data Governance) |
| 3 | **Context Freshness** | Stale context inputs do not exceed 10% of total records (10% or fewer) | **Article 10** (Data Quality) |
| 4 | **Tamper Resistance** | Audit trail is HMAC-signed (`trail.is_signed is True`) | **Article 12** (Tamper Resistance) |

### Issue Reporting

When any of the four checks fail, Provena appends an explicit finding to the
`issues` list:

- **Broken Hash Chain**: `"Hash chain broken at record {id} - tamper-evident logging compromised (Art. 12)"`
- **Missing Provenance**: `"Only {pct}% of records have valid provenance - data lineage incomplete (Art. 10)"`
- **Excessive Stale Data**: `"{count} stale records detected - context freshness monitoring needed"`
- **Unsigned Chain**: `"Trail is not HMAC-signed - consider enabling signing for tamper resistance (Art. 12)"`

---

## EU AI Act Article Mapping

Provena maps technical audit metrics directly to four operational articles of
the EU AI Act (Regulation 2024/1689):

| Article | Requirement | Report Status | Evaluation Rule |
|---|---|---|---|
| **Article 10**<br>*(Data Governance)* | High-risk AI systems must implement data governance, ensuring data lineage and error-free context. | `PASS`<br>`REVIEW` | `PASS` if 100% of records have `VALID` provenance and trail is non-empty; otherwise `REVIEW`. |
| **Article 12**<br>*(Record-Keeping)* | High-risk AI systems must enable automatic, tamper-evident recording of events throughout their lifecycle. | `PASS`<br>`FAIL` | `PASS` if cryptographic hash chain is intact; `FAIL` if the chain is broken or tampered with. |
| **Article 13**<br>*(Transparency)* | System operation must be transparent, enabling deployers to interpret and trace system context. | `PASS`<br>`REVIEW` | `PASS` if non-empty trail has tracked sources (`ContextSource`); otherwise `REVIEW`. |
| **Article 14**<br>*(Human Oversight)* | Systems must allow natural persons to effectively oversee and intervene in AI operations. | `PRESENT` | Always marked `PRESENT` because the `trail.annotate()` human review API is available. |

---

## Report Formats

### 1. JSON Report Structure

The JSON format provides complete technical details:

```json
{
  "title": "Provena Governance Compliance Report",
  "generated_at": "2026-10-10T12:00:00+00:00",
  "compliance_score": 100,
  "checks_passed": 4,
  "checks_total": 4,
  "issues": [],
  "chain_integrity": {
    "status": "INTACT",
    "records_verified": 42,
    "broken_at": null
  },
  "summary": {
    "total_records": 42,
    "provenance": {
      "VALID": 42
    },
    "freshness": {
      "FRESH": 40,
      "UNKNOWN": 2
    },
    "sources": {
      "retriever": 30,
      "tool": 12
    },
    "signed": true
  },
  "eu_ai_act": {
    "article_10": {
      "name": "Data Governance",
      "status": "PASS",
      "detail": "42/42 records with valid provenance"
    },
    "article_12": {
      "name": "Record-Keeping",
      "status": "PASS",
      "detail": "Chain intact (42 records)"
    },
    "article_13": {
      "name": "Transparency",
      "status": "PASS",
      "detail": "42 records with source tracking"
    },
    "article_14": {
      "name": "Human Oversight",
      "status": "PRESENT",
      "detail": "Annotation API available (trail.annotate)"
    }
  }
}
```

### 2. Text Report Structure

The text format renders cleanly in console logs or CI/CD summaries:

```text
============================================================
           Provena Governance Compliance Report
============================================================
Generated: 2026-10-10T12:00:00+00:00

COMPLIANCE SCORE: 100% (4/4 checks passed)

CHAIN INTEGRITY:
  Status:   INTACT
  Verified: 42 records

SUMMARY:
  Records:  42
  Signed:   Yes

  Provenance:
    VALID        42
  Freshness:
    FRESH        40
    UNKNOWN      2
  Sources:
    retriever    30
    tool         12

EU AI ACT COMPLIANCE:
  ARTICLE_10   Data Governance      [PASS] 42/42 records with valid provenance
  ARTICLE_12   Record-Keeping       [PASS] Chain intact (42 records)
  ARTICLE_13   Transparency         [PASS] 42 records with source tracking
  ARTICLE_14   Human Oversight      [PRESENT] Annotation API available (trail.annotate)
============================================================
```

### 3. PDF Report Structure

The generated PDF report provides an executive summary:

- **Header**: Centered report title and UTC timestamp.
- **Score Banner**: Overall compliance score and check tally.
- **Issues Section**: Flagged findings with article references.
- **Chain Integrity**: Tamper verification status and total records.
- **Audit Summary**: Breakdown by provenance status, freshness status, and source types.
- **Regulatory Table**: Status (`PASS`, `REVIEW`, `FAIL`) and details for Articles 10, 12, 13, and 14.

---

## Command-Line Interface (`provena report`)

You can generate compliance reports directly from the CLI without writing Python code:

```bash
provena [GLOBAL_OPTIONS] report [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--format TEXT` | | `json` | Output format: `json`, `text`, `csv`, or `pdf` |
| `--output PATH` | `-o` | *(stdout)* | Write report content to a file |

### Examples

#### 1. Quick JSON Report (Terminal)

```bash
provena --db audit.db report
```

#### 2. Formatted Text Report to File

```bash
provena --db audit.db report --format text --output compliance_summary.txt
```

#### 3. Executive PDF Report

```bash
provena --db audit.db report --format pdf --output provena-compliance.pdf
```

Output:
```text
PDF report written to provena-compliance.pdf
```

*(If `--output` is omitted for PDF format, the CLI defaults to saving to `provena-report.pdf`)*.

#### 4. CSV Audit Data Export

```bash
provena --db audit.db report --format csv --output audit_dump.csv
```

---

## Interpreting & Improving Compliance

### Score Interpretation

- **100% (4/4 Checks Passed)**: Fully compliant technical audit trail. Cryptographic chain intact, full source attribution, fresh context, and HMAC signing active.
- **75% (3/4 Checks Passed)**: Minor gap. Common when HMAC signing key was not configured (`Trail is not HMAC-signed`).
- **50% or Below**: Requires investigation. Indicates missing provenance metadata on inputs or broken hash chain integrity.

### Remediation Checklist

1. **Unsigned Trail (Art. 12)**: Provide `signing_key="..."` to `ContextTrail` or export `PROVENA_SIGNING_KEY`.
2. **Incomplete Provenance (Art. 10)**: Ensure retrievers and tools attach `ProvenanceMetadata` with `source_url` and `created_at`.
3. **Stale Context**: Check retriever indexing freshness or decrease `max_age_days`.
4. **Broken Hash Chain (Art. 12)**: A broken chain indicates database tampering or file corruption. Investigate record ID referenced in `broken_at`.

---

## Next Steps

- [Retention Policy Guide](retention.md) -- Managing record lifecycle and 180-day retention
- [Chain Verification Guide](verification.md) -- Detailed hash chain verification mechanics
- [EU AI Act Compliance Guide](../compliance/eu-ai-act.md) -- Full legal analysis and penalties
