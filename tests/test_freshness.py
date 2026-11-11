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

    def test_naive_now_override_treated_as_utc(self):
        # Regression for #147: passing a naive `now` override previously
        # raised "can't subtract offset-naive and offset-aware datetimes"
        # because created_at is normalized to UTC-aware internally. A naive
        # `now` must be normalized the same way instead of crashing.
        aware_created = datetime(2025, 1, 1, tzinfo=timezone.utc)
        naive_now = datetime(2025, 1, 11)  # 10 days later, no tzinfo
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=aware_created)

        result = checker.check(entry, now=naive_now)
        assert result.status == "FRESH"
        assert "10 days" in result.details

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

    def test_year_context_in(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        content = "This pricing guide was written in 2019."
        entry = _entry(content=content)
        result = checker.check(entry, content=content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.year == 2019

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


class TestFreshnessCheckerFutureDates:
    """Regression tests for future date handling (GitHub issue: future dates incorrectly marked FRESH)."""

    def test_future_provenance_date_returns_unknown(self):
        """Future provenance created_at should return UNKNOWN, not FRESH."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        future_date = now + timedelta(days=30)
        entry = _entry(created_at=future_date)
        result = checker.check(entry, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()
        assert result.detected_date == future_date

    def test_future_temporal_marker_returns_unknown(self):
        """Future temporal markers in content should return UNKNOWN, not FRESH."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "As of 2030, the policy will be updated"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()
        assert result.detected_date is not None
        assert result.detected_date.year == 2030

    def test_future_iso_date_returns_unknown(self):
        """Future ISO dates in content should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "Published on 2030-06-15"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()

    def test_future_month_year_returns_unknown(self):
        """Future month-year in content should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "Updated January 2030"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()

    def test_future_quarter_returns_unknown(self):
        """Future quarter in content should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "Q3 2030 report"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()

    def test_future_half_year_returns_unknown(self):
        """Future half-year in content should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "H2 2030 projections"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()

    def test_future_year_context_returns_unknown(self):
        """Future year context (as of/in/since) should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        for phrase in [
            "as of 2030",
            "in 2030",
            "since 2030",
            "from 2030",
            "circa 2030",
        ]:
            future_content = f"{phrase}, data shows growth"
            result = checker.check(entry, content=future_content, now=now)
            assert result.status == "UNKNOWN", f"Failed for phrase: {phrase}"
            assert "future" in result.details.lower()

    def test_future_update_marker_returns_unknown(self):
        """Future update markers should return UNKNOWN."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        future_content = "last updated: June 2030"
        result = checker.check(entry, content=future_content, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()

    def test_exactly_now_provenance_date_is_fresh(self):
        """Provenance date exactly at 'now' should be FRESH."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now)
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_past_provenance_date_still_fresh(self):
        """Past provenance dates within threshold should still be FRESH."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        past_date = now - timedelta(days=30)
        entry = _entry(created_at=past_date)
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_past_temporal_marker_still_stale(self):
        """Past temporal markers beyond threshold should still be STALE."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        past_content = "As of 2020, the policy was updated"
        result = checker.check(entry, content=past_content, now=now)
        assert result.status == "STALE"
        assert result.detected_date is not None
        assert result.detected_date.year == 2020

    def test_mixed_past_and_future_markers_uses_past_marker(self):
        """Mixed past and future markers: genuinely future markers are ignored,
        freshness is evaluated from the usable past marker, and the ignored
        future marker is mentioned in the details."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        # 2025-06-15 is old (outside threshold); 2030-01-01 is genuinely future.
        mixed_content = "Updated 2025-06-15, projected 2030-01-01"
        result = checker.check(entry, content=mixed_content, now=now)
        assert result.status == "STALE", (
            f"Expected STALE, got {result.status}: {result.details}"
        )
        assert "2030-01-01" in result.details
        assert result.detected_date is not None
        assert result.detected_date.year == 2025

    def test_recent_past_marker_with_future_marker_uses_past(self):
        """A recent past marker combined with a future marker uses the past
        marker; the future marker is ignored and noted in details."""
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        mixed_content = "Updated 2025-12-20, projected 2030-01-01"
        result = checker.check(entry, content=mixed_content, now=now)
        assert result.status == "FRESH", (
            f"Expected FRESH, got {result.status}: {result.details}"
        )
        assert "2030-01-01" in result.details
        assert result.detected_date.year == 2025


class TestFreshnessCheckerFutureTolerance:
    """One-day future-date tolerance and mixed past/future marker handling."""

    def test_metadata_date_more_than_one_day_future_returns_unknown(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now + timedelta(days=2))
        result = checker.check(entry, now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()
        assert result.detected_date == now + timedelta(days=2)

    def test_content_marker_more_than_one_day_future_returns_unknown(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        result = checker.check(entry, content="As of 2030, the policy applies", now=now)
        assert result.status == "UNKNOWN"
        assert "future" in result.details.lower()
        assert result.detected_date.year == 2030

    def test_metadata_date_within_one_day_future_handled_normally(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now + timedelta(hours=12))
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_content_marker_within_one_day_future_handled_normally(self):
        now = datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        # 2026-01-02 is 18 hours ahead of now: within the one-day tolerance.
        result = checker.check(entry, content="Updated on 2026-01-02", now=now)
        assert result.status == "FRESH"

    def test_date_exactly_one_day_future_follows_tolerance_boundary(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        # Exactly one day ahead is within the tolerance: handled normally (FRESH).
        entry = _entry(created_at=now + timedelta(days=1))
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

        # Just past one day is genuinely future-dated: UNKNOWN.
        entry = _entry(created_at=now + timedelta(days=1, seconds=1))
        result = checker.check(entry, now=now)
        assert result.status == "UNKNOWN"

    def test_date_equal_to_reference_retains_fresh(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(created_at=now)
        result = checker.check(entry, now=now)
        assert result.status == "FRESH"

    def test_all_detected_markers_in_future_return_unknown(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        checker = FreshnessChecker(max_age_days=90)
        entry = _entry(content="test")
        result = checker.check(
            entry,
            content="As of 2030, revised in 2031, from 2032",
            now=now,
        )
        assert result.status == "UNKNOWN"
        assert "genuinely future-dated" in result.details
        assert result.detected_date is not None
        assert result.detected_date.year == 2032
