"""
pgappforge/env_pipeline/config.py

Environment configuration model for the dev/test/prod pipeline.
Loads from pgappforge.yaml with ${ENV_VAR} substitution.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EnvironmentConfig:
	"""Configuration for a single deployment environment."""

	name: str
	database_uri: str
	debug: bool = False
	ai_features: bool = True
	mock_mpesa: bool = False
	require_mfa: bool = False
	extra_plugins: list[str] = field(default_factory=list)
	env_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class PgAppForgeConfig:
	"""Top-level project configuration loaded from pgappforge.yaml."""

	environments: dict[str, EnvironmentConfig]
	default_environment: str = "development"

	# ── Loading ──────────────────────────────────────────────────────────────

	@classmethod
	def load(cls, path: str | Path = "pgappforge.yaml") -> "PgAppForgeConfig":
		"""Load from pgappforge.yaml, resolving ``${ENV_VAR}`` substitutions.

		If the file does not exist a sensible default config is returned so CLI
		commands work out of the box without a config file.
		"""
		path = Path(path)

		if not path.exists():
			return cls._default()

		raw = path.read_text(encoding="utf-8")
		raw = cls._resolve_env_vars(raw)

		data: dict[str, Any] = yaml.safe_load(raw) or {}
		envs: dict[str, EnvironmentConfig] = {}

		valid_fields = set(EnvironmentConfig.__dataclass_fields__)  # type: ignore[attr-defined]
		for env_name, env_data in data.get("environments", {}).items():
			if not isinstance(env_data, dict):
				continue
			filtered = {k: v for k, v in env_data.items() if k in valid_fields}
			filtered.setdefault("name", env_name)
			filtered.setdefault("database_uri", "")
			envs[env_name] = EnvironmentConfig(**filtered)

		return cls(
			environments=envs,
			default_environment=data.get("default_environment", "development"),
		)

	# ── Helpers ──────────────────────────────────────────────────────────────

	@staticmethod
	def _resolve_env_vars(text: str) -> str:
		"""Replace ``${VAR}`` with the matching OS environment variable value."""
		def _sub(match: re.Match) -> str:
			var = match.group(1)
			return os.environ.get(var, match.group(0))

		return re.sub(r"\$\{([^}]+)\}", _sub, text)

	@classmethod
	def _default(cls) -> "PgAppForgeConfig":
		"""Sensible defaults when no pgappforge.yaml exists."""
		return cls(
			environments={
				"development": EnvironmentConfig(
					name="development",
					database_uri=os.environ.get(
						"SQLALCHEMY_DATABASE_URI",
						"postgresql://localhost/pgappforge_dev",
					),
					debug=True,
				),
				"staging": EnvironmentConfig(
					name="staging",
					database_uri=os.environ.get("STAGING_DATABASE_URI", ""),
				),
				"production": EnvironmentConfig(
					name="production",
					database_uri=os.environ.get("PROD_DATABASE_URI", ""),
					require_mfa=True,
				),
			},
			default_environment="development",
		)

	# ── Convenience ──────────────────────────────────────────────────────────

	def get_env(self, name: str | None = None) -> EnvironmentConfig:
		"""Return the named environment, falling back to ``default_environment``."""
		target = name or self.default_environment
		if target not in self.environments:
			raise KeyError(f"Environment '{target}' not found in config")
		return self.environments[target]
