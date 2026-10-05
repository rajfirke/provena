# Compliance Reports

`generate_report()` scores one trail against four checks and maps the result
onto EU AI Act Articles 10, 12, 13, and 14. The same data is rendered as
JSON, text, or PDF.

## Generate a report

```python
from provena import ContextTrail
from provena.report import generate_pdf_report, generate_report

trail = ContextTrail(storage_path="audit.db")

text = generate_report(trail, format="text")
payload = generate_report(trail, format="json")
pdf_bytes = generate_report(trail, format="pdf")

generate_pdf_report(trail, "compliance.pdf")
```

PDF output needs the `pdf` extra (`pip install provena[pdf]`), which
installs `fpdf2`.

## Scoring

The score is `checks_passed / 4`:

| Check | Passes when |
|---|---|
| Chain integrity | `verify_chain().intact` is true |
| Provenance | Every record is `VALID` |
| Freshness | At most 10% of records are `STALE` |
| Signing | The trail uses an HMAC signing key |

An empty trail does not pass the provenance, freshness, or transparency
checks. Article 12 is `FAIL` when the chain is broken and `PASS` when it is
intact. Article 10 is `REVIEW` unless every record has valid provenance.
Article 13 is `PASS` when the trail has at least one record. Article 14 is
`PRESENT` because `trail.annotate()` is available for human review.

When every check passes, the text report omits the `ISSUES:` section.

## CLI

```bash
provena --db audit.db report
provena --db audit.db report --format text
provena --db audit.db report --format pdf -o compliance.pdf
```

`--format pdf` writes `provena-report.pdf` when `-o` is omitted. `--format
csv` exports raw trail rows via `trail.export()` rather than the scored
compliance report.
