# Changelog

All notable changes to Provena are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-07-22

### Production Release

Provena v1.0.0 marks production readiness. All 8 planned phases are complete.
Semantic versioning commitment: the 1.x API surface is stable.

### Core
- Tamper-evident SHA-256 hash-chained audit trails with HMAC signing
- Provenance validation (VALID / MISSING / INCOMPLETE)
- Freshness checking via metadata timestamps and regex temporal detection
- Policy engine with LOG / WARN / BLOCK enforcement
- Async batch write buffer for 10K+ entries/sec throughput
- TOML / YAML config file support with signing_key_env

### Storage
- SQLite backend (default) with WAL mode and PRAGMA optimizations
- PostgreSQL backend with psycopg v3, connection pooling, advisory locks
- InMemory backend for testing
- Migration CLI between backends

### Integrations
- 6 framework adapters: LangChain, LlamaIndex, CrewAI, AutoGen, OpenAI
  Agents SDK, Google ADK
- OpenTelemetry span export
- MCP governance server (5 tools, 3 resources, 1 prompt)

### Governance
- Multi-trail aggregation with handoff tracking and evidence gap detection
- Retention policy engine with EU AI Act 180-day minimum enforcement
- Compliance report generator with EU AI Act article-by-article scoring
- PDF report output

### Security (since 0.15.0)
- verify_chain() now uses hmac.compare_digest() for timing-safe comparison
- _weak_flush uses peek-before-pop to prevent data loss

## [0.15.0] - 2026-07-20

### Fixed
- **Retention preserves chain integrity** — uses tombstones instead of record
  deletion, keeping verify_chain() intact per EU AI Act Art. 12 (#40)
- **Buffer flush no longer loses records** — peek-before-pop pattern prevents
  data loss when backend.append() fails (#41)
- **FreshnessChecker uses most recent date** — max(dates) instead of min(dates)
  prevents false STALE on content with historical references (#49)
- **Compliance report score aligned with Art. 10** — provenance check now
  requires 100% valid, matching the article-level assessment (#52)
- Retention engine now supports PostgreSQL backend via _pool connection (#44)

## [0.14.0] - 2026-07-20

### Added
- **Retention policy engine**: `RetentionEngine` with configurable retention
  period, EU AI Act 180-day minimum enforcement, export-before-delete archival,
  dry-run preview, and retention actions logged to the audit trail (#29)
- **Compliance report generator**: `generate_report()` and `generate_pdf_report()`
  with EU AI Act article-by-article compliance scoring (Art. 10/12/13/14),
  issue detection, and chain integrity assessment
- **PDF reports**: `provena report --format pdf` via `provena[pdf]` (fpdf2)
- **CLI retain command**: `provena retain --max-age 365 --archive backup.json`
  with `--dry-run` preview mode
- New exports: `RetentionEngine`, `RetentionResult`

## [0.13.0] - 2026-07-20

### Added
- **Multi-trail aggregation**: `TrailAggregator` for governing multi-agent
  systems — unified summary, query, and chain verification across agents (#28)
- **Handoff tracking**: `record_handoff()` links records across trails when
  context flows agent-to-agent, with `run_id` grouping for workflow audit
- **Cross-agent timeline**: `timeline()` provides merged chronological view
  with interleaved handoff edges
- **Evidence gap detection**: `detect_gaps()` surfaces broken chains, stale
  context, missing provenance, and unlinked handoffs across the full pipeline
- **Query by run**: `query(run_id="...")` filters records involved in a
  specific workflow execution across all agents
- New exports: `TrailAggregator`, `HandoffEdge`, `AggregateVerdict`,
  `TrailVerdict`, `EvidenceGap`

## [0.12.0] - 2026-07-20

### Added
- **Async batch write buffer**: `ContextTrail(buffered=True)` moves storage
  writes to a background thread for 10K+ entries/sec throughput
- `trail.flush()` for explicit buffer drain
- 5-layer flush safety: explicit, context manager, atexit, SIGTERM, weakref
- `health()` now reports `buffered` and `buffer_pending` fields
- Config file support: `storage.buffered`, `storage.buffer_size`,
  `storage.flush_interval`
- CI benchmark tests: 10K entries < 10s, verify 10K chain < 5s

## [0.11.0] - 2026-07-19

### Added
- **MCP server**: Governance-aware agents via `provena mcp serve` (`provena[mcp]`)
- 5 MCP tools: `check_freshness`, `verify_chain`, `list_violations`,
  `get_summary`, `check_provenance` — all return structured JSON with
  `recommendation` field
- 3 MCP resources: `provena://health`, `provena://summary`,
  `provena://chain/status`
- 1 MCP prompt: `governance_check` — standard agent self-audit prompt
- `configure(trail)` API for binding a ContextTrail to the MCP server
- CLI: `provena mcp serve --db audit.db` starts the MCP server

## [0.10.0] - 2026-07-19

### Added
- **CrewAI adapter**: `ProvenaCrewListener` event listener for tool and agent
  outputs (`provena[crewai]`)
- **AutoGen adapter**: `ProvenaAutoGenHook` for message interception via
  `register_hook("process_message_before_send", ...)` (`provena[autogen]`)
- **OpenAI Agents SDK adapter**: `ProvenaRunHooks` with async `on_tool_end`
  and `on_handoff` hooks (`provena[openai-agents]`)
- **Google ADK adapter**: `ProvenaADKCallback` with `after_tool_call`
  callback (`provena[google-adk]`)
- 6 total framework adapters (LangChain, LlamaIndex, CrewAI, AutoGen,
  OpenAI Agents SDK, Google ADK)

## [0.9.0] - 2026-07-19

### Added
- **TOML config files**: `ContextTrail(config="provena.toml")` with zero new deps
  on Python 3.11+ (stdlib `tomllib`); `tomli` backport for 3.10
- **YAML config files**: `ContextTrail(config="trail.yaml")` via `provena[yaml]`
- **`signing_key_env`**: Config files reference env vars instead of storing keys
  directly (`hash_chain.signing_key_env = "PROVENA_SIGNING_KEY"`)
- **PostgreSQL backend**: `provena[postgres]` with `psycopg` v3, connection
  pooling, `pg_advisory_xact_lock` for chain ordering, JSONB + TIMESTAMPTZ
  schema, and 5 indexes for query performance
- **URL auto-detection**: `storage_path="postgresql://..."` automatically selects
  the PostgreSQL backend
- **Migration CLI**: `provena migrate --from audit.db --to postgresql://...`
  with batch streaming, annotation copying, and chain integrity verification
- **`--config` CLI option**: All CLI commands support `--config provena.toml`
  (envvar `PROVENA_CONFIG`)
- Example config files: `provena.example.toml` and `provena.example.yaml`

## [0.8.0] - 2026-07-18

### Added
- **Policy engine**: `ContextTrail(policies=[...])` enforces governance rules at
  three levels — `LOG`, `WARN`, `BLOCK` — on every logged entry (#26)
- `PolicyViolation` exception raised on BLOCK (propagates even in non-strict mode)
- Blocked records are still persisted to the audit trail (EU AI Act Art. 12 compliance)
- Built-in policy checks: `freshness_check()`, `provenance_check()`,
  `require_signing()`, `source_allowlist()`
- `PolicyEngine.from_config()` for declarative policy configuration
- Per-decorator policy override: `@trail.track(source="retriever", policies=[...])`
- Forbid-overrides-permit: any BLOCK-level failure = DENY

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
- **Annotation retrieval API**: `ContextTrail.get_annotations(record_id)` and
  `StorageBackend.get_annotations(record_id)` (implemented in `SQLiteBackend`
  and `InMemoryBackend`) — read annotations for a record in insertion order,
  returning `[]` for non-existent or unannotated records (#27)
- New `"json_with_annotations"` export format including annotations grouped by
  `record_id` (backward compatible — existing `"json"` format unchanged) (#27)

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
