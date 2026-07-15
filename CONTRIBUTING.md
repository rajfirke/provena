# Contributing to Provena

Thanks for your interest in contributing to Provena! This document covers everything you need to get started.

## Development Setup

```bash
# Clone and install
git clone https://github.com/rajfirke/provena.git
cd provena
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,cli,otel]"
pip install opentelemetry-sdk  # for OTel tests

# Verify everything works
pytest
ruff check src/ tests/
mypy src/provena/
```

## Project Structure

```
src/provena/
├── __init__.py              # Public API
├── models.py                # Core data types (ContextEntry, TrailRecord, etc.)
├── hasher.py                # SHA-256 / HMAC-SHA256 hash chain
├── storage.py               # SQLite + InMemory backends
├── trail.py                 # ContextTrail engine + @track decorator
├── validators/
│   ├── provenance.py        # Provenance validation (VALID/MISSING/INCOMPLETE)
│   └── freshness.py         # Freshness checking with regex temporal detection
├── exporters/
│   └── otel.py              # OpenTelemetry span export
├── integrations/
│   ├── langchain.py         # LangChain BaseCallbackHandler
│   └── llamaindex.py        # LlamaIndex BaseNodePostprocessor
└── cli/
    └── main.py              # Click-based CLI (audit/verify/report/summary)
```

## How to Contribute

### Adding a New Validator

1. Create `src/provena/validators/your_validator.py`
2. Follow the pattern in `provenance.py` — accept a `ContextEntry`, return a result dataclass
3. Add tests in `tests/test_your_validator.py`
4. Integrate into `trail.py` `_log_internal()` if it should run on every log call

### Adding a New Integration

1. Create `src/provena/integrations/your_framework.py`
2. Use try/except for the framework import (see `langchain.py` for the pattern)
3. Add the framework as an optional dependency in `pyproject.toml`
4. Add tests using mock objects (see `test_integrations.py`)

### Adding a New Storage Backend

1. Implement the `StorageBackend` protocol from `storage.py`
2. Required methods: `append`, `get`, `get_last`, `count`, `all_records`, `query`, `add_annotation`, `close`
3. Add tests that verify parity with `InMemoryBackend`

## Code Standards

- **Formatter**: `ruff format`
- **Linter**: `ruff check` (rules: E, F, I, N, UP, W, B, SIM, RUF)
- **Type checker**: `mypy --strict`
- **Tests**: `pytest` with `pytest-cov` — aim for 90%+ coverage
- **Python**: 3.10+ (use `from __future__ import annotations`)

All checks must pass before merging. CI runs automatically on every PR.

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes with tests
3. Run the full check suite:
   ```bash
   ruff check src/ tests/
   ruff format --check src/ tests/
   mypy src/provena/
   pytest --cov=provena
   ```
4. Open a PR with a clear description of what and why
5. Respond to review feedback

## Reporting Bugs

Use the [bug report template](https://github.com/rajfirke/provena/issues/new?template=bug_report.yml) on GitHub Issues.

## Requesting Features

Use the [feature request template](https://github.com/rajfirke/provena/issues/new?template=feature_request.yml) on GitHub Issues.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
