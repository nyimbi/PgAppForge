"""AI Composable Pipeline — LangChain LCEL-inspired Runnable protocol for PgAppForge.

Provides a uniform Runnable interface so AI steps compose cleanly:

    from pgappforge.ai.pipeline import LLMStep, SQLStep, RuleStep, Composable

    pipeline = (
        SQLStep(query="SELECT * FROM fin_ar_invoice WHERE tenant_id = :tenant_id")
        | LLMStep(system="Summarise these invoices in one sentence.")
    )

    result = pipeline.invoke({"tenant_id": "t1"}, session=session)

Every Runnable:
  - .invoke(input, **kwargs) -> output      (sync, single item)
  - .pipe(other) -> Composable              (returns new Composable)
  - .parallel(**branches) -> Composable     (fan-out, dict of results)
  - __or__(other) -> Composable             (sugar for .pipe())
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)


# ── Core protocol ────────────────────────────────────────────────────────────

class Runnable(ABC):
	"""Abstract base for all composable pipeline steps.

	The uniform interface: every step accepts any input and returns any output.
	Types are documented in subclass docstrings; not enforced at runtime so
	pipelines stay flexible.
	"""

	@abstractmethod
	def invoke(self, input: Any, **kwargs: Any) -> Any:
		"""Execute this step on *input* and return the result."""
		...

	def pipe(self, other: "Runnable") -> "Composable":
		"""Chain *other* after self — self's output becomes other's input."""
		return Composable([self, other])

	def parallel(self, **branches: "Runnable") -> "ParallelComposable":
		"""Fan *input* out to multiple named branches; collect into a dict."""
		return ParallelComposable(first=self, branches=branches)

	def __or__(self, other: "Runnable") -> "Composable":
		return self.pipe(other)

	def __repr__(self) -> str:
		return self.__class__.__name__


# ── Composition operators ────────────────────────────────────────────────────

class Composable(Runnable):
	"""A sequential chain of Runnables — output of step N feeds step N+1."""

	def __init__(self, steps: list[Runnable]) -> None:
		self._steps = steps

	def invoke(self, input: Any, **kwargs: Any) -> Any:
		result = input
		for step in self._steps:
			result = step.invoke(result, **kwargs)
		return result

	def pipe(self, other: Runnable) -> "Composable":
		if isinstance(other, Composable):
			return Composable(self._steps + other._steps)
		return Composable(self._steps + [other])

	def __repr__(self) -> str:
		return " | ".join(repr(s) for s in self._steps)


class ParallelComposable(Runnable):
	"""Runs `first` then fans the result into multiple named branches.

	invoke() returns {branch_name: branch_result, ...}.
	"""

	def __init__(self, first: Runnable, branches: dict[str, Runnable]) -> None:
		self._first = first
		self._branches = branches

	def invoke(self, input: Any, **kwargs: Any) -> dict[str, Any]:
		intermediate = self._first.invoke(input, **kwargs)
		return {name: step.invoke(intermediate, **kwargs) for name, step in self._branches.items()}

	def __repr__(self) -> str:
		return f"Parallel({self._first!r}, branches={list(self._branches)})"


class Lambda(Runnable):
	"""Wrap any callable as a Runnable step."""

	def __init__(self, fn: Any, name: str = "") -> None:
		self._fn = fn
		self._name = name or getattr(fn, "__name__", "lambda")

	def invoke(self, input: Any, **kwargs: Any) -> Any:
		return self._fn(input, **kwargs)

	def __repr__(self) -> str:
		return f"Lambda({self._name!r})"


class Passthrough(Runnable):
	"""Return input unchanged — useful for merging side-branch outputs."""

	def invoke(self, input: Any, **kwargs: Any) -> Any:
		return input

	def __repr__(self) -> str:
		return "Passthrough()"


# ── Built-in pipeline steps ──────────────────────────────────────────────────

class LLMStep(Runnable):
	"""Call an LLM via the LiteLLM gateway.

	Expects input to be a str or dict (converted to str).
	Returns the LLM completion text.

	Args:
		system:    System prompt text.
		model:     LiteLLM model string (default: 'gpt-4o-mini').
		gateway:   Base URL for LiteLLM gateway (reads LITELLM_BASE_URL env if None).
		api_key:   API key (reads LITELLM_API_KEY env if None).
	"""

	def __init__(
		self,
		system: str = "",
		model: str = "gpt-4o-mini",
		gateway: str | None = None,
		api_key: str | None = None,
		max_tokens: int = 1024,
	) -> None:
		self.system = system
		self.model = model
		self.gateway = gateway
		self.api_key = api_key
		self.max_tokens = max_tokens

	def invoke(self, input: Any, **kwargs: Any) -> str:
		import os
		try:
			import litellm
		except ImportError as exc:
			raise ImportError("LLMStep requires 'litellm': pip install litellm") from exc

		base_url = self.gateway or os.getenv("LITELLM_BASE_URL", "http://84.247.181.100:4000/v1")
		api_key = self.api_key or os.getenv("LITELLM_API_KEY", "sk-pgappforge")

		user_content = input if isinstance(input, str) else str(input)
		messages = []
		if self.system:
			messages.append({"role": "system", "content": self.system})
		messages.append({"role": "user", "content": user_content})

		log.debug("LLMStep: calling %s with %d chars", self.model, len(user_content))
		resp = litellm.completion(
			model=self.model,
			messages=messages,
			api_base=base_url,
			api_key=api_key,
			max_tokens=self.max_tokens,
		)
		return resp.choices[0].message.content or ""

	def __repr__(self) -> str:
		return f"LLMStep(model={self.model!r}, system={self.system[:30]!r})"


class SQLStep(Runnable):
	"""Execute a SQL query and return the rows.

	*query* may use ``:key`` named parameters resolved from the input dict.
	Returns a list of row dicts.

	Requires *session* to be passed as a kwarg to invoke().
	"""

	def __init__(self, query: str) -> None:
		self.query = query

	def invoke(self, input: Any, **kwargs: Any) -> list[dict[str, Any]]:
		import sqlalchemy as sa
		session = kwargs.get("session")
		if session is None:
			raise ValueError("SQLStep.invoke() requires session= kwarg")
		params = input if isinstance(input, dict) else {}
		try:
			result = session.execute(sa.text(self.query), params)
			keys = list(result.keys())
			return [dict(zip(keys, row)) for row in result.fetchall()]
		except Exception as exc:
			log.warning("SQLStep: query failed — %s", exc)
			return []

	def __repr__(self) -> str:
		q = self.query.strip()[:40].replace("\n", " ")
		return f"SQLStep({q!r})"


class RuleStep(Runnable):
	"""Run the PgAppForge rules engine against a model instance.

	Input: a SQLAlchemy model instance.
	Output: same instance (possibly mutated by set_field actions).
	Raises RulesValidationError if a 'block' action fires.
	"""

	def __init__(self, tenant_id: str = "", event: str = "on_update") -> None:
		self.tenant_id = tenant_id
		self.event = event

	def invoke(self, input: Any, **kwargs: Any) -> Any:
		try:
			from pgappforge.plugins.rules.engine import get_rules_engine
		except ImportError:
			return input
		engine = get_rules_engine()
		if engine is None:
			return input
		session = kwargs.get("session")
		engine.evaluate(
			record=input,
			event_type=self.event,
			tenant_id=self.tenant_id or getattr(input, "tenant_id", ""),
			session=session,
		)
		return input

	def __repr__(self) -> str:
		return f"RuleStep(event={self.event!r})"


class WorkflowStep(Runnable):
	"""Start a named workflow instance.

	Input: dict used as initial workflow data.
	Output: WorkflowInstance.
	"""

	def __init__(self, workflow_name: str, tenant_id: str = "") -> None:
		self.workflow_name = workflow_name
		self.tenant_id = tenant_id

	def invoke(self, input: Any, **kwargs: Any) -> Any:
		try:
			from pgappforge.workflow.engine import PgAppForgeWorkflowEngine
		except ImportError:
			return input
		engine = PgAppForgeWorkflowEngine()
		data = input if isinstance(input, dict) else {"input": input}
		session = kwargs.get("session")
		return engine.start(self.workflow_name, data, self.tenant_id, session=session)

	def __repr__(self) -> str:
		return f"WorkflowStep({self.workflow_name!r})"


class FormatStep(Runnable):
	"""Format input into a string using a Python f-string-like template.

	Template uses {key} placeholders resolved from input dict.
	"""

	def __init__(self, template: str) -> None:
		self.template = template

	def invoke(self, input: Any, **kwargs: Any) -> str:
		data = input if isinstance(input, dict) else {"value": input}
		try:
			return self.template.format(**data)
		except KeyError as exc:
			log.warning("FormatStep: missing key %s in input %s", exc, list(data.keys()))
			return self.template


__all__ = [
	"Runnable", "Composable", "ParallelComposable", "Lambda", "Passthrough",
	"LLMStep", "SQLStep", "RuleStep", "WorkflowStep", "FormatStep",
]
