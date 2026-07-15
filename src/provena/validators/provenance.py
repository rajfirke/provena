from __future__ import annotations

from provena.models import ContextEntry, ProvenanceMetadata, ValidationResult

_DEFAULT_REQUIRED = ("source_url", "created_at")


class ProvenanceValidator:
    def __init__(
        self, required_fields: tuple[str, ...] | list[str] | None = None
    ) -> None:
        self._required = (
            tuple(required_fields) if required_fields else _DEFAULT_REQUIRED
        )

    @property
    def required_fields(self) -> tuple[str, ...]:
        return self._required

    def validate(self, entry: ContextEntry) -> ValidationResult:
        if entry.provenance is None:
            return ValidationResult(
                status="MISSING",
                missing_fields=self._required,
                details="No provenance metadata attached",
            )

        missing = self._check_fields(entry.provenance)
        if missing:
            return ValidationResult(
                status="INCOMPLETE",
                missing_fields=tuple(missing),
                details=f"Missing fields: {', '.join(missing)}",
            )

        return ValidationResult(status="VALID")

    def _check_fields(self, prov: ProvenanceMetadata) -> list[str]:
        missing: list[str] = []
        for f in self._required:
            val = getattr(prov, f, None) if f != "extra" else None
            if f == "extra":
                continue
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(f)
        return missing
