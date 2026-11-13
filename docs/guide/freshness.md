# Freshness Checking

Stale context is a silent failure mode in AI agent systems. Research shows that
feeding outdated information to LLMs degrades output quality by 12-15%, often
without any visible error. Provena detects stale context automatically and flags
it in the audit trail so you can act on it.

## Two Detection Methods

Provena uses two complementary strategies to determine content age:

1. **Metadata timestamps** -- If the entry has `ProvenanceMetadata` with a
   `created_at` field, that date is used directly. This is the most reliable
   method.

2. **Regex temporal detection** -- When no metadata timestamp is available,
   Provena scans the content text for date patterns (ISO dates, month-year
   phrases, quarter references, and more). This catches staleness even when
   upstream sources do not provide structured metadata.

Metadata timestamps always take priority. If `created_at` is present,
content-based detection is skipped entirely.

## The max_age_days Parameter

The `max_age_days` parameter sets the staleness threshold. Content older than
this many days is marked `STALE`. The default is 90 days.

```python
from provena import ContextTrail

# Default: 90 days
trail = ContextTrail(backend="memory")

# Strict freshness: 30 days
trail_strict = ContextTrail(backend="memory", max_age_days=30)

# Relaxed freshness: 365 days
trail_relaxed = ContextTrail(backend="memory", max_age_days=365)
```

## Freshness Verdicts

Every logged entry receives one of three freshness verdicts:

| Verdict     | Meaning                                                    |
|-------------|------------------------------------------------------------|
| **FRESH**   | Content age is within the `max_age_days` threshold          |
| **STALE**   | Content age exceeds the threshold                           |
| **UNKNOWN** | No timestamp metadata or temporal markers were detected, or all detected dates are genuinely in the future (beyond the one-day tolerance) |

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(backend="memory", max_age_days=90)

# FRESH -- created 10 days ago
trail.log(
    content="Recent deployment guide.",
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://docs.example.com/deploy",
        created_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    ),
)

# STALE -- created over 90 days ago
trail.log(
    content="Legacy migration notes.",
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://docs.example.com/migrate",
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    ),
)

# UNKNOWN -- no timestamp, no temporal markers in content
trail.log(
    content="Some context with no date information.",
    source="retriever",
)

summary = trail.summary()
print(summary["freshness"])
# {'FRESH': 1, 'STALE': 1, 'UNKNOWN': 1}
```

## Future-Date Tolerance

Dates that fall more than one day after the reference time are treated as
genuinely future-dated and cannot be used to verify freshness, so they return
`UNKNOWN`. This prevents a future projection or a clock-skewed timestamp from
making old content appear fresh.

A one-day tolerance absorbs minor clock skew: a date within one day of the
reference time (including a date exactly one day ahead, or equal to the
reference time) is treated as current and evaluated normally.

When content contains multiple temporal markers, genuinely future markers are
ignored and freshness is evaluated from the usable past or current markers (the
newest usable date wins). If at least one usable marker exists, the verdict
details list the ignored future-dated marker(s). If every detected marker is
genuinely future-dated, the verdict is `UNKNOWN`.

## Temporal Patterns Detected

When metadata timestamps are absent, Provena scans content text for these
patterns:

| Pattern Type       | Examples                                        |
|--------------------|-------------------------------------------------|
| ISO dates          | `2023-06-15`, `2024/01/30`                      |
| Month-year         | `January 2024`, `Mar 2023`, `September 2025`    |
| Quarters           | `Q3 2024`, `Q1 2025`                            |
| Half-years         | `H1 2025`, `H2 2024`                            |
| Contextual years   | `as of 2023`, `since 2024`, `circa 2025`        |
| Update markers     | `last updated: March 2024`, `published on 2024-01-15`, `revised December 2023`, `effective date: 2024-03-01` |

```python
trail = ContextTrail(backend="memory", max_age_days=180)

# Temporal detection finds "Q3 2024" in the content
record = trail.log(
    content="This report covers Q3 2024 financial results.",
    source="retriever",
)
# Freshness is evaluated based on Q3 2024 (July 1, 2024)

# "last updated: March 2024" is detected
record = trail.log(
    content="API reference (last updated: March 2024) for the billing service.",
    source="tool:api_docs",
)
# Freshness is evaluated based on March 2024
```

!!! tip "Newest usable date wins"
    When multiple temporal markers are found in a single piece of content,
    Provena uses the **newest** detected date for the freshness calculation
    (`max` of the detected dates). Genuinely future-dated markers (more than
    one day ahead of the reference time) are excluded from the selection, so a
    future projection cannot hide the last real update date or make stale
    content appear fresh. When future markers are ignored, the verdict details
    list them.

## Disabling Temporal Detection

If regex-based detection produces false positives for your content (for example,
documents that discuss historical dates), disable it:

```python
trail = ContextTrail(
    backend="memory",
    temporal_detection=False,
)

# This content mentions "2019" but it will NOT be flagged as STALE
# because temporal detection is off. Verdict will be UNKNOWN.
record = trail.log(
    content="The protocol was first standardized in 2019.",
    source="retriever",
)
```

With temporal detection disabled, only `ProvenanceMetadata.created_at`
timestamps are used. Entries without metadata timestamps receive an UNKNOWN
verdict.

## Priority: Metadata Overrides Content Detection

When both a `created_at` metadata timestamp and content temporal markers are
present, the metadata timestamp is used and content scanning is skipped:

```python
from datetime import datetime, timezone

trail = ContextTrail(backend="memory", max_age_days=90)

# The content mentions "2019" but the metadata says it was created recently.
# Freshness is based on created_at, not the content text.
record = trail.log(
    content="The TCP/IP protocol was standardized in 2019.",
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://docs.example.com/networking",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ),
)
# Verdict: FRESH (based on metadata, not content)
```

## Checking Freshness in trail.summary()

The `summary()` method includes a freshness breakdown:

```python
summary = trail.summary()
print(summary["freshness"])
# {'FRESH': 25, 'STALE': 3, 'UNKNOWN': 12}
```

You can also query records filtered by freshness status:

```python
stale_records = trail.query(freshness_status="STALE", limit=50)
for record in stale_records:
    print(f"Stale: {record['source_name']} ({record['timestamp']})")
```

!!! tip "Monitoring freshness over time"
    Track the ratio of STALE to FRESH entries in your trail summary. A rising
    STALE count indicates that your knowledge sources need updating. Combine
    with the CLI `provena --db audit.db report` command for periodic compliance
    reports.
