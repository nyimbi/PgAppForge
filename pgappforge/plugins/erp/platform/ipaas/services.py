"""iPaaS integration service."""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.ipaas.models import ConnectorDefinition, ConnectorInstance, IntegrationFlow, IntegrationRun

_FIELD_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_SECRET_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "bearer_token",
    "client_secret",
    "password",
    "secret",
    "token",
}
_VALID_AUTH_TYPES = {"NONE", "BASIC", "BEARER", "OAUTH2", "APIKEY"}
_VALID_PROTOCOLS = {"REST", "SOAP", "DB", "FILE", "QUEUE"}
_VALID_TRANSFORMS = {"UPPER", "LOWER"}
_VALID_TRIGGER_TYPES = {"WEBHOOK", "SCHEDULE", "EVENT"}


def _uuid() -> str:
    return str(uuid.uuid4())


class IntegrationServiceError(Exception):
    """Base error for iPaaS service domain violations."""


class InvalidIntegrationDefinitionError(IntegrationServiceError):
    """Connector, flow, mapping, or payload input is invalid."""


class ConnectorNotFoundError(IntegrationServiceError):
    """No connector definition or instance exists for the requested id."""


class FlowNotFoundError(IntegrationServiceError):
    """No integration flow exists for the requested id."""


class IntegrationService:
    def register_connector(
        self,
        name: str,
        protocol: str,
        auth_type: str | None = None,
        config_schema: dict | None = None,
        session: Any = None,
    ) -> ConnectorDefinition:
        name = self._require_non_empty(name, "name", max_length=100)
        protocol = self._normalize_choice(protocol, _VALID_PROTOCOLS, "protocol")
        auth_type = self._normalize_choice(auth_type or "NONE", _VALID_AUTH_TYPES, "auth_type")
        config_schema = self._validate_config_schema(config_schema)
        existing = (
            session.execute(
                sa.select(ConnectorDefinition).where(ConnectorDefinition.name == name)
            ).scalar_one_or_none()
            if session is not None
            else None
        )
        if existing:
            return existing
        defn = ConnectorDefinition(
            id=_uuid(),
            name=name,
            protocol=protocol,
            auth_type=auth_type,
            config_schema=config_schema,
        )
        if session is not None:
            session.add(defn)
        return defn

    def create_instance(
        self,
        definition_id: str,
        tenant_id: str,
        name: str,
        config: dict | None = None,
        session: Any = None,
    ) -> ConnectorInstance:
        definition_id = self._require_non_empty(definition_id, "definition_id", max_length=36)
        tenant_id = self._require_non_empty(tenant_id, "tenant_id", max_length=36)
        name = self._require_non_empty(name, "name", max_length=200)
        config = self._validate_config(config)
        if session is not None and self._get_model(session, ConnectorDefinition, definition_id) is None:
            raise ConnectorNotFoundError(f"ConnectorDefinition {definition_id!r} was not found")
        inst = ConnectorInstance(
            id=_uuid(),
            definition_id=definition_id,
            tenant_id=tenant_id,
            name=name,
            config=config,
        )
        if session is not None:
            session.add(inst)
        return inst

    def create_flow(
        self,
        tenant_id: str,
        name: str,
        trigger_type: str,
        source_id: str,
        target_id: str,
        mapping: list[dict[str, Any]],
        session: Any,
    ) -> IntegrationFlow:
        self._require_session(session)
        tenant_id = self._require_non_empty(tenant_id, "tenant_id", max_length=36)
        name = self._require_non_empty(name, "name", max_length=200)
        trigger_type = self._normalize_choice(trigger_type, _VALID_TRIGGER_TYPES, "trigger_type")
        source_id = self._require_non_empty(source_id, "source_id", max_length=36)
        target_id = self._require_non_empty(target_id, "target_id", max_length=36)
        mapping = self._validate_flow_mapping(mapping)
        self._get_connector_instance(session, source_id, tenant_id, "source_id")
        self._get_connector_instance(session, target_id, tenant_id, "target_id")
        flow = IntegrationFlow(
            id=_uuid(),
            tenant_id=tenant_id,
            name=name,
            trigger_type=trigger_type,
            source_connector_id=source_id,
            target_connector_id=target_id,
            mapping=mapping,
        )
        session.add(flow)
        return flow

    def _resolve_value(
        self,
        record: dict[str, Any],
        source_field: str,
        transform: str | None = None,
    ) -> Any:
        if not isinstance(record, dict):
            raise InvalidIntegrationDefinitionError("payload must be a JSON object")
        if source_field.startswith("$"):
            value = self._read_payload_field(record, source_field[1:])
        else:
            value = source_field
        if transform == "upper" and isinstance(value, str):
            value = value.upper()
        elif transform == "lower" and isinstance(value, str):
            value = value.lower()
        elif transform is not None:
            raise InvalidIntegrationDefinitionError(f"Unsupported transform {transform!r}")
        return value

    def execute_flow(self, flow_id: str, payload: dict[str, Any], session: Any) -> IntegrationRun:
        self._require_session(session)
        flow_id = self._require_non_empty(flow_id, "flow_id", max_length=36)
        if not isinstance(payload, dict):
            raise InvalidIntegrationDefinitionError("payload must be a JSON object")
        flow = self._get_model(session, IntegrationFlow, flow_id)
        if flow is None:
            raise FlowNotFoundError(f"IntegrationFlow {flow_id!r} was not found")
        if getattr(flow, "is_active", True) is False:
            raise InvalidIntegrationDefinitionError(f"IntegrationFlow {flow_id!r} is inactive")

        run = IntegrationRun(id=_uuid(), flow_id=flow_id, tenant_id=flow.tenant_id)
        session.add(run)
        processed = 0
        errors = 0
        status = "COMPLETED"
        try:
            mapped: dict[str, Any] = {}
            for item in self._validate_flow_mapping(flow.mapping):
                mapped[item["target_field"]] = self._resolve_value(
                    payload,
                    item["source_field"],
                    item.get("transform"),
                )
            processed = 1
        except IntegrationServiceError:
            errors = 1
            status = "FAILED"
        completed_at = datetime.now(timezone.utc)
        run.records_processed = processed
        run.errors = errors
        run.status = status
        run.completed_at = completed_at
        session.execute(
            sa.update(IntegrationRun).where(IntegrationRun.id == run.id).values(
                records_processed=processed,
                errors=errors,
                status=status,
                completed_at=completed_at,
            )
        )
        return run

    @staticmethod
    def _require_non_empty(value: str, field_name: str, max_length: int | None = None) -> str:
        if not isinstance(value, str):
            raise InvalidIntegrationDefinitionError(f"{field_name} must be a string")
        text = value.strip()
        if not text:
            raise InvalidIntegrationDefinitionError(f"{field_name} is required")
        if max_length is not None and len(text) > max_length:
            raise InvalidIntegrationDefinitionError(
                f"{field_name} must be at most {max_length} characters"
            )
        return text

    @staticmethod
    def _normalize_choice(value: str, choices: set[str], field_name: str) -> str:
        text = IntegrationService._require_non_empty(value, field_name).upper()
        if text not in choices:
            allowed = ", ".join(sorted(choices))
            raise InvalidIntegrationDefinitionError(
                f"Invalid {field_name} {value!r}; expected one of {allowed}"
            )
        return text

    @staticmethod
    def _require_session(session: Any) -> None:
        if session is None:
            raise InvalidIntegrationDefinitionError("session is required")

    @staticmethod
    def _get_model(session: Any, model: type, model_id: str) -> Any | None:
        getter = getattr(session, "get", None)
        if getter is None:
            raise InvalidIntegrationDefinitionError("session must provide get(model, id)")
        return getter(model, model_id)

    def _get_connector_instance(
        self,
        session: Any,
        connector_id: str,
        tenant_id: str,
        field_name: str,
    ) -> ConnectorInstance:
        connector = self._get_model(session, ConnectorInstance, connector_id)
        if connector is None:
            raise ConnectorNotFoundError(f"ConnectorInstance {connector_id!r} was not found")
        if connector.tenant_id != tenant_id:
            raise InvalidIntegrationDefinitionError(
                f"{field_name} connector does not belong to tenant {tenant_id!r}"
            )
        if getattr(connector, "status", "ACTIVE") != "ACTIVE":
            raise InvalidIntegrationDefinitionError(
                f"{field_name} connector {connector_id!r} is not active"
            )
        return connector

    def _validate_config_schema(self, value: Any) -> dict | None:
        if value is None:
            return None
        schema = self._validate_json_object(value, "config_schema")
        schema_type = schema.get("type")
        if schema_type is not None and schema_type != "object":
            raise InvalidIntegrationDefinitionError("config_schema type must be 'object'")
        properties = schema.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise InvalidIntegrationDefinitionError("config_schema properties must be an object")
        required = schema.get("required")
        if required is not None and (
            not isinstance(required, list) or not all(isinstance(item, str) for item in required)
        ):
            raise InvalidIntegrationDefinitionError("config_schema required must be a list of strings")
        return schema

    def _validate_config(self, value: Any) -> dict | None:
        if value is None:
            return None
        config = self._validate_json_object(value, "config")
        for key in config:
            if str(key).lower() in _SECRET_CONFIG_KEYS:
                raise InvalidIntegrationDefinitionError(
                    f"config must store credential references, not plaintext {key!r}"
                )
        return config

    def _validate_flow_mapping(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not value:
            raise InvalidIntegrationDefinitionError("mapping must be a non-empty list")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise InvalidIntegrationDefinitionError(
                    f"mapping item {index} must be a JSON object"
                )
            source_field = self._require_non_empty(
                item.get("source_field"),
                f"mapping[{index}].source_field",
                max_length=200,
            )
            target_field = self._require_field_path(
                item.get("target_field"),
                f"mapping[{index}].target_field",
            )
            if source_field.startswith("$"):
                self._require_field_path(
                    source_field[1:],
                    f"mapping[{index}].source_field",
                )
            transform = item.get("transform")
            if transform is not None:
                transform = self._normalize_choice(
                    transform,
                    _VALID_TRANSFORMS,
                    f"mapping[{index}].transform",
                ).lower()
            normalized.append(
                {
                    "source_field": source_field,
                    "target_field": target_field,
                    **({"transform": transform} if transform else {}),
                }
            )
        self._ensure_json_serializable(normalized, "mapping")
        return normalized

    def _validate_json_object(self, value: Any, field_name: str) -> dict:
        if not isinstance(value, dict):
            raise InvalidIntegrationDefinitionError(f"{field_name} must be a JSON object")
        self._ensure_json_serializable(value, field_name)
        return dict(value)

    @staticmethod
    def _ensure_json_serializable(value: Any, field_name: str) -> None:
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise InvalidIntegrationDefinitionError(
                f"{field_name} must be JSON serializable"
            ) from exc

    def _require_field_path(self, value: str, field_name: str) -> str:
        text = self._require_non_empty(value, field_name, max_length=200)
        if not _FIELD_PATH_RE.fullmatch(text):
            raise InvalidIntegrationDefinitionError(
                f"{field_name} must be a dotted field path"
            )
        return text

    def _read_payload_field(self, record: dict[str, Any], field_path: str) -> Any:
        self._require_field_path(field_path, "source_field")
        current: Any = record
        for part in field_path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise InvalidIntegrationDefinitionError(
                    f"payload is missing source field {field_path!r}"
                )
            current = current[part]
        return current


__all__ = [
    "ConnectorNotFoundError",
    "FlowNotFoundError",
    "IntegrationService",
    "IntegrationServiceError",
    "InvalidIntegrationDefinitionError",
]
