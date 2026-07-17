# Changelog

All notable changes to Provena are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.7.0] - 2026-07-18

### Added
- Documentation site at [rajfirke.github.io/provena](https://rajfirke.github.io/provena)
- MkDocs Material theme with light/dark toggle, code copy, and search
- Auto-generated API reference from docstrings via mkdocstrings
- Guide pages: tracking, provenance, freshness, verification, configuration, testing
- Integration docs: LangChain, LlamaIndex, OpenTelemetry, CLI reference
- Compliance docs: EU AI Act article-by-article mapping, OWASP ASI06 coverage
- GitHub Actions workflow for automatic docs deployment to GitHub Pages
- Documentation URL added to PyPI project metadata

## [0.6.0] - 2026-07-17

### Added
- Google-style docstrings on all public API classes and methods
- PyPI trusted publishing via GitHub Actions with OIDC authentication
- PyPI version and download badges in README
- `ContextTrail.query()` filters for exact provenance and freshness status values

## [0.5.0] - 2026-07-15

### Added
- **Framework integrations**: LangChain `ProvenaCallback` and LlamaIndex `ProvenaPostprocessor`
- **OpenTelemetry export**: Span emission for every governance event (`provena[otel]`)
- **CLI tools**: `provena audit`, `provena verify`, `provena report`, `provena summary`
- **FreshnessChecker**: Regex-based temporal detection (ISO dates, month-year, quarters, contextual years)
- **HMAC-SHA256 signing**: Optional compliance mode with external signing key
- **Config validation**: `max_age_days` and `max_content_bytes` validated on construction
- **InMemoryBackend**: For testing without filesystem side effects
- **SQLite schema versioning**: `user_version` pragma with automatic migration
- **`trail.annotate()`**: Human oversight annotations (EU AI Act Art. 14)
- **`trail.explain()`/`summary()`**: Governance transparency (EU AI Act Art. 13)
- **Error resilience**: Governance failures never crash user code
- **Content type dispatch**: Automatic handling of str, bytes, list, dict, LangChain Documents
- **226 tests** with 89% coverage across all components

### Architecture
- Pure Python, zero stdlib-only dependencies for core
- SHA-256 hash-chained Merkle audit trail
- Frozen dataclasses with slots for all models
- Per-instance threading locks for thread safety
- Append-only SQLite with WAL mode

## [0.1.0] - 2026-07-13

### Added
- Initial implementation: `ContextTrail`, `@trail.track` decorator
- Core models: `ContextEntry`, `TrailRecord`, `ProvenanceMetadata`, `ValidationResult`
- `ProvenanceValidator` with configurable required fields
- `HashChain` with SHA-256
- `SQLiteBackend` with append-only storage
- `ContextSource` enum: retriever, tool, agent, memory, mcp, custom
