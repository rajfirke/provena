"""Policy engine for governance enforcement on context inputs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from provena.models import TrailRecord

_logger = logging.getLogger("provena.policy")


class EnforcementLevel(str, Enum):
    """How a policy violation is handled."""

    LOG = "log"
    WARN = "warn"
    BLOCK = "block"


class PolicyViolation(Exception):
    """Raised when a BLOCK-level policy rejects a context input.

    Attributes:
        policy_name: Name of the policy that triggered the block.
        record: The TrailRecord that was blocked (already persisted).
        details: Human-readable explanation.
    """

    def __init__(
        self,
        policy_name: str,
        record: TrailRecord,
        details: str = "",
    ) -> None:
        self.policy_name = policy_name
        self.record = record
        self.details = details
        super().__init__(f"Policy '{policy_name}' blocked context: {details}")


@dataclass(frozen=True, slots=True)
class PolicyCheckResult:
    """Outcome of a single policy check against one record.

    Attributes:
        policy_name: Name of the policy that was evaluated.
        passed: Whether the record satisfied the policy.
        enforcement: The enforcement level configured for this policy.
        details: Human-readable explanation.
    """

    policy_name: str
    passed: bool
    enforcement: EnforcementLevel
    details: str = ""


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """Aggregate result of evaluating all policies against a record.

    Attributes:
        decision: Overall outcome — ``"ALLOW"`` or ``"DENY"``.
        results: Individual check results for each policy.
    """

    decision: Literal["ALLOW", "DENY"]
    results: tuple[PolicyCheckResult, ...] = ()

    @property
    def violations(self) -> tuple[PolicyCheckResult, ...]:
        """Return only the failing check results."""
        return tuple(r for r in self.results if not r.passed)

    def __repr__(self) -> str:
        n = len(self.results)
        if self.decision == "DENY":
            v = len(self.violations)
            label = "violation" if v == 1 else "violations"
            return f"PolicyEvaluation(DENY, {v} {label})"
        label = "check" if n == 1 else "checks"
        return f"PolicyEvaluation(ALLOW, {n} {label})"


@dataclass(frozen=True, slots=True)
class Policy:
    """A governance rule evaluated against every logged record.

    Attributes:
        name: Unique identifier for this policy.
        check: Callable that returns True if the record passes.
        enforcement: What happens when the check fails.
        description: Human-readable explanation of what the policy enforces.
    """

    name: str
    check: Any  # Callable[[TrailRecord], bool] — Any to keep frozen+slots
    enforcement: EnforcementLevel = EnforcementLevel.LOG
    description: str = ""


class PolicyEngine:
    """Evaluates a set of policies against trail records.

    Follows forbid-overrides-permit: if any BLOCK-level policy fails,
    the overall decision is DENY regardless of other policies.
    """

    def __init__(self, policies: list[Policy] | None = None) -> None:
        self._policies: list[Policy] = list(policies) if policies else []

    @property
    def policies(self) -> tuple[Policy, ...]:
        """Return the registered policies."""
        return tuple(self._policies)

    def add(self, policy: Policy) -> None:
        """Register an additional policy."""
        self._policies.append(policy)

    def evaluate(self, record: TrailRecord) -> PolicyEvaluation:
        """Run all policies against a record and return the aggregate result."""
        if not self._policies:
            return PolicyEvaluation(decision="ALLOW")

        results: list[PolicyCheckResult] = []
        has_block = False

        for policy in self._policies:
            try:
                passed = policy.check(record)
            except Exception:
                _logger.debug(
                    "Policy '%s' raised during evaluation", policy.name, exc_info=True
                )
                passed = False

            result = PolicyCheckResult(
                policy_name=policy.name,
                passed=passed,
                enforcement=policy.enforcement,
                details=policy.description if not passed else "",
            )
            results.append(result)

            if not passed and policy.enforcement == EnforcementLevel.BLOCK:
                has_block = True

        decision: Literal["ALLOW", "DENY"] = "DENY" if has_block else "ALLOW"
        return PolicyEvaluation(decision=decision, results=tuple(results))

    @classmethod
    def from_config(cls, config: list[dict[str, Any]]) -> PolicyEngine:
        """Build a PolicyEngine from a list of declarative policy dicts.

        Each dict should have keys: ``check``, ``enforcement`` (optional,
        defaults to ``"log"``), and check-specific parameters like ``status``.

        Supported checks: ``"freshness"``, ``"provenance"``,
        ``"require_signing"``, ``"source_allowlist"``.
        """
        policies: list[Policy] = []
        for entry in config:
            check_name = entry.get("check", "")
            enforcement = EnforcementLevel(entry.get("enforcement", "log"))

            if check_name == "freshness":
                status = entry.get("status", "STALE")
                policies.append(freshness_check(status=status, enforcement=enforcement))
            elif check_name == "provenance":
                status = entry.get("status", "MISSING")
                policies.append(
                    provenance_check(status=status, enforcement=enforcement)
                )
            elif check_name == "require_signing":
                policies.append(require_signing(enforcement=enforcement))
            elif check_name == "source_allowlist":
                allowed = entry.get("sources", [])
                policies.append(
                    source_allowlist(allowed=allowed, enforcement=enforcement)
                )
            else:
                _logger.warning(
                    "Unknown policy check %r — skipping. "
                    "Valid checks: freshness, provenance, require_signing, source_allowlist",
                    check_name,
                )

        return cls(policies)


def freshness_check(
    *,
    status: str = "STALE",
    enforcement: EnforcementLevel = EnforcementLevel.LOG,
) -> Policy:
    """Policy that fails when freshness matches the given status."""

    def _check(record: TrailRecord) -> bool:
        if record.freshness_result is None:
            return True
        return record.freshness_result.status != status

    return Policy(
        name=f"freshness:{status}",
        check=_check,
        enforcement=enforcement,
        description=f"Content freshness must not be {status}",
    )


def provenance_check(
    *,
    status: str = "MISSING",
    enforcement: EnforcementLevel = EnforcementLevel.LOG,
) -> Policy:
    """Policy that fails when provenance matches the given status."""

    def _check(record: TrailRecord) -> bool:
        if record.provenance_result is None:
            return True
        return record.provenance_result.status != status

    return Policy(
        name=f"provenance:{status}",
        check=_check,
        enforcement=enforcement,
        description=f"Provenance must not be {status}",
    )


def require_signing(
    *,
    enforcement: EnforcementLevel = EnforcementLevel.BLOCK,
    _signed_ref: list[bool] | None = None,
) -> Policy:
    """Policy that fails when the trail is not HMAC-signed.

    Accepts an optional mutable reference ``_signed_ref`` (a single-element
    list) that can be updated after construction by the trail.
    """
    ref = _signed_ref if _signed_ref is not None else [False]

    def _check(record: TrailRecord) -> bool:
        return ref[0]

    return Policy(
        name="require_signing",
        check=_check,
        enforcement=enforcement,
        description="Trail must use HMAC-signed hash chains",
    )


def source_allowlist(
    *,
    allowed: list[str],
    enforcement: EnforcementLevel = EnforcementLevel.BLOCK,
) -> Policy:
    """Policy that fails when the source is not in the allowlist."""
    allowed_set = frozenset(allowed)

    def _check(record: TrailRecord) -> bool:
        return record.entry.source.value in allowed_set

    return Policy(
        name="source_allowlist",
        check=_check,
        enforcement=enforcement,
        description=f"Source must be one of: {', '.join(sorted(allowed_set))}",
    )
