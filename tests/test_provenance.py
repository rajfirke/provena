from __future__ import annotations

from datetime import datetime, timezone

from provena.models import ContextEntry, ContextSource, ProvenanceMetadata
from provena.validators.provenance import ProvenanceValidator


class TestProvenanceValidator:
    def test_valid_with_defaults(self):
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.RETRIEVER,
            source_name="r",
            provenance=prov,
        )
        validator = ProvenanceValidator()
        result = validator.validate(entry)
        assert result.status == "VALID"
        assert result.missing_fields == ()

    def test_missing_provenance(self):
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.RETRIEVER,
            source_name="r",
        )
        validator = ProvenanceValidator()
        result = validator.validate(entry)
        assert result.status == "MISSING"
        assert "source_url" in result.missing_fields
        assert "created_at" in result.missing_fields

    def test_incomplete_provenance(self):
        prov = ProvenanceMetadata(source_url="https://example.com")
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.RETRIEVER,
            source_name="r",
            provenance=prov,
        )
        validator = ProvenanceValidator()
        result = validator.validate(entry)
        assert result.status == "INCOMPLETE"
        assert "created_at" in result.missing_fields
        assert "source_url" not in result.missing_fields

    def test_custom_required_fields(self):
        prov = ProvenanceMetadata(author="Alice", version="1.0")
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.TOOL,
            source_name="api",
            provenance=prov,
        )
        validator = ProvenanceValidator(required_fields=["author", "version"])
        result = validator.validate(entry)
        assert result.status == "VALID"

    def test_custom_fields_missing(self):
        prov = ProvenanceMetadata(author="Alice")
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.TOOL,
            source_name="api",
            provenance=prov,
        )
        validator = ProvenanceValidator(required_fields=["author", "version"])
        result = validator.validate(entry)
        assert result.status == "INCOMPLETE"
        assert "version" in result.missing_fields

    def test_empty_string_treated_as_missing(self):
        prov = ProvenanceMetadata(
            source_url="  ", created_at=datetime.now(timezone.utc)
        )
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.RETRIEVER,
            source_name="r",
            provenance=prov,
        )
        validator = ProvenanceValidator()
        result = validator.validate(entry)
        assert result.status == "INCOMPLETE"
        assert "source_url" in result.missing_fields

    def test_required_fields_property(self):
        validator = ProvenanceValidator()
        assert validator.required_fields == ("source_url", "created_at")

    def test_all_fields_valid(self):
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            author="Alice",
            created_at=datetime.now(timezone.utc),
            version="1.0",
        )
        entry = ContextEntry.create(
            content="test",
            source=ContextSource.RETRIEVER,
            source_name="r",
            provenance=prov,
        )
        validator = ProvenanceValidator(
            required_fields=["source_url", "author", "created_at", "version"]
        )
        result = validator.validate(entry)
        assert result.status == "VALID"
