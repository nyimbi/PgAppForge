"""
tests/ci/test_env_pipeline.py

CI tests for pgappforge.env_pipeline — config loading, env var
substitution, CLI commands (list / diff / deploy / promote).
No mocks; no Flask app context required.
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pgappforge.env_pipeline.config import EnvironmentConfig, PgAppForgeConfig
from pgappforge.env_pipeline.deployment_log import (
	create_deployment_log_table,
	log_deployment,
)
from pgappforge.cli import forge


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def full_yaml(tmp_path) -> Path:
	content = textwrap.dedent("""
		default_environment: development
		environments:
		  development:
		    database_uri: "postgresql://localhost/dev_db"
		    debug: true
		    mock_mpesa: true
		    require_mfa: false
		    ai_features: true
		    extra_plugins:
		      - pgappforge.plugins.devtools
		  staging:
		    database_uri: "postgresql://staging-host/staging_db"
		    debug: false
		    mock_mpesa: false
		    require_mfa: false
		    ai_features: true
		  production:
		    database_uri: "postgresql://prod-host/prod_db"
		    debug: false
		    mock_mpesa: false
		    require_mfa: true
		    ai_features: true
	""")
	p = tmp_path / "pgappforge.yaml"
	p.write_text(content)
	return p


@pytest.fixture
def runner() -> CliRunner:
	return CliRunner()


# ── EnvironmentConfig ─────────────────────────────────────────────────────────

class TestEnvironmentConfig:
	def test_defaults(self):
		e = EnvironmentConfig(name="test", database_uri="postgresql://localhost/test")
		assert e.debug is False
		assert e.ai_features is True
		assert e.mock_mpesa is False
		assert e.require_mfa is False
		assert e.extra_plugins == []
		assert e.env_vars == {}

	def test_custom_values(self):
		e = EnvironmentConfig(
			name="prod",
			database_uri="postgresql://prod/db",
			debug=False,
			require_mfa=True,
			extra_plugins=["myplugin"],
			env_vars={"LOG_LEVEL": "WARNING"},
		)
		assert e.require_mfa is True
		assert "myplugin" in e.extra_plugins
		assert e.env_vars["LOG_LEVEL"] == "WARNING"


# ── PgAppForgeConfig.load ─────────────────────────────────────────────────────

class TestPgAppForgeConfigLoad:
	def test_default_when_no_file(self):
		cfg = PgAppForgeConfig.load("/nonexistent/pgappforge.yaml")
		assert "development" in cfg.environments
		assert "staging" in cfg.environments
		assert "production" in cfg.environments
		assert cfg.default_environment == "development"

	def test_production_requires_mfa_in_default(self):
		cfg = PgAppForgeConfig._default()
		assert cfg.environments["production"].require_mfa is True

	def test_load_from_yaml(self, full_yaml):
		cfg = PgAppForgeConfig.load(full_yaml)
		assert cfg.default_environment == "development"
		assert len(cfg.environments) == 3
		assert cfg.environments["development"].debug is True
		assert cfg.environments["production"].require_mfa is True

	def test_extra_plugins_loaded(self, full_yaml):
		cfg = PgAppForgeConfig.load(full_yaml)
		assert "pgappforge.plugins.devtools" in cfg.environments["development"].extra_plugins

	def test_env_var_substitution(self, tmp_path):
		os.environ["TEST_CODEGEN_DB"] = "postgresql://localhost/substituted"
		content = textwrap.dedent("""
			default_environment: development
			environments:
			  development:
			    database_uri: "${TEST_CODEGEN_DB}"
			    debug: true
		""")
		p = tmp_path / "cfg.yaml"
		p.write_text(content)
		cfg = PgAppForgeConfig.load(p)
		assert cfg.environments["development"].database_uri == "postgresql://localhost/substituted"

	def test_unresolved_env_var_kept_as_literal(self, tmp_path):
		# env var not set — literal should be preserved
		os.environ.pop("DEFINITELY_UNSET_VAR_XYZ", None)
		content = textwrap.dedent("""
			default_environment: development
			environments:
			  development:
			    database_uri: "${DEFINITELY_UNSET_VAR_XYZ}"
		""")
		p = tmp_path / "cfg.yaml"
		p.write_text(content)
		cfg = PgAppForgeConfig.load(p)
		assert cfg.environments["development"].database_uri == "${DEFINITELY_UNSET_VAR_XYZ}"

	def test_get_env_returns_named(self, full_yaml):
		cfg = PgAppForgeConfig.load(full_yaml)
		e = cfg.get_env("staging")
		assert e.name == "staging"

	def test_get_env_falls_back_to_default(self, full_yaml):
		cfg = PgAppForgeConfig.load(full_yaml)
		e = cfg.get_env(None)
		assert e.name == "development"

	def test_get_env_raises_for_unknown(self, full_yaml):
		cfg = PgAppForgeConfig.load(full_yaml)
		with pytest.raises(KeyError, match="nonexistent"):
			cfg.get_env("nonexistent")


# ── CLI: forge env list ───────────────────────────────────────────────────────

class TestEnvList:
	def test_lists_all_environments(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "list", "--config", str(full_yaml)])
		assert r.exit_code == 0, r.output
		assert "development" in r.output
		assert "staging" in r.output
		assert "production" in r.output

	def test_marks_default(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "list", "--config", str(full_yaml)])
		assert r.exit_code == 0
		assert "<- default" in r.output

	def test_shows_count(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "list", "--config", str(full_yaml)])
		assert "3 environment(s)" in r.output

	def test_works_without_config_file(self, runner, tmp_path):
		# fallback defaults shown even with nonexistent path
		r = runner.invoke(forge, ["env", "list", "--config", str(tmp_path / "missing.yaml")])
		assert r.exit_code == 0
		assert "development" in r.output


# ── CLI: forge env diff ───────────────────────────────────────────────────────

class TestEnvDiff:
	def test_shows_changed_fields(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "diff", "development", "production", "--config", str(full_yaml)])
		assert r.exit_code == 0, r.output
		assert "debug" in r.output
		assert "require_mfa" in r.output
		assert "mock_mpesa" in r.output

	def test_same_env_reports_no_differences(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "diff", "development", "development", "--config", str(full_yaml)])
		assert r.exit_code == 0
		assert "no differences" in r.output

	def test_unknown_from_env_exits_nonzero(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "diff", "ghost", "production", "--config", str(full_yaml)])
		assert r.exit_code != 0

	def test_unknown_to_env_exits_nonzero(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "diff", "development", "ghost", "--config", str(full_yaml)])
		assert r.exit_code != 0

	def test_diff_count_shown(self, runner, full_yaml):
		r = runner.invoke(forge, ["env", "diff", "development", "production", "--config", str(full_yaml)])
		assert "field(s) differ" in r.output


# ── CLI: forge env deploy ─────────────────────────────────────────────────────

class TestEnvDeploy:
	def test_dry_run_no_changes(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "deploy", "production", "--dry-run", "--skip-migrate",
			"--config", str(full_yaml),
		])
		assert r.exit_code == 0, r.output
		assert "DRY RUN" in r.output
		assert "dry run" in r.output

	def test_preflight_passes_for_valid_config(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "deploy", "production", "--dry-run", "--skip-migrate",
			"--config", str(full_yaml),
		])
		assert "[OK] Database URI configured" in r.output
		assert "[OK] Production requires MFA" in r.output

	def test_preflight_fails_missing_db_uri(self, runner, tmp_path):
		content = textwrap.dedent("""
			default_environment: development
			environments:
			  production:
			    database_uri: ""
			    require_mfa: true
		""")
		p = tmp_path / "cfg.yaml"
		p.write_text(content)
		r = runner.invoke(forge, [
			"env", "deploy", "production", "--dry-run", "--skip-migrate",
			"--config", str(p),
		])
		assert r.exit_code != 0
		assert "[FAIL] Database URI configured" in r.output

	def test_preflight_fails_prod_without_mfa(self, runner, tmp_path):
		content = textwrap.dedent("""
			default_environment: production
			environments:
			  production:
			    database_uri: "postgresql://host/db"
			    require_mfa: false
		""")
		p = tmp_path / "cfg.yaml"
		p.write_text(content)
		r = runner.invoke(forge, [
			"env", "deploy", "production", "--dry-run", "--skip-migrate",
			"--config", str(p),
		])
		assert r.exit_code != 0
		assert "[FAIL] Production requires MFA" in r.output

	def test_unknown_environment_exits_nonzero(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "deploy", "ghost", "--dry-run", "--config", str(full_yaml),
		])
		assert r.exit_code != 0


# ── CLI: forge env promote ────────────────────────────────────────────────────

class TestEnvPromote:
	def test_promote_with_confirm_flag(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "promote", "staging", "production",
			"--confirm", "--config", str(full_yaml),
		])
		assert r.exit_code == 0, r.output
		assert "staging" in r.output
		assert "production" in r.output
		assert "NOTE" in r.output

	def test_promote_unknown_source_exits_nonzero(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "promote", "ghost", "production",
			"--confirm", "--config", str(full_yaml),
		])
		assert r.exit_code != 0

	def test_promote_unknown_target_exits_nonzero(self, runner, full_yaml):
		r = runner.invoke(forge, [
			"env", "promote", "staging", "ghost",
			"--confirm", "--config", str(full_yaml),
		])
		assert r.exit_code != 0


# ── Deployment log (unit, no DB) ──────────────────────────────────────────────

class TestDeploymentLog:
	def test_log_deployment_returns_none_outside_app_context(self):
		# no Flask app context — should return None gracefully
		result = log_deployment("production", "SUCCESS")
		assert result is None

	def test_log_deployment_accepts_all_kwargs(self):
		result = log_deployment(
			"staging", "PROMOTE",
			source_env="development",
			notes="automated CI promote",
		)
		assert result is None  # outside app context — non-fatal
