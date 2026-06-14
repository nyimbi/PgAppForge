"""iPaaS integration service."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.ipaas.models import ConnectorDefinition, ConnectorInstance, IntegrationFlow, IntegrationRun


def _uuid() -> str:
	return str(uuid.uuid4())


class IntegrationService:
	def register_connector(self, name: str, protocol: str, auth_type: str | None = None, config_schema: dict | None = None, session: Any = None) -> ConnectorDefinition:
		existing = (session.execute(sa.select(ConnectorDefinition).where(ConnectorDefinition.name == name)).scalar_one_or_none()) if session else None
		if existing:
			return existing
		defn = ConnectorDefinition(id=_uuid(), name=name, protocol=protocol, auth_type=auth_type, config_schema=config_schema)
		if session:
			session.add(defn)
		return defn

	def create_instance(self, definition_id: str, tenant_id: str, name: str, config: dict | None = None, session: Any = None) -> ConnectorInstance:
		inst = ConnectorInstance(id=_uuid(), definition_id=definition_id, tenant_id=tenant_id, name=name, config=config)
		if session:
			session.add(inst)
		return inst

	def create_flow(self, tenant_id: str, name: str, trigger_type: str, source_id: str, target_id: str, mapping: list[dict[str, Any]], session: Any) -> IntegrationFlow:
		flow = IntegrationFlow(id=_uuid(), tenant_id=tenant_id, name=name, trigger_type=trigger_type, source_connector_id=source_id, target_connector_id=target_id, mapping=mapping)
		session.add(flow)
		return flow

	def _resolve_value(self, record: dict[str, Any], source_field: str, transform: str | None = None) -> Any:
		if source_field.startswith("$"):
			value = record.get(source_field[1:])
		else:
			value = source_field
		if transform == "upper" and isinstance(value, str):
			value = value.upper()
		elif transform == "lower" and isinstance(value, str):
			value = value.lower()
		return value

	def execute_flow(self, flow_id: str, payload: dict[str, Any], session: Any) -> IntegrationRun:
		flow = session.get(IntegrationFlow, flow_id)
		run = IntegrationRun(id=_uuid(), flow_id=flow_id, tenant_id=flow.tenant_id)
		session.add(run)
		mapped: dict[str, Any] = {}
		processed = 0
		errors = 0
		try:
			for m in flow.mapping:
				mapped[m["target_field"]] = self._resolve_value(payload, m["source_field"], m.get("transform"))
			processed = 1
		except Exception:
			errors = 1
		session.execute(
			sa.update(IntegrationRun).where(IntegrationRun.id == run.id).values(
				records_processed=processed, errors=errors, status="COMPLETED", completed_at=datetime.now(timezone.utc)
			)
		)
		return run


__all__ = ["IntegrationService"]
