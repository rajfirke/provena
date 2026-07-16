from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from provena.models import ContextEntry, FreshnessResult

_MONTH_MAP: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH_NAMES = "|".join(_MONTH_MAP.keys())

_QUARTER_START = {1: 1, 2: 4, 3: 7, 4: 10}


class _TemporalPatterns:
    """Pre-compiled regex patterns for temporal detection in content."""

    __slots__ = ("half_year", "iso_date", "month_year", "quarter", "year_context","update_marker",)

    def __init__(self) -> None:
        # 2023-06-15 or 2023/06/15
        self.iso_date = re.compile(
            r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b"
        )
        # January 2024, Jan 2024, March 2023
        self.month_year = re.compile(
            rf"\b({_MONTH_NAMES})\s+(20\d{{2}})\b", re.IGNORECASE
        )
        # Q1 2024, Q3 2023
        self.quarter = re.compile(r"\bQ([1-4])\s+(20\d{2})\b", re.IGNORECASE)
        # H1 2023, H2 2024
        self.half_year = re.compile(r"\bH([12])\s+(20\d{2})\b", re.IGNORECASE)
        # "as of 2023", "in 2024", "since 2022", "from 2023", "circa 2024"
        self.year_context = re.compile(
            r"\b(?:as\s+of|since|circa|from|during)\s+(20\d{2})\b", re.IGNORECASE
        )
        # "last updated: March 2024", "published on 2024-01-15",
        # "revised December 2023", "effective date: 2024-03-01"
        self.update_marker = re.compile(
            rf"\b(?:last\s+updated:|published\s+on|revised|effective\s+date:)\s+"
            rf"(({_MONTH_NAMES})\s+(20\d{{2}})|(20\d{{2}}[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])))",
            re.IGNORECASE,
        )

_PATTERNS = _TemporalPatterns()


class FreshnessChecker:
    def __init__(
        self,
        max_age_days: int = 90,
        temporal_detection: bool = True,
    ) -> None:
        self._max_age_days = max_age_days
        self._temporal_detection = temporal_detection
        self._threshold = timedelta(days=max_age_days)

    @property
    def max_age_days(self) -> int:
        return self._max_age_days

    def check(
        self,
        entry: ContextEntry,
        content: str | None = None,
        now: datetime | None = None,
    ) -> FreshnessResult:
        reference = now or datetime.now(timezone.utc)

        result = self._check_metadata(entry, reference)
        if result is not None:
            return result

        if self._temporal_detection and content:
            result = self._check_content(content, reference)
            if result is not None:
                return result

        return FreshnessResult(
            status="UNKNOWN",
            details="No timestamp metadata and no temporal markers detected",
        )

    def _check_metadata(
        self, entry: ContextEntry, now: datetime
    ) -> FreshnessResult | None:
        if entry.provenance is None:
            return None

        created = entry.provenance.created_at
        if created is None:
            return None

        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        age = now - created
        if age <= self._threshold:
            return FreshnessResult(
                status="FRESH",
                details=f"Content age: {age.days} days (threshold: {self._max_age_days})",
                detected_date=created,
            )

        return FreshnessResult(
            status="STALE",
            details=f"Content age: {age.days} days exceeds threshold of {self._max_age_days} days",
            detected_date=created,
        )

    def _check_content(self, content: str, now: datetime) -> FreshnessResult | None:
        dates = self._extract_dates(content)
        if not dates:
            return None

        oldest = min(dates)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)

        age = now - oldest
        if age <= self._threshold:
            return FreshnessResult(
                status="FRESH",
                details=f"Temporal marker detected: {oldest.date().isoformat()} ({age.days} days old)",
                detected_date=oldest,
            )

        return FreshnessResult(
            status="STALE",
            details=f"Temporal marker detected: {oldest.date().isoformat()} ({age.days} days old, threshold: {self._max_age_days} days)",
            detected_date=oldest,
        )

    def _extract_dates(self, content: str) -> list[datetime]:
        dates: list[datetime] = []

        for m in _PATTERNS.iso_date.finditer(content):
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = _safe_date(year, month, day)
            if dt:
                dates.append(dt)

        for m in _PATTERNS.month_year.finditer(content):
            month_num = _MONTH_MAP.get(m.group(1).lower())
            year = int(m.group(2))
            if month_num:
                dt = _safe_date(year, month_num, 1)
                if dt:
                    dates.append(dt)

        for m in _PATTERNS.quarter.finditer(content):
            q, year = int(m.group(1)), int(m.group(2))
            start_month = _QUARTER_START[q]
            dt = _safe_date(year, start_month, 1)
            if dt:
                dates.append(dt)

        for m in _PATTERNS.half_year.finditer(content):
            h, year = int(m.group(1)), int(m.group(2))
            start_month = 1 if h == 1 else 7
            dt = _safe_date(year, start_month, 1)
            if dt:
                dates.append(dt)

        for m in _PATTERNS.year_context.finditer(content):
            year = int(m.group(1))
            dt = _safe_date(year, 1, 1)
            if dt:
                dates.append(dt)

        for m in _PATTERNS.update_marker.finditer(content):
            if m.group(2):
                month_num = _MONTH_MAP.get(m.group(2).lower())
                year = int(m.group(3))
                if month_num:
                    dt = _safe_date(year, month_num, 1)
                    if dt:
                        dates.append(dt)
            else:
                iso_match = _PATTERNS.iso_date.search(m.group(1))
                if iso_match:
                    year, month, day = (
                        int(iso_match.group(1)),
                        int(iso_match.group(2)),
                        int(iso_match.group(3)),
                    )
                    dt = _safe_date(year, month, day)
                    if dt:
                        dates.append(dt)

        return dates


def _safe_date(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
