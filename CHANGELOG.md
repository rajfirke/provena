# Changelog

All notable changes to Provena are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
