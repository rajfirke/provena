"""Tests for TOML/YAML config file loading and signing_key_env support."""

from __future__ import annotations

import pytest

from provena import ContextTrail


class TestTOMLConfig:
    def test_load_toml_config(self, tmp_path):
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\nbackend = "memory"\n\n[freshness]\nmax_age_days = 30\n'
        )
        trail = ContextTrail(config=str(config_file))
        trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()

    def test_load_toml_pathlib(self, tmp_path):
        config_file = tmp_path / "provena.toml"
        config_file.write_text('[storage]\nbackend = "memory"\n')
        trail = ContextTrail(config=config_file)
        trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()

    def test_toml_with_policies(self, tmp_path):
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\nbackend = "memory"\n\n'
            "[[policies]]\n"
            'check = "provenance"\n'
            'status = "MISSING"\n'
            'enforcement = "warn"\n'
        )
        trail = ContextTrail(config=str(config_file))
        record = trail.log("test", source="retriever")
        assert record is not None
        trail.close()


class TestYAMLConfig:
    def test_load_yaml_config(self, tmp_path):
        config_file = tmp_path / "provena.yaml"
        config_file.write_text(
            "storage:\n  backend: memory\nfreshness:\n  max_age_days: 45\n"
        )
        trail = ContextTrail(config=str(config_file))
        trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()

    def test_load_yml_extension(self, tmp_path):
        config_file = tmp_path / "provena.yml"
        config_file.write_text("storage:\n  backend: memory\n")
        trail = ContextTrail(config=str(config_file))
        trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()


class TestConfigErrors:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            ContextTrail(config="/nonexistent/provena.toml")

    def test_unsupported_extension_raises(self, tmp_path):
        config_file = tmp_path / "provena.json"
        config_file.write_text("{}")
        with pytest.raises(ValueError, match="Unsupported config file format"):
            ContextTrail(config=str(config_file))

    def test_yaml_non_mapping_raises(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="YAML config must be a mapping"):
            ContextTrail(config=str(config_file))

    def test_empty_config_dict_uses_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trail = ContextTrail(config={})
        trail.log("test", source="retriever")
        assert trail.summary()["total"] == 1
        trail.close()


class TestSigningKeyEnv:
    def test_signing_key_env_resolved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SIGNING_KEY", "test-secret-key")
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\nbackend = "memory"\n\n'
            "[hash_chain]\n"
            'signing_key_env = "MY_SIGNING_KEY"\n'
        )
        trail = ContextTrail(config=str(config_file))
        assert trail.is_signed
        trail.close()

    def test_signing_key_env_not_set(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MY_SIGNING_KEY", raising=False)
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\nbackend = "memory"\n\n'
            "[hash_chain]\n"
            'signing_key_env = "MY_SIGNING_KEY"\n'
        )
        trail = ContextTrail(config=str(config_file))
        assert not trail.is_signed
        trail.close()

    def test_signing_key_direct_takes_precedence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_SIGNING_KEY", "env-key")
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\nbackend = "memory"\n\n'
            "[hash_chain]\n"
            'signing_key = "direct-key"\n'
            'signing_key_env = "MY_SIGNING_KEY"\n'
        )
        trail = ContextTrail(config=str(config_file))
        assert trail.is_signed
        trail.close()


_has_psycopg = False
try:
    import psycopg  # noqa: F401

    _has_psycopg = True
except ImportError:
    pass


class TestAutoDetectPostgres:
    @pytest.mark.skipif(_has_psycopg, reason="psycopg IS installed")
    def test_pg_url_import_error_without_psycopg(self):
        with pytest.raises(ImportError, match="psycopg"):
            ContextTrail(storage_path="postgresql://localhost/test")

    @pytest.mark.skipif(_has_psycopg, reason="psycopg IS installed")
    def test_pg_config_import_error_without_psycopg(self, tmp_path):
        config_file = tmp_path / "provena.toml"
        config_file.write_text(
            '[storage]\npath = "postgresql://localhost:5432/provena_test"\n'
        )
        with pytest.raises(ImportError, match="psycopg"):
            ContextTrail(config=str(config_file))
