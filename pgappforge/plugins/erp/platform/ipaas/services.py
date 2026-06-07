"""
pgappforge/plugins/erp/platform/ipaas/services.py

IntegrationService — connector registration, flow definition, flow execution,
field mapping with transform resolution, and run history.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("iPaaS event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("ipaas.execute_flow")
	def _bpm_execute_flow(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "ipaas.execute_flow", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — iPaaS BPM actions not registered")


# ---------------------------------------------------------------------------
# Field transform resolution (mirrors Rules Engine _resolve_value pattern)
# ---------------------------------------------------------------------------

def _resolve_value(value: Any, transform: str | None, payload: dict[str, Any]) -> Any:
	"""Apply a simple transform string to a field value.

	Supported transforms:
	  upper        — str.upper()
	  lower        — str.lower()
	  str          — str()
	  int          — int()
	  float        — float()
	  cents        — multiply by 100 and cast to int (float → cents)
	  units        — divide by 100 (cents → units float)
	  strip        — str.strip()
	  None/unknown — identity
	"""
	if not transform:
		return value
	t = transform.lower().strip()
	try:
		if t == "upper":
			return str(value).upper()
		elif t == "lower":
			return str(value).lower()
		elif t == "str":
			return str(value)
		elif t == "int":
			return int(value)
		elif t == "float":
			return float(value)
		elif t == "cents":
			return int(float(value) * 100)
		elif t == "units":
			return float(value) / 100.0
		elif t == "strip":
			return str(value).strip()
	except (ValueError, TypeError) as exc:
		log.debug("iPaaS: transform %r failed on %r: %s", t, value, exc)
	return value


def _apply_mapping(
	payload: dict[str, Any],
	mapping: list[dict[str, Any]],
) -> dict[str, Any]:
	"""Transform a source payload dict into a target dict using the flow mapping.

	mapping entries: {source_field: str, target_field: str, transform?: str}
	"""
	result: dict[str, Any] = {}
	for entry in mapping:
		src = entry.get("source_field", "")
		tgt = entry.get("target_field", "") or src
		transform = entry.get("transform")
		value = payload.get(src)
		result[tgt] = _resolve_value(value, transform, payload)
	return result


# ---------------------------------------------------------------------------
# IntegrationService
# ---------------------------------------------------------------------------

class IntegrationService:
	"""Service layer for the iPaaS Integration Platform."""

	# ------------------------------------------------------------------
	# Connector management
	# ------------------------------------------------------------------

	def register_connector(
		self,
		name: str,
		protocol: str,
		tenant_id: str,
		session: Any,
		*,
		version: str = "1.0.0",
		auth_type: str = "NONE",
		config_schema: dict[str, Any] | None = None,
	) -> Any:
		"""Register a new connector definition.

		Emits ConnectorRegisteredEvent.
		"""
		from pgappforge.plugins.erp.platform.ipaas.models import ConnectorDefinition
		from pgappforge.plugins.erp.platform.ipaas.events import ConnectorRegisteredEvent

		connector = ConnectorDefinition(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			version=version,
			protocol=protocol.upper(),
			auth_type=auth_type.upper(),
			config_schema=config_schema or {},
			is_active=True,
		)
		session.add(connector)
		session.flush()

		_emit(
			ConnectorRegisteredEvent(
				aggregate_id=connector.id,
				aggregate_type="ConnectorDefinition",
				tenant_id=tenant_id,
				connector_id=connector.id,
				connector_name=name,
				protocol=protocol.upper(),
			),
			session,
		)
		log.info("iPaaS: registered connector %r [%s]", name, protocol)
		return connector

	def create_flow(
		self,
		name: str,
		trigger_type: str,
		tenant_id: str,
		session: Any,
		*,
		source_connector_id: str | None = None,
		target_connector_id: str | None = None,
		mapping: list[dict[str, Any]] | None = None,
	) -> Any:
		"""Define an integration flow."""
		from pgappforge.plugins.erp.platform.ipaas.models import IntegrationFlow

		flow = IntegrationFlow(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			trigger_type=trigger_type.upper(),
			source_connector_id=source_connector_id,
			target_connector_id=target_connector_id,
			mapping=mapping or [],
			is_active=True,
		)
		session.add(flow)
		session.flush()
		log.info("iPaaS: created flow %r [%s]", name, trigger_type)
		return flow

	# ------------------------------------------------------------------
	# Execution
	# ------------------------------------------------------------------

	def execute_flow(
		self,
		flow_id: str,
		payload: dict[str, Any] | list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Execute an integration flow against a payload.

		Applies field mapping/transforms and returns transformed records.
		Creates an IntegrationRun record. Emits FlowExecutedEvent or
		IntegrationErrorEvent on failure.
		"""
		from pgappforge.plugins.erp.platform.ipaas.models import IntegrationFlow, IntegrationRun
		from pgappforge.plugins.erp.platform.ipaas.events import FlowExecutedEvent, IntegrationErrorEvent

		flow = session.execute(
			sa.select(IntegrationFlow).where(IntegrationFlow.id == flow_id)
		).scalar_one_or_none()
		if flow is None:
			raise ValueError(f"IntegrationFlow {flow_id} not found")

		run = IntegrationRun(
			id=_uuid4(),
			tenant_id=flow.tenant_id,
			flow_id=flow_id,
			started_at=_now(),
			status="RUNNING",
			records_processed=0,
			errors_count=0,
		)
		session.add(run)
		session.flush()

		# Normalise to list
		records = payload if isinstance(payload, list) else [payload]
		mapping: list[dict[str, Any]] = flow.mapping or []

		processed = 0
		errors = 0
		results: list[dict[str, Any]] = []

		for record in records:
			try:
				transformed = _apply_mapping(record, mapping) if mapping else record
				results.append(transformed)
				processed += 1
			except Exception as exc:
				log.warning("iPaaS: flow %s transform error: %s", flow_id, exc)
				errors += 1

		run.records_processed = processed
		run.errors_count = errors
		run.completed_at = _now()
		run.status = "FAILED" if errors == processed else ("PARTIAL" if errors > 0 else "SUCCESS")
		session.flush()

		if errors > 0:
			_emit(
				IntegrationErrorEvent(
					aggregate_id=flow_id,
					aggregate_type="IntegrationFlow",
					tenant_id=flow.tenant_id,
					flow_id=flow_id,
					run_id=run.id,
					error_message=f"{errors} record(s) failed transform",
					errors_count=errors,
				),
				session,
			)

		_emit(
			FlowExecutedEvent(
				aggregate_id=flow_id,
				aggregate_type="IntegrationFlow",
				tenant_id=flow.tenant_id,
				flow_id=flow_id,
				run_id=run.id,
				records_processed=processed,
				errors_count=errors,
				status=run.status,
			),
			session,
		)

		run.result = results  # type: ignore[attr-defined] — convenience attr, not persisted
		return run

	# ------------------------------------------------------------------
	# History
	# ------------------------------------------------------------------

	def get_flow_history(
		self,
		flow_id: str,
		session: Any,
		*,
		limit: int = 50,
	) -> list[dict[str, Any]]:
		"""Return the most recent IntegrationRun records for a flow."""
		from pgappforge.plugins.erp.platform.ipaas.models import IntegrationRun

		runs = session.execute(
			sa.select(IntegrationRun)
			.where(IntegrationRun.flow_id == flow_id)
			.order_by(IntegrationRun.started_at.desc())
			.limit(limit)
		).scalars().all()

		return [
			{
				"run_id": r.id,
				"started_at": str(r.started_at),
				"completed_at": str(r.completed_at) if r.completed_at else None,
				"records_processed": r.records_processed,
				"errors_count": r.errors_count,
				"status": r.status,
			}
			for r in runs
		]
