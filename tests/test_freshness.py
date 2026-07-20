from __future__ import annotations

from datetime import datetime, timedelta, timezone

from provena.models import (
    ContextEntry,
    ContextSource,
    ProvenanceMetadata,
)
from provena.validators.freshness import FreshnessChecker


def _entry(
    content: str = "test",
    created_at: datetime | None = None,
    source_url: str | None = None,
) -> ContextEntry:
    prov = None
    if created_at is not None or source_url is not None:
        prov = ProvenanceMetadata(source_url=source_url, created_at=created_at)
    return ContextEntry.create(
        content=content,
        source=ContextSource.RETRIEVER,
        source_name="test",
        provenance=prov,
    )


class TestFreshnessCheckerMetadata:
    def test_fresh_content(self):
        now = datetime.now(timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now - timedelta(days=10))
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"
        assert result.detected_date is not None
        assert "10 days" in result.details

    def test_stale_content(self):
        now = datetime.now(timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now - timedelta(days=180))
        result = checker.check(entry, now=now)
        assert result.status == "STALE"
        assert "180 days" in result.details
        assert "threshold" in result.details

    def test_exactly_at_threshold(self):
        now = datetime.now(timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now - timedelta(days=90))
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_one_day_over_threshold(self):
        now = datetime.now(timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now - timedelta(days=91))
        result = checker.check(entry, now=now)
        assert result.status == "STALE"

    def test_custom_threshold(self):
        now = datetime.now(timezone.utc)
        checker = FreshnessChecker(max_age_days=30)
        entry = _entry(created_at=now - timedelta(days=45))
        result = checker.check(entry, now=now)
        assert result.status == "STALE"

    def test_naive_datetime_treated_as_utc(self):
        now = datetime.now(timezone.utc)
        naive = now - timedelta(days=10)
        naive = naive.replace(tzinfo=None)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=naive)
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_no_provenance_returns_unknown(self):
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry()
        result = checker.check(entry, content=None)
        assert result.status == "UNKNOWN"

    def test_provenance_without_created_at(self):
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(source_url="https://example.com")
        result = checker.check(entry, content=None)
        assert result.status == "UNKNOWN"


class TestFreshnessCheckerTemporal:
    def test_iso_date_stale(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="Data as of 2025-01-15 shows the results.")
        result = checker.check(
            entry, content="Data as of 2025-01-15 shows the results.", now=now
        )
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.year == 2025
        assert result.detected_date.month == 1

    def test_iso_date_fresh(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="Updated on 2026-06-01 with latest data.")
        result = checker.check(
            entry, content="Updated on 2026-06-01 with latest data.", now=now
        )
        assert result.status == "FRESH"

    def test_iso_date_with_slashes(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="Report from 2024/03/15 quarterly review.")
        result = checker.check(
            entry, content="Report from 2024/03/15 quarterly review.", now=now
        )
        assert result.status == "STALE"

    def test_month_year_stale(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Published in January 2025 by the research team."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.month == 1
        assert result.detected_date.year == 2025

    def test_month_year_abbreviated(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Last revised in Mar 2024."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"

    def test_month_year_fresh(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Updated June 2026 with the latest figures."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "FRESH"

    def test_last_updated_marker(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Last updated: March 2024."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.month == 3
        assert result.detected_date.year == 2024

    def test_published_on_marker(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Published on 2024-01-15."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.year == 2024
        assert result.detected_date.month == 1
        assert result.detected_date.day == 15

    def test_revised_marker(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Revised December 2023."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.month == 12
        assert result.detected_date.year == 2023

    def test_effective_date_marker(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Effective date: 2024-03-01."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.year == 2024
        assert result.detected_date.month == 3
        assert result.detected_date.day == 1

    def test_quarter_stale(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Performance in Q3 2024 exceeded expectations."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.month == 7

    def test_quarter_fresh(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=120)
        content = "Q2 2026 results are in."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "FRESH"
        assert result.detected_date.month == 4

    def test_half_year(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "H1 2025 financial report."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.month == 1

    def test_year_context_as_of(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "As of 2023, the policy was still in effect."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date.year == 2023

    def test_year_context_since(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Available since 2024 in all regions."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"

    def test_no_temporal_markers(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "The product costs $99 and is available in blue."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "UNKNOWN"

    def test_temporal_detection_disabled(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90, temporal_detection=False)
        content = "As of 2020, the old data still applies."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "UNKNOWN"

    def test_multiple_dates_uses_newest(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Updated 2026-06-01 based on original data from 2023-01-15."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "FRESH"
        assert result.detected_date.year == 2026

    def test_bytes_content_skips_temporal(self):
        checker = FreshnessChecker(max_age_days=90)
        entry = ContextEntry.create(
            content=b"\x00\x01\x02",
            source=ContextSource.TOOL,
            source_name="binary",
        )
        result = checker.check(entry, content=None)
        assert result.status == "UNKNOWN"


class TestFreshnessCheckerMetadataPriority:
    def test_metadata_overrides_content(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(
            content="As of 2020, very old data.",
            created_at=now - timedelta(days=5),
        )
        result = checker.check(entry, content="As of 2020, very old data.", now=now)
        assert result.status == "FRESH"
        assert "5 days" in result.details


class TestFreshnessCheckerProperties:
    def test_max_age_days(self):
        checker = FreshnessChecker(max_age_days=180)
        assert checker.max_age_days == 180


class TestFreshnessCheckerEdgeCases:
    def test_invalid_date_feb_30(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Published 2025-02-30 edition."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "UNKNOWN"

    def test_empty_content(self):
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="")
        result = checker.check(entry, content="")
        assert result.status == "UNKNOWN"

    def test_content_with_version_numbers_not_detected(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Using Python 3.12 with library version 2024.1.0"
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "UNKNOWN"

    def test_september_abbreviation_sept(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "Released Sept 2024."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date.month == 9
