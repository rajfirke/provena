from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from provena.models import ProvenanceMetadata
from provena.policy import (
    EnforcementLevel,
    Policy,
    PolicyCheckResult,
    PolicyEngine,
    PolicyEvaluation,
    PolicyViolation,
    freshness_check,
    provenance_check,
    require_signing,
    source_allowlist,
)
from provena.trail import ContextTrail


class TestEnforcementLevel:
    def test_values(self):
        assert EnforcementLevel.LOG == "log"
        assert EnforcementLevel.WARN == "warn"
        assert EnforcementLevel.BLOCK == "block"

    def test_from_string(self):
        assert EnforcementLevel("log") == EnforcementLevel.LOG
        assert EnforcementLevel("warn") == EnforcementLevel.WARN
        assert EnforcementLevel("block") == EnforcementLevel.BLOCK


class TestPolicyCheckResult:
    def test_frozen(self):
        result = PolicyCheckResult(
            policy_name="test",
            passed=True,
            enforcement=EnforcementLevel.LOG,
        )
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]


class TestPolicyEvaluation:
    def test_allow_with_no_violations(self):
        evaluation = PolicyEvaluation(decision="ALLOW")
        assert evaluation.violations == ()

    def test_violations_property(self):
        results = (
            PolicyCheckResult("p1", True, EnforcementLevel.LOG),
            PolicyCheckResult("p2", False, EnforcementLevel.BLOCK, "failed"),
            PolicyCheckResult("p3", True, EnforcementLevel.WARN),
        )
        evaluation = PolicyEvaluation(decision="DENY", results=results)
        assert len(evaluation.violations) == 1
        assert evaluation.violations[0].policy_name == "p2"


class TestPolicyViolation:
    def test_exception_attributes(self, memory_trail):
        record = memory_trail.log("test", source="retriever")
        exc = PolicyViolation(
            policy_name="freshness:STALE",
            record=record,
            details="Content is stale",
        )
        assert exc.policy_name == "freshness:STALE"
        assert exc.record is record
        assert exc.details == "Content is stale"
        assert "freshness:STALE" in str(exc)

    def test_is_exception(self):
        assert issubclass(PolicyViolation, Exception)


class TestPolicyEngine:
    def test_empty_engine_allows(self, memory_trail):
        engine = PolicyEngine()
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "ALLOW"
        assert evaluation.results == ()

    def test_passing_policy(self, memory_trail):
        policy = Policy(
            name="always_pass",
            check=lambda r: True,
            enforcement=EnforcementLevel.BLOCK,
        )
        engine = PolicyEngine([policy])
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "ALLOW"
        assert len(evaluation.results) == 1
        assert evaluation.results[0].passed

    def test_failing_log_policy_allows(self, memory_trail):
        policy = Policy(
            name="always_fail_log",
            check=lambda r: False,
            enforcement=EnforcementLevel.LOG,
        )
        engine = PolicyEngine([policy])
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "ALLOW"
        assert not evaluation.results[0].passed

    def test_failing_warn_policy_allows(self, memory_trail):
        policy = Policy(
            name="always_fail_warn",
            check=lambda r: False,
            enforcement=EnforcementLevel.WARN,
        )
        engine = PolicyEngine([policy])
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "ALLOW"

    def test_failing_block_policy_denies(self, memory_trail):
        policy = Policy(
            name="always_fail_block",
            check=lambda r: False,
            enforcement=EnforcementLevel.BLOCK,
        )
        engine = PolicyEngine([policy])
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "DENY"

    def test_forbid_overrides_permit(self, memory_trail):
        policies = [
            Policy("pass1", lambda r: True, EnforcementLevel.BLOCK),
            Policy("fail_block", lambda r: False, EnforcementLevel.BLOCK),
            Policy("pass2", lambda r: True, EnforcementLevel.LOG),
        ]
        engine = PolicyEngine(policies)
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "DENY"

    def test_multiple_log_failures_still_allow(self, memory_trail):
        policies = [
            Policy("fail1", lambda r: False, EnforcementLevel.LOG),
            Policy("fail2", lambda r: False, EnforcementLevel.WARN),
        ]
        engine = PolicyEngine(policies)
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "ALLOW"
        assert len(evaluation.violations) == 2

    def test_add_policy(self, memory_trail):
        engine = PolicyEngine()
        assert len(engine.policies) == 0
        engine.add(Policy("new", lambda r: True, EnforcementLevel.LOG))
        assert len(engine.policies) == 1

    def test_policies_property_returns_tuple(self):
        engine = PolicyEngine()
        assert isinstance(engine.policies, tuple)

    def test_check_exception_treated_as_failure(self, memory_trail):
        def bad_check(r):
            raise RuntimeError("boom")

        policy = Policy("bad", bad_check, EnforcementLevel.BLOCK)
        engine = PolicyEngine([policy])
        record = memory_trail.log("test", source="retriever")
        evaluation = engine.evaluate(record)
        assert evaluation.decision == "DENY"
        assert not evaluation.results[0].passed


class TestPolicyEngineFromConfig:
    def test_freshness_config(self, memory_trail):
        config = [{"check": "freshness", "status": "STALE", "enforcement": "block"}]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 1
        assert engine.policies[0].name == "freshness:STALE"

    def test_provenance_config(self, memory_trail):
        config = [{"check": "provenance", "status": "MISSING", "enforcement": "warn"}]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 1
        assert engine.policies[0].name == "provenance:MISSING"

    def test_require_signing_config(self):
        config = [{"check": "require_signing", "enforcement": "block"}]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 1
        assert engine.policies[0].name == "require_signing"

    def test_source_allowlist_config(self):
        config = [
            {
                "check": "source_allowlist",
                "sources": ["retriever", "tool"],
                "enforcement": "block",
            }
        ]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 1
        assert engine.policies[0].name == "source_allowlist"

    def test_multiple_policies_config(self):
        config = [
            {"check": "freshness", "status": "STALE", "enforcement": "warn"},
            {"check": "provenance", "status": "MISSING", "enforcement": "block"},
        ]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 2

    def test_default_enforcement_is_log(self):
        config = [{"check": "freshness", "status": "STALE"}]
        engine = PolicyEngine.from_config(config)
        assert engine.policies[0].enforcement == EnforcementLevel.LOG

    def test_unknown_check_ignored(self):
        config = [{"check": "nonexistent"}]
        engine = PolicyEngine.from_config(config)
        assert len(engine.policies) == 0


class TestBuiltInPolicies:
    def test_freshness_check_blocks_stale(self):
        trail = ContextTrail(backend="memory", max_age_days=30)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        record = trail.log("old data", source="retriever", provenance=prov)
        assert record is not None

        policy = freshness_check(status="STALE", enforcement=EnforcementLevel.BLOCK)
        assert not policy.check(record)
        trail.close()

    def test_freshness_check_passes_fresh(self):
        trail = ContextTrail(backend="memory", max_age_days=90)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        record = trail.log("fresh data", source="retriever", provenance=prov)
        assert record is not None

        policy = freshness_check(status="STALE", enforcement=EnforcementLevel.BLOCK)
        assert policy.check(record)
        trail.close()

    def test_provenance_check_blocks_missing(self, memory_trail):
        record = memory_trail.log("no provenance", source="retriever")
        policy = provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
        assert not policy.check(record)

    def test_provenance_check_passes_valid(self):
        trail = ContextTrail(backend="memory")
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        record = trail.log("data", source="retriever", provenance=prov)
        policy = provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
        assert policy.check(record)
        trail.close()

    def test_source_allowlist_blocks_unknown(self, memory_trail):
        record = memory_trail.log("data", source="agent")
        policy = source_allowlist(
            allowed=["retriever", "tool"], enforcement=EnforcementLevel.BLOCK
        )
        assert not policy.check(record)

    def test_source_allowlist_passes_allowed(self, memory_trail):
        record = memory_trail.log("data", source="retriever")
        policy = source_allowlist(
            allowed=["retriever", "tool"], enforcement=EnforcementLevel.BLOCK
        )
        assert policy.check(record)

    def test_require_signing_fails_without_signing_key(self, memory_trail):
        record = memory_trail.log("data", source="retriever")
        policy = require_signing(enforcement=EnforcementLevel.BLOCK)
        assert not policy.check(record)

    def test_require_signing_passes_with_signed_trail(self):
        trail = ContextTrail(
            backend="memory",
            signing_key="secret",
            policies=[require_signing(enforcement=EnforcementLevel.BLOCK)],
        )
        record = trail.log("data", source="retriever")
        assert record is not None
        trail.close()


class TestContextTrailWithPolicies:
    def test_block_policy_raises_on_log(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
            ],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            trail.log("no provenance", source="retriever")
        assert exc_info.value.policy_name == "provenance:MISSING"
        trail.close()

    def test_blocked_record_still_persisted(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
            ],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            trail.log("no provenance", source="retriever")

        assert trail.summary()["total"] == 1
        assert exc_info.value.record.id == 1
        trail.close()

    def test_warn_policy_returns_record(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.WARN)
            ],
        )
        record = trail.log("no provenance", source="retriever")
        assert record is not None
        assert trail.summary()["total"] == 1
        trail.close()

    def test_log_policy_silently_passes(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.LOG)
            ],
        )
        record = trail.log("no provenance", source="retriever")
        assert record is not None
        trail.close()

    def test_passing_policy_does_not_interfere(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                source_allowlist(
                    allowed=["retriever", "tool"], enforcement=EnforcementLevel.BLOCK
                )
            ],
        )
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        record = trail.log("data", source="retriever", provenance=prov)
        assert record is not None
        trail.close()

    def test_multiple_policies_block_wins(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                freshness_check(status="UNKNOWN", enforcement=EnforcementLevel.WARN),
                provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK),
            ],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            trail.log("no provenance", source="retriever")
        assert exc_info.value.policy_name == "provenance:MISSING"
        trail.close()

    def test_block_propagates_even_without_strict_mode(self):
        trail = ContextTrail(
            backend="memory",
            strict_mode=False,
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
            ],
        )
        with pytest.raises(PolicyViolation):
            trail.log("test", source="retriever")
        trail.close()

    def test_chain_integrity_preserved_after_block(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                source_allowlist(
                    allowed=["retriever"], enforcement=EnforcementLevel.BLOCK
                )
            ],
        )
        trail.log("first", source="retriever")

        with pytest.raises(PolicyViolation):
            trail.log("blocked", source="agent")

        trail.log("third", source="retriever")

        verdict = trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 3
        trail.close()

    def test_config_dict_with_policies(self):
        trail = ContextTrail(
            config={
                "storage": {"backend": "memory"},
                "policies": [
                    {
                        "check": "provenance",
                        "status": "MISSING",
                        "enforcement": "block",
                    }
                ],
            }
        )
        with pytest.raises(PolicyViolation):
            trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()

    def test_no_policies_default(self, memory_trail):
        record = memory_trail.log("test", source="retriever")
        assert record is not None

    def test_track_decorator_with_policy_override(self):
        trail = ContextTrail(backend="memory")

        strict_policies = [
            provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
        ]

        @trail.track(source="retriever", policies=strict_policies)
        def search(query):
            return f"result for {query}"

        with pytest.raises(PolicyViolation):
            search("test")

        assert trail.summary()["total"] == 1
        trail.close()

    def test_track_decorator_override_does_not_affect_log(self):
        trail = ContextTrail(backend="memory")

        @trail.track(
            source="retriever",
            policies=[
                provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK)
            ],
        )
        def search(query):
            return f"result for {query}"

        record = trail.log("direct log without policy", source="retriever")
        assert record is not None
        trail.close()

    def test_track_async_with_block_policy(self):
        trail = ContextTrail(
            backend="memory",
            policies=[
                source_allowlist(allowed=["tool"], enforcement=EnforcementLevel.BLOCK)
            ],
        )

        @trail.track(source="retriever")
        async def async_search(query):
            return f"async result for {query}"

        with pytest.raises(PolicyViolation):
            asyncio.run(async_search("test"))

        assert trail.summary()["total"] == 1
        trail.close()
