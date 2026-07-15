from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest

from provena.storage import InMemoryBackend, SQLiteBackend
from provena.trail import ContextTrail


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVENA_DISABLED", raising=False)
    monkeypatch.delenv("PROVENA_SIGNING_KEY", raising=False)


@pytest.fixture
def memory_backend() -> InMemoryBackend:
    return InMemoryBackend()


@pytest.fixture
def sqlite_backend(tmp_path: object) -> Generator[SQLiteBackend, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    backend = SQLiteBackend(path=db_path)
    yield backend
    backend.close()
    os.unlink(db_path)


@pytest.fixture
def trail(tmp_path: object) -> Generator[ContextTrail, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    t = ContextTrail(storage_path=db_path)
    yield t
    t.close()
    os.unlink(db_path)


@pytest.fixture
def memory_trail() -> ContextTrail:
    return ContextTrail(backend="memory")
