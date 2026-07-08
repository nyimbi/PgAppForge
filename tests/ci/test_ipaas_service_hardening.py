"""Hardening tests for the platform iPaaS integration service."""
from __future__ import annotations

import pytest

from pgappforge.plugins.erp.platform.ipaas.models import (
    ConnectorDefinition,
    ConnectorInstance,
    IntegrationFlow,
)
from pgappforge.plugins.erp.platform.ipaas.services import (
    ConnectorNotFoundError,
    FlowNotFoundError,
    IntegrationService,
    InvalidIntegrationDefinitionError,
)


class _ScalarResult:
    def scalar_one_or_none(self):
        return None


class _Session:
    def __init__(
        self,
        *,
        definitions: dict[str, ConnectorDefinition] | None = None,
        instances: dict[str, ConnectorInstance] | None = None,
        flows: dict[str, IntegrationFlow] | None = None,
    ) -> None:
        self.definitions = definitions or {}
        self.instances = instances or {}
        self.flows = flows or {}
        self.added = []
        self.executed = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def execute(self, statement):
        self.executed.append(statement)
        return _ScalarResult()

    def get(self, model, model_id: str):
        if model is ConnectorDefinition:
            return self.definitions.get(model_id)
        if model is ConnectorInstance:
            return self.instances.get(model_id)
        if model is IntegrationFlow:
            return self.flows.get(model_id)
        return None


def _definition(definition_id: str = "def-1") -> ConnectorDefinition:
    return ConnectorDefinition(
        id=definition_id,
        name="REST",
        protocol="REST",
        auth_type="NONE",
    )


def _instance(
    connector_id: str,
    *,
    tenant_id: str = "tenant-1",
    status: str = "ACTIVE",
) -> ConnectorInstance:
    return ConnectorInstance(
        id=connector_id,
        definition_id="def-1",
        tenant_id=tenant_id,
        name=connector_id,
        status=status,
    )


def _flow(mapping: list[dict]) -> IntegrationFlow:
    return IntegrationFlow(
        id="flow-1",
        tenant_id="tenant-1",
        name="Customer sync",
        trigger_type="WEBHOOK",
        source_connector_id="source-1",
        target_connector_id="target-1",
        mapping=mapping,
        is_active=True,
    )


def test_register_connector_normalizes_and_rejects_invalid_definitions():
    session = _Session()
    service = IntegrationService()

    definition = service.register_connector(
        " Customer API ",
        "rest",
        config_schema={"type": "object", "properties": {}},
        session=session,
    )

    assert definition.name == "Customer API"
    assert definition.protocol == "REST"
    assert definition.auth_type == "NONE"
    assert session.added == [definition]

    with pytest.raises(InvalidIntegrationDefinitionError, match="name is required"):
        service.register_connector(" ", "REST")
    with pytest.raises(InvalidIntegrationDefinitionError, match="Invalid protocol"):
        service.register_connector("Bad", "FTP")
    with pytest.raises(InvalidIntegrationDefinitionError, match="Invalid auth_type"):
        service.register_connector("Bad", "REST", auth_type="PASSWORD")
    with pytest.raises(InvalidIntegrationDefinitionError, match="type must be 'object'"):
        service.register_connector("Bad", "REST", config_schema={"type": "array"})


def test_create_instance_requires_known_definition_and_vault_style_config_refs():
    service = IntegrationService()
    session = _Session(definitions={"def-1": _definition()})

    instance = service.create_instance(
        "def-1",
        "tenant-1",
        "Payroll connector",
        {"credential_ref": "vault://payroll-api"},
        session,
    )

    assert instance.config == {"credential_ref": "vault://payroll-api"}
    assert session.added == [instance]

    with pytest.raises(ConnectorNotFoundError, match="ConnectorDefinition"):
        service.create_instance("missing", "tenant-1", "Missing", {}, session)
    with pytest.raises(InvalidIntegrationDefinitionError, match="plaintext"):
        service.create_instance("def-1", "tenant-1", "Bad", {"password": "secret"}, session)
    with pytest.raises(InvalidIntegrationDefinitionError, match="JSON serializable"):
        service.create_instance("def-1", "tenant-1", "Bad", {"bad": object()}, session)


def test_create_flow_validates_mapping_trigger_and_tenant_pairing():
    service = IntegrationService()
    session = _Session(
        instances={
            "source-1": _instance("source-1"),
            "target-1": _instance("target-1"),
            "other-tenant": _instance("other-tenant", tenant_id="tenant-2"),
            "disabled": _instance("disabled", status="DISABLED"),
        }
    )

    flow = service.create_flow(
        "tenant-1",
        " Customer sync ",
        "webhook",
        "source-1",
        "target-1",
        [{"source_field": "$customer.name", "target_field": "display_name", "transform": "UPPER"}],
        session,
    )

    assert flow.name == "Customer sync"
    assert flow.trigger_type == "WEBHOOK"
    assert flow.mapping == [
        {"source_field": "$customer.name", "target_field": "display_name", "transform": "upper"}
    ]

    with pytest.raises(InvalidIntegrationDefinitionError, match="Invalid trigger_type"):
        service.create_flow("tenant-1", "Bad", "manual", "source-1", "target-1", [], session)
    with pytest.raises(InvalidIntegrationDefinitionError, match="non-empty list"):
        service.create_flow("tenant-1", "Bad", "WEBHOOK", "source-1", "target-1", [], session)
    with pytest.raises(InvalidIntegrationDefinitionError, match="dotted field path"):
        service.create_flow(
            "tenant-1",
            "Bad",
            "WEBHOOK",
            "source-1",
            "target-1",
            [{"source_field": "$customer.name", "target_field": "drop table"}],
            session,
        )
    with pytest.raises(InvalidIntegrationDefinitionError, match="does not belong"):
        service.create_flow(
            "tenant-1",
            "Bad",
            "WEBHOOK",
            "source-1",
            "other-tenant",
            [{"source_field": "$customer.name", "target_field": "display_name"}],
            session,
        )
    with pytest.raises(InvalidIntegrationDefinitionError, match="not active"):
        service.create_flow(
            "tenant-1",
            "Bad",
            "WEBHOOK",
            "source-1",
            "disabled",
            [{"source_field": "$customer.name", "target_field": "display_name"}],
            session,
        )


def test_execute_flow_rejects_missing_or_inactive_flows_before_creating_run():
    service = IntegrationService()

    missing_session = _Session()
    with pytest.raises(FlowNotFoundError):
        service.execute_flow("missing", {}, missing_session)
    assert missing_session.added == []

    inactive_session = _Session(flows={"flow-1": _flow([{"source_field": "$x", "target_field": "y"}])})
    inactive_session.flows["flow-1"].is_active = False
    with pytest.raises(InvalidIntegrationDefinitionError, match="inactive"):
        service.execute_flow("flow-1", {"x": "value"}, inactive_session)
    assert inactive_session.added == []


def test_execute_flow_marks_mapping_errors_as_failed_runs():
    service = IntegrationService()
    session = _Session(flows={"flow-1": _flow([{"source_field": "$missing", "target_field": "out"}])})

    run = service.execute_flow("flow-1", {"present": "value"}, session)

    assert run.status == "FAILED"
    assert run.records_processed == 0
    assert run.errors == 1
    assert session.added == [run]
    assert session.executed


def test_execute_flow_completes_valid_nested_mapping():
    service = IntegrationService()
    session = _Session(
        flows={
            "flow-1": _flow(
                [
                    {"source_field": "$customer.name", "target_field": "display_name", "transform": "lower"},
                    {"source_field": "ERP", "target_field": "source"},
                ]
            )
        }
    )

    run = service.execute_flow("flow-1", {"customer": {"name": "ALICE"}}, session)

    assert run.status == "COMPLETED"
    assert run.records_processed == 1
    assert run.errors == 0
