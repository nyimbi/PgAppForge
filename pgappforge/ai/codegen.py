"""
pgappforge/ai/codegen.py

LLM-powered PgAppForge module generation from natural language descriptions.

Config (Flask app.config):
    LITELLM_URL     = "http://84.247.181.100:4000/v1"
    LITELLM_API_KEY = "sk-pjs-litellm-master-key"
    CODEGEN_MODEL   = "gpt-4o"

Usage:

    gen = PgAppForgeCodegen()

    module = gen.generate(
        "A supplier invoice with vendor name, phone number, amount in KES, "
        "invoice date, and approval status",
        domain="finance",
        output_dir=Path("pgappforge/plugins/erp/finance/supplier_invoice/"),
    )

    print(module.module_name)   # supplier_invoice
    print(module.fields)        # [{"name": "vendor_name", ...}, ...]

    # Iterative refinement
    module = gen.refine(module, "Add an M-Pesa payment reference field (+254 phone)")
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class GeneratedModule:
	"""Complete PgAppForge module generated from a business description."""

	module_name: str        # snake_case module name
	model_code: str         # SQLAlchemy model (Python, tabs)
	view_code: str          # FAB ModelView (Python, tabs)
	migration_code: str     # Alembic migration script (Python, tabs)
	test_code: str          # pytest test cases (Python, tabs)
	plugin_init_code: str   # __init__.py plugin class (Python, tabs)
	description: str        # original business description
	fields: list[dict]      # parsed field definitions


# ── Codegen ───────────────────────────────────────────────────────────────────

class PgAppForgeCodegen:
	"""Generate complete PgAppForge modules from natural language descriptions.

	Uses Claude (via LiteLLM gateway or direct Anthropic) to generate:
	- SQLAlchemy model with proper PostgreSQL types
	- FAB ModelView with list/search/form columns
	- Alembic migration
	- pytest fixtures and tests
	- Plugin ``__init__.py``

	All config is read lazily from the Flask app context so it is safe to
	instantiate at module import time.
	"""

	SYSTEM_PROMPT = """You are a PgAppForge expert code generator. Generate production-quality Python code.

PgAppForge conventions:
- SQLAlchemy 2.x with Mapped[] annotations
- TABS (not spaces) for indentation
- UUID7 PKs: id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
- Table names: prefix with domain, e.g. "fin_", "hcm_", "crm_", "pgaf_"
- Timestamps: created_at/updated_at as DateTime(timezone=True)
- Amounts always in integer CENTS (never float)
- BigInteger for amounts >1B, Integer otherwise
- JSONB for flexible metadata
- All models in pgappforge/plugins/erp/<domain>/<module>/models.py
- All views in pgappforge/plugins/erp/<domain>/<module>/views.py
- Plugin class in pgappforge/plugins/erp/<domain>/<module>/__init__.py

Return ONLY valid JSON with these exact keys:
{
  "module_name": "snake_case_name",
  "table_prefix": "fin_",
  "fields": [{"name": "...", "type": "...", "nullable": true, "description": "..."}],
  "model_code": "complete Python model code with TABS",
  "view_code": "complete FAB ModelView with TABS",
  "migration_code": "complete Alembic migration with TABS",
  "test_code": "complete pytest tests with TABS",
  "plugin_init_code": "complete __init__.py plugin with TABS"
}"""

	def __init__(self) -> None:
		self._client = None

	# ── Public API ────────────────────────────────────────────────────────────

	def generate(
		self,
		description: str,
		*,
		domain: str = "platform",
		output_dir: Path | str | None = None,
	) -> GeneratedModule:
		"""Generate a complete PgAppForge module from a business description.

		Args:
			description: Natural language description of the business entity.
			    Example: "A supplier invoice tracking system for M-Pesa payments
			    with fields for vendor name, phone number, amount in KES,
			    invoice date, and approval status"
			domain: ERP domain — ``finance``, ``hcm``, ``crm``, ``operations``,
			    or ``platform``.
			output_dir: If provided, write the generated files here.

		Returns:
			:class:`GeneratedModule` with all generated code and field metadata.

		Raises:
			:exc:`json.JSONDecodeError`: If the LLM returns non-parseable JSON.
			:exc:`pgappforge.plugins.erp.platform.nlp.client.LLMError`:
			    If the LiteLLM proxy is unreachable.
		"""
		client = self._get_client()
		model = self._codegen_model(client)

		messages = [
			{"role": "system", "content": self.SYSTEM_PROMPT},
			{
				"role": "user",
				"content": f"Domain: {domain}\n\nBusiness requirement:\n{description}",
			},
		]

		log.info("Codegen: generating module for domain=%s", domain)
		response_text = client.chat(messages, model=model, max_tokens=4096, temperature=0.1)

		data = json.loads(self._extract_json(response_text))
		module = self._build_module(data, description)

		if output_dir is not None:
			self.write_files(module, Path(output_dir))

		return module

	def write_files(self, module: GeneratedModule, output_dir: Path) -> list[Path]:
		"""Write generated module files to disk.

		Args:
			module: A :class:`GeneratedModule` instance.
			output_dir: Directory to write ``models.py``, ``views.py``,
			    ``__init__.py`` into.  Created if it does not exist.

		Returns:
			List of :class:`Path` objects for every file written.
		"""
		output_dir = Path(output_dir)
		output_dir.mkdir(parents=True, exist_ok=True)
		written: list[Path] = []

		core_files = {
			"models.py": module.model_code,
			"views.py": module.view_code,
			"__init__.py": module.plugin_init_code,
		}
		for filename, content in core_files.items():
			path = output_dir / filename
			path.write_text(content, encoding="utf-8")
			written.append(path)
			log.info("Codegen: wrote %s", path)

		# Migration
		migrations_dir = Path("migrations/versions")
		if migrations_dir.exists() and module.migration_code:
			mig_path = migrations_dir / f"{int(time.time())}_{module.module_name}.py"
			mig_path.write_text(module.migration_code, encoding="utf-8")
			written.append(mig_path)
			log.info("Codegen: wrote migration %s", mig_path)

		# Tests
		tests_dir = Path("tests/ci")
		if tests_dir.exists() and module.test_code:
			test_path = tests_dir / f"test_{module.module_name}.py"
			test_path.write_text(module.test_code, encoding="utf-8")
			written.append(test_path)
			log.info("Codegen: wrote test %s", test_path)

		return written

	def refine(self, module: GeneratedModule, instruction: str) -> GeneratedModule:
		"""Iteratively refine a generated module with a natural language instruction.

		Args:
			module: The :class:`GeneratedModule` to refine.
			instruction: What to change, e.g.
			    ``"Add an M-Pesa phone field with Kenya +254 validation"``.

		Returns:
			A new :class:`GeneratedModule` with the requested changes applied.
		"""
		client = self._get_client()
		model = self._codegen_model(client)

		prompt = (
			f"Existing module '{module.module_name}':\n\n"
			f"Current model code:\n```python\n{module.model_code[:2000]}\n```\n\n"
			f"Modification requested:\n{instruction}\n\n"
			"Return ONLY the updated JSON with the same keys as before."
		)

		response_text = client.chat(
			[
				{"role": "system", "content": self.SYSTEM_PROMPT},
				{"role": "user", "content": prompt},
			],
			model=model,
			max_tokens=4096,
			temperature=0.1,
		)

		data = json.loads(self._extract_json(response_text))
		return GeneratedModule(
			module_name=data.get("module_name", module.module_name),
			model_code=data.get("model_code", module.model_code),
			view_code=data.get("view_code", module.view_code),
			migration_code=data.get("migration_code", module.migration_code),
			test_code=data.get("test_code", module.test_code),
			plugin_init_code=data.get("plugin_init_code", module.plugin_init_code),
			description=module.description,
			fields=data.get("fields", module.fields),
		)

	# ── Internals ─────────────────────────────────────────────────────────────

	def _get_client(self):
		if self._client is None:
			from pgappforge.plugins.erp.platform.nlp.client import LLMClient
			self._client = LLMClient()
		return self._client

	@staticmethod
	def _codegen_model(client) -> str:
		"""Read CODEGEN_MODEL from Flask config, fall back to client default."""
		try:
			from flask import current_app  # type: ignore[import-untyped]
			return current_app.config.get("CODEGEN_MODEL", client._model)
		except RuntimeError:
			return "gpt-4o"

	@staticmethod
	def _build_module(data: dict[str, Any], description: str) -> GeneratedModule:
		return GeneratedModule(
			module_name=data["module_name"],
			model_code=data.get("model_code", ""),
			view_code=data.get("view_code", ""),
			migration_code=data.get("migration_code", ""),
			test_code=data.get("test_code", ""),
			plugin_init_code=data.get("plugin_init_code", ""),
			description=description,
			fields=data.get("fields", []),
		)

	@staticmethod
	def _extract_json(text: str) -> str:
		"""Extract the first JSON object from an LLM response string."""
		# Prefer fenced code blocks
		m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
		if m:
			return m.group(1)
		# Fall back to first bare JSON object
		m = re.search(r"(\{.*\})", text, re.DOTALL)
		if m:
			return m.group(1)
		return text


# ── CLI helper ────────────────────────────────────────────────────────────────

def codegen_cli_command(
	description: str,
	domain: str = "platform",
	output: str = "./generated/",
) -> None:
	"""Thin wrapper called by ``flask forge gen module``.

	Args:
		description: Natural language business requirement.
		domain: ERP domain.
		output: Output directory path.
	"""
	import click

	gen = PgAppForgeCodegen()
	click.echo(f"Generating module: {description[:80]}...")

	module = gen.generate(description, domain=domain, output_dir=Path(output))

	click.echo(f"Generated module: {module.module_name}")
	if module.fields:
		click.echo(f"  Fields: {', '.join(f['name'] for f in module.fields)}")
	click.echo(f"  Files written to: {output}")


__all__ = ["PgAppForgeCodegen", "GeneratedModule", "codegen_cli_command"]
