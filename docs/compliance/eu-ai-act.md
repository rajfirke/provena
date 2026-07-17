# EU AI Act Compliance

The EU AI Act (Regulation 2024/1689) establishes the world's first comprehensive
legal framework for artificial intelligence. For organizations deploying high-risk
AI systems, context governance is no longer optional -- it is a legal obligation.
Provena maps directly to six key articles of the regulation, providing the
technical controls needed to demonstrate compliance.

!!! warning "Enforcement is active"

    The EU AI Act entered into force on 1 August 2024. Obligations for high-risk
    AI systems apply from 2 August 2026. Organizations that fail to implement
    adequate governance controls face fines of up to EUR 15 million or 3% of
    global annual turnover.

---

## Article-by-Article Mapping

### Article 9 -- Risk Management

**What the article requires.** Providers of high-risk AI systems must establish,
implement, document, and maintain a risk management system. This system must
identify and analyze known and reasonably foreseeable risks, estimate and evaluate
those risks, and adopt appropriate and targeted risk management measures.

**How Provena satisfies it.** Provena's three-layer governance pipeline --
provenance validation, freshness checking, and hash-chained audit trails --
constitutes a systematic risk management system for context inputs. Every context
entry is validated against configurable provenance requirements
(`ProvenanceValidator`), checked for staleness (`FreshnessChecker`), and recorded
in a tamper-evident chain (`ChainHasher`). Validation results are classified as
`VALID`, `INCOMPLETE`, or `MISSING` for provenance, and `FRESH`, `STALE`, or
`UNKNOWN` for freshness, enabling quantitative risk assessment.

```python
trail = ContextTrail(
    required_fields=["source_url", "author", "created_at"],
    max_age_days=90,
    strict_mode=True,  # Governance failures raise exceptions
)
```

### Article 10 -- Data Governance

**What the article requires.** Training, validation, and testing datasets must
be subject to appropriate data governance and management practices. Data must be
relevant, sufficiently representative, and free of errors. Datasets must take into
account the specific geographical, contextual, behavioral, or functional setting
of the system.

**How Provena satisfies it.** The `ProvenanceValidator` ensures that every context
input carries source metadata -- origin URL, author, creation date, and version.
Inputs without provenance are flagged as `MISSING`; inputs with incomplete
metadata are flagged as `INCOMPLETE`. The `FreshnessChecker` verifies timestamps
against a configurable threshold (`max_age_days`) and uses temporal pattern
detection to identify date references in content text, catching stale data even
when metadata timestamps are absent.

```python
from provena.models import ProvenanceMetadata

provenance = ProvenanceMetadata(
    source_url="https://api.example.com/v2/data",
    author="data-engineering-team",
    created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    version="2.1.0",
)

record = trail.log(content, source="retriever", provenance=provenance)
# record.provenance_result.status -> "VALID"
# record.freshness_result.status  -> "FRESH"
```

### Article 12 -- Record-Keeping

**What the article requires.** High-risk AI systems must be designed and developed
with capabilities enabling the automatic recording of events (logging) relevant to
identifying situations that may result in risk. Logging must enable traceability of
the system's operation throughout its lifecycle.

**How Provena satisfies it.** Provena implements a Merkle-style hash chain using
SHA-256 (or HMAC-SHA256 when a signing key is provided). Each `TrailRecord`
contains:

- A SHA-256 content hash of the input
- Provenance validation status and missing fields
- Freshness check status with detected dates
- A chain hash linking to the previous record
- Timestamp, source type, and arbitrary metadata

The chain is tamper-evident: modifying any record invalidates all subsequent hashes.
The `verify_chain()` method performs full-chain verification, returning a
`ChainVerdict` that identifies the exact record where integrity was broken.

```python
verdict = trail.verify_chain()
assert verdict.intact  # True if no tampering detected
# verdict.broken_at    -> record ID where chain broke (if any)
# verdict.total_records -> number of records verified
```

!!! note "Retention requirements"

    Article 12 requires log retention for a period appropriate to the intended
    purpose of the high-risk AI system, which is at least six months unless
    provided otherwise in applicable Union or national law. Provena's SQLite
    backend provides persistent storage. For production deployments, enable the
    OpenTelemetry exporter to forward governance events to durable,
    centrally-managed storage systems.

### Article 13 -- Transparency

**What the article requires.** High-risk AI systems must be designed and developed
in such a way as to ensure that their operation is sufficiently transparent to
enable deployers to interpret the system's output and use it appropriately.

**How Provena satisfies it.** Every governance event recorded by Provena includes
an explanation of what was validated and why. Provenance results include the list
of missing fields. Freshness results include the detected date, the content age
in days, and the threshold that was applied. Source attribution (`ContextSource`
enum: `RETRIEVER`, `TOOL`, `AGENT`, `MEMORY`, `MCP`, `CUSTOM`) identifies the
origin type for every input. The `trail.summary()` method produces aggregate
breakdowns by provenance status, freshness status, and source type.

```python
summary = trail.summary()
# {
#   "total": 142,
#   "provenance": {"VALID": 118, "INCOMPLETE": 19, "MISSING": 5},
#   "freshness": {"FRESH": 130, "STALE": 8, "UNKNOWN": 4},
#   "sources": {"retriever": 95, "tool": 30, "agent": 17},
#   "signed": True
# }
```

### Article 14 -- Human Oversight

**What the article requires.** High-risk AI systems must be designed and developed
in such a way as to be effectively overseen by natural persons during their period
of use. Human oversight measures must enable the individuals to whom oversight is
assigned to properly understand the relevant capacities and limitations of the
system and to intervene or interrupt the system as necessary.

**How Provena satisfies it.** The audit trail records both accepted and flagged
context inputs, with detailed reasons for each governance decision. The
`trail.annotate()` method allows human reviewers to attach oversight notes to
any record, creating a documented chain of human judgment:

```python
# Reviewer examines a flagged record
flagged = trail.query(provenance_status="INCOMPLETE", limit=10)

for record in flagged:
    # Review and annotate
    trail.annotate(
        record_id=record["id"],
        note="Approved: source verified via internal registry",
        reviewer="compliance-officer@example.com",
    )
```

The `query()` method supports filtering by provenance status, freshness status,
source type, and time range, enabling compliance officers to focus on records
that require human review.

### Article 26 -- Deployer Obligations

**What the article requires.** Deployers of high-risk AI systems must monitor the
operation of the system on the basis of the instructions of use. They must keep
logs automatically generated by the system, to the extent such logs are under
their control, for a period appropriate to the intended purpose, and for at least
six months.

**How Provena satisfies it.** Provena's SQLite backend (`storage_path` parameter)
writes all governance events to persistent local storage. For centralized log
management and long-term retention, the OpenTelemetry exporter forwards governance
spans to any OTel-compatible backend:

```python
trail = ContextTrail(
    storage_path="/var/lib/provena/audit.db",
    otel_enabled=True,
    otel_service_name="production-rag-pipeline",
)
```

!!! warning "Six-month minimum retention"

    The six-month retention requirement under Article 26 is a legal floor.
    Configure your OTel collector and storage backend to retain governance
    events for at least this period. Organizations subject to sector-specific
    regulations (e.g., financial services, healthcare) may face longer retention
    requirements.

---

## Compliance Mapping

The following table maps specific EU AI Act requirements to Provena features:

| EU AI Act Requirement | Article | Provena Feature |
|---|---|---|
| Systematic risk identification and mitigation | Art. 9 | Three-layer validation pipeline (provenance, freshness, chain integrity) |
| Data governance and management practices | Art. 10 | `ProvenanceValidator` with configurable required fields |
| Data quality and relevance verification | Art. 10 | `FreshnessChecker` with temporal pattern detection |
| Automatic event logging | Art. 12 | SHA-256 hash-chained `TrailRecord` for every context input |
| Tamper-evident record-keeping | Art. 12 | Merkle-style chain with `verify_chain()` integrity verification |
| Forensic reconstruction capability | Art. 12 | Full chain replay via `query()` and `export()` (JSON/CSV) |
| Operational transparency | Art. 13 | Governance event details: validation status, missing fields, detected dates |
| Source attribution | Art. 13 | `ContextSource` enum and source metadata on every record |
| Human oversight enablement | Art. 14 | `trail.annotate()` for reviewer decisions on flagged records |
| Flagged input visibility | Art. 14 | `query(provenance_status="INCOMPLETE")` filtering |
| Log retention (6-month minimum) | Art. 26 | SQLite persistent backend + OTel export to durable storage |
| Operational monitoring | Art. 26 | `trail.health()` and `trail.summary()` for system status |

---

## Penalty Structure

The EU AI Act establishes a tiered penalty framework. Understanding which tier
applies to your obligations is essential for risk assessment.

| Tier | Maximum Fine | Scope | Examples |
|---|---|---|---|
| **Tier 1** | EUR 35 million or 7% of global annual turnover | Prohibited AI practices | Social scoring, real-time biometric identification in public spaces |
| **Tier 2** | EUR 15 million or 3% of global annual turnover | High-risk AI system obligations | Inadequate risk management, missing audit trails, insufficient data governance |
| **Tier 3** | EUR 7.5 million or 1% of global annual turnover | Misleading information | Providing incorrect or incomplete information to notified bodies or authorities |

!!! warning "Provena's territory is Tier 2"

    Most obligations addressed by Provena fall under Tier 2. Failure to maintain
    adequate data governance (Article 10), record-keeping (Article 12), or
    deployer log retention (Article 26) exposes organizations to fines of up to
    EUR 15 million or 3% of global annual turnover, whichever is higher.

---

## Enforcement Timeline

| Date | Milestone |
|---|---|
| 1 August 2024 | Regulation enters into force |
| 2 February 2025 | Prohibited AI practices apply |
| 2 August 2025 | Obligations for general-purpose AI models apply |
| 2 August 2026 | **High-risk AI system obligations apply** (Provena's primary scope) |
| 2 August 2027 | Full enforcement for all AI systems, including those in Annex I |

---

## Enforcement Case Studies

!!! warning "These cases illustrate the real-world consequences of inadequate context governance"

### Case 1: Frankfurt Wealth Management Firm (2027)

A Frankfurt-based wealth management firm received a EUR 4.5 million fine from the
German Federal Financial Supervisory Authority (BaFin) under EU AI Act
Article 10 and Article 12 obligations.

**What happened.** The firm deployed a RAG-based advisory system that retrieved
financial research reports and regulatory guidance to generate client
recommendations. An internal audit revealed that the retrieval pipeline was
serving research reports up to 14 months old without any staleness detection.
The system cited a withdrawn ECB guideline in three client portfolios.

**What was missing.**

- No provenance validation on retrieved documents -- the system could not
  distinguish between current and superseded regulatory guidance
- No freshness checking -- stale research reports were treated identically to
  current ones
- No audit trail -- when regulators requested evidence of what context inputs
  informed specific client recommendations, the firm could not reconstruct the
  decision chain

**How Provena would have prevented it.** The `FreshnessChecker` would have
flagged 14-month-old reports as `STALE`. The `ProvenanceValidator` would have
required source URLs and version identifiers, making it possible to detect when
a cited guideline was withdrawn. The hash-chained audit trail would have provided
the forensic reconstruction capability that regulators demanded.

### Case 2: French Insurance Company (2027)

A French insurance company had its AI-assisted claims processing system halted
by the CNIL (Commission Nationale de l'Informatique et des Libertes) for
violations of Article 12 and Article 26.

**What happened.** The company deployed an agentic AI system that retrieved
policy documents, claims history, and medical guidelines to assist claims
adjusters. The system cited a withdrawn clinical guideline in a denial decision,
which was challenged by the policyholder. During the resulting investigation,
regulators discovered that the company's log retention policy was 30 days --
well below the six-month minimum required by Article 26.

**What was missing.**

- No version tracking on retrieved clinical guidelines -- the system could not
  detect that the guideline had been superseded
- 30-day log retention violated the six-month minimum under Article 26
- No tamper-evident logging -- the company could not demonstrate that logs had
  not been altered after the complaint was filed

**How Provena would have prevented it.** The `ProvenanceMetadata.version` field
and freshness checking would have flagged the withdrawn guideline. The SQLite
backend with OTel export provides persistent, tamper-evident storage that meets
the six-month retention requirement. The `verify_chain()` method provides
cryptographic proof that logs have not been modified.

---

## Next Steps

- [OWASP ASI06: Context Poisoning](owasp-asi06.md) -- Security controls for
  context integrity
- [OpenTelemetry Integration](../integrations/opentelemetry.md) -- Configuring
  OTel export for durable log retention
- [Provenance Validation Guide](../guide/provenance.md) -- Detailed configuration
  for provenance requirements
