from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from provena.cli.main import cli
from provena.trail import ContextTrail

BOUNDARY = datetime(2026, 11, 3, tzinfo=timezone.utc)
TIMESTAMPS = [
    BOUNDARY - timedelta(seconds=1),
    BOUNDARY,
    BOUNDARY + timedelta(seconds=1),
]
NAMES = ["before", "boundary", "after"]


def _populate(trail: ContextTrail, *, flush_first: bool = False) -> None:
    with patch("provena.models.datetime") as clock:
        clock.now.side_effect = TIMESTAMPS
        for index, name in enumerate(NAMES):
            assert trail.log(name, source="retriever", source_name=name) is not None
            if flush_first and index == 0:
                trail.flush()


@pytest.fixture(params=["memory", "sqlite", "postgresql"])
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(params=[False, True], ids=["immediate", "buffered"])
def dated_trail(
    request: pytest.FixtureRequest, backend: str, tmp_path: Path
) -> Generator[ContextTrail, None, None]:
    storage_path = str(tmp_path / "trail.db")
    if backend == "postgresql":
        storage_path = request.getfixturevalue("query_pg_url")

    buffered = bool(request.param)
    with ContextTrail(
        backend=backend,
        storage_path=storage_path,
        buffered=buffered,
        buffer_size=100,
        flush_interval=3600,
        strict_mode=True,
    ) as trail:
        _populate(trail, flush_first=buffered)
        yield trail


@pytest.fixture
def query_pg_url() -> Generator[str, None, None]:
    conninfo = os.environ.get("PROVENA_TEST_PG_URL", "")
    if not conninfo:
        pytest.skip("PostgreSQL not available (set PROVENA_TEST_PG_URL)")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    schema = f"query_filters_{uuid4().hex}"
    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        options = conninfo_to_dict(conninfo).get("options", "")
        yield make_conninfo(
            conninfo, options=f"{options} -c search_path={schema}".strip()
        )
    finally:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.parametrize("offset_minutes", [330, -420, 0])
def test_query_matches_the_instant_in_another_timezone(
    dated_trail: ContextTrail, offset_minutes: int
) -> None:
    original = dated_trail.query()
    bound = BOUNDARY.astimezone(timezone(timedelta(minutes=offset_minutes)))

    rows = dated_trail.query(start=bound, end=bound)

    assert [row["source_name"] for row in rows] == ["boundary"]
    assert dated_trail.query() == original


@pytest.mark.parametrize(
    ("use_start", "use_end", "expected"),
    [
        (True, False, ["boundary", "after"]),
        (False, True, ["before", "boundary"]),
        (True, True, ["boundary"]),
    ],
)
def test_query_interprets_naive_bounds_as_utc(
    dated_trail: ContextTrail, use_start: bool, use_end: bool, expected: list[str]
) -> None:
    bound = BOUNDARY.replace(tzinfo=None)

    rows = dated_trail.query(
        start=bound if use_start else None,
        end=bound if use_end else None,
    )

    assert [row["source_name"] for row in rows] == expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (["--from", "2026-11-03"], ["boundary", "after", "end_of_day", "next_day"]),
        (["--to", "2026-11-03"], ["before", "boundary", "after", "end_of_day"]),
        (
            ["--from", "2026-11-03", "--to", "2026-11-03"],
            ["boundary", "after", "end_of_day"],
        ),
    ],
)
def test_audit_date_filter_includes_its_utc_boundary(
    tmp_path: Path, options: list[str], expected: list[str]
) -> None:
    database = str(tmp_path / "audit.db")
    with ContextTrail(storage_path=database) as trail:
        _populate(trail)
        next_day = BOUNDARY + timedelta(days=1)
        with patch("provena.models.datetime") as clock:
            clock.now.side_effect = [next_day - timedelta(microseconds=1), next_day]
            for name in ("end_of_day", "next_day"):
                assert trail.log(name, source="retriever", source_name=name) is not None

    result = CliRunner().invoke(
        cli, ["--db", database, "audit", *options, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    assert [row["source_name"] for row in json.loads(result.output)] == expected
