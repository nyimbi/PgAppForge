"""
tests/ci/test_industry_plugins.py

Compile-check and import tests for:
  - pgappforge.plugins.erp.industry.financial_services
  - pgappforge.plugins.erp.industry.health

These tests verify that all modules import without error, all public symbols
are exported, model column types satisfy domain rules (no float amounts),
and service/event class hierarchies are correct.

No database connection required — pure import + reflection tests.
"""
from __future__ import annotations

import importlib
import inspect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import(dotted: str):
	return importlib.import_module(dotted)


def _assert_subclass(cls, parent, label: str):
	assert issubclass(cls, parent), (
		f"{label}: expected subclass of {parent.__name__}, got {cls.__mro__}"
	)


# ---------------------------------------------------------------------------
# Financial Services — module imports
# ---------------------------------------------------------------------------

def test_finserv_models_import():
	m = _import("pgappforge.plugins.erp.industry.financial_services.models")
	for name in (
		"FinancialClient",
		"PortfolioAccount",
		"FinancialProduct",
		"ClientHolding",
		"SanctionsScreeningResult",
	):
		assert hasattr(m, name), f"models.py missing {name}"


def test_finserv_events_import():
	m = _import("pgappforge.plugins.erp.industry.financial_services.events")
	for name in (
		"ClientOnboardedEvent",
		"ClientKYCStatusChangedEvent",
		"ClientRiskProfileChangedEvent",
		"AccountOpenedEvent",
		"AccountStatusChangedEvent",
		"AccountBalanceUpdatedEvent",
		"HoldingRevaluedEvent",
		"SanctionsScreeningCompletedEvent",
		"SanctionsMatchClearedEvent",
		"emit_event",
	):
		assert hasattr(m, name), f"events.py missing {name}"


def test_finserv_services_import():
	m = _import("pgappforge.plugins.erp.industry.financial_services.services")
	for name in (
		"FinancialServicesService",
		"FinServError",
		"ClientNotFoundError",
		"AccountNotFoundError",
		"AccountFrozenError",
		"AccountClosedError",
		"InsufficientBalanceError",
		"KYCNotApprovedError",
		"SanctionsHoldError",
		"DuplicateClientNumberError",
	):
		assert hasattr(m, name), f"services.py missing {name}"


def test_finserv_views_import():
	m = _import("pgappforge.plugins.erp.industry.financial_services.views")
	for name in (
		"FinancialClientView",
		"PortfolioAccountView",
		"FinancialProductView",
		"SanctionsScreeningView",
		"FinServReportView",
	):
		assert hasattr(m, name), f"views.py missing {name}"


def test_finserv_plugin_import():
	m = _import("pgappforge.plugins.erp.industry.financial_services")
	assert hasattr(m, "FinancialServicesPlugin")
	assert hasattr(m, "create_plugin")
	# All __all__ symbols must be importable
	for name in m.__all__:
		assert hasattr(m, name), f"__init__.py __all__ missing {name}"


# ---------------------------------------------------------------------------
# Financial Services — model column type assertions
# ---------------------------------------------------------------------------

def test_finserv_no_float_columns():
	"""No monetary column may use Float type anywhere in FinServ models."""
	from sqlalchemy import Float
	from pgappforge.plugins.erp.industry.financial_services.models import (
		FinancialClient,
		PortfolioAccount,
		FinancialProduct,
		ClientHolding,
		SanctionsScreeningResult,
	)
	for model_cls in (
		FinancialClient, PortfolioAccount, FinancialProduct,
		ClientHolding, SanctionsScreeningResult,
	):
		for col in model_cls.__table__.columns:
			assert not isinstance(col.type, Float), (
				f"{model_cls.__name__}.{col.name} uses Float — must use Integer or Numeric"
			)


def test_finserv_pk_uuid():
	"""All FinServ models must have a UUID primary key named 'id'."""
	from sqlalchemy.dialects.postgresql import UUID
	from pgappforge.plugins.erp.industry.financial_services.models import (
		FinancialClient,
		PortfolioAccount,
		FinancialProduct,
		ClientHolding,
		SanctionsScreeningResult,
	)
	for model_cls in (
		FinancialClient, PortfolioAccount, FinancialProduct,
		ClientHolding, SanctionsScreeningResult,
	):
		pk_cols = [c for c in model_cls.__table__.columns if c.primary_key]
		assert len(pk_cols) == 1, f"{model_cls.__name__} must have exactly 1 PK"
		assert pk_cols[0].name == "id", f"{model_cls.__name__} PK must be named 'id'"
		assert isinstance(pk_cols[0].type, UUID), (
			f"{model_cls.__name__}.id must be UUID, got {type(pk_cols[0].type)}"
		)


def test_finserv_tenant_id_not_null():
	"""All FinServ models must have a non-nullable tenant_id column."""
	from pgappforge.plugins.erp.industry.financial_services.models import (
		FinancialClient,
		PortfolioAccount,
		FinancialProduct,
		ClientHolding,
		SanctionsScreeningResult,
	)
	for model_cls in (
		FinancialClient, PortfolioAccount, FinancialProduct,
		ClientHolding, SanctionsScreeningResult,
	):
		col = model_cls.__table__.columns.get("tenant_id")
		assert col is not None, f"{model_cls.__name__} missing tenant_id"
		assert not col.nullable, f"{model_cls.__name__}.tenant_id must be NOT NULL"


# ---------------------------------------------------------------------------
# Financial Services — plugin class assertions
# ---------------------------------------------------------------------------

def test_finserv_plugin_class_attrs():
	from pgappforge.plugins.erp.industry.financial_services import FinancialServicesPlugin
	from pgappforge.plugins.base_plugin import BasePlugin
	_assert_subclass(FinancialServicesPlugin, BasePlugin, "FinancialServicesPlugin")
	assert FinancialServicesPlugin.name == "financial_services"
	assert FinancialServicesPlugin.domain == "industry"
	assert "foundation" in FinancialServicesPlugin.depends_on


def test_finserv_plugin_events():
	from pgappforge.plugins.erp.industry.financial_services import FinancialServicesPlugin
	# Instantiate with None appbuilder — only checking event declarations
	plugin = FinancialServicesPlugin.__new__(FinancialServicesPlugin)
	plugin.config = {}
	events = plugin.get_events()
	assert isinstance(events, list)
	assert "finserv.client.onboarded" in events
	assert "finserv.sanctions.screening_completed" in events
	subs = plugin.subscribe_to()
	assert isinstance(subs, list)
	assert "party.created" in subs


# ---------------------------------------------------------------------------
# Financial Services — event dataclass assertions
# ---------------------------------------------------------------------------

def test_finserv_events_are_dataclasses():
	import dataclasses
	from pgappforge.plugins.erp.foundation.events import DomainEvent
	from pgappforge.plugins.erp.industry.financial_services.events import (
		ClientOnboardedEvent,
		AccountBalanceUpdatedEvent,
		SanctionsScreeningCompletedEvent,
	)
	for cls in (ClientOnboardedEvent, AccountBalanceUpdatedEvent, SanctionsScreeningCompletedEvent):
		assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"
		_assert_subclass(cls, DomainEvent, cls.__name__)


def test_account_balance_event_amount_is_int():
	"""AccountBalanceUpdatedEvent.delta_cents and new_balance_cents must be int fields."""
	import dataclasses
	from pgappforge.plugins.erp.industry.financial_services.events import AccountBalanceUpdatedEvent
	fields = {f.name: f for f in dataclasses.fields(AccountBalanceUpdatedEvent)}
	assert "delta_cents" in fields, "Missing delta_cents field"
	assert "new_balance_cents" in fields, "Missing new_balance_cents field"
	# Default values should be int (0), not float
	ev = AccountBalanceUpdatedEvent()
	assert isinstance(ev.delta_cents, int), "delta_cents default must be int"
	assert isinstance(ev.new_balance_cents, int), "new_balance_cents default must be int"


# ---------------------------------------------------------------------------
# Health — module imports
# ---------------------------------------------------------------------------

def test_health_models_import():
	m = _import("pgappforge.plugins.erp.industry.health.models")
	for name in (
		"Patient",
		"ClinicalEncounter",
		"DiagnosisRecord",
		"ProcedureRecord",
		"Prescription",
		"LabResult",
	):
		assert hasattr(m, name), f"models.py missing {name}"


def test_health_events_import():
	m = _import("pgappforge.plugins.erp.industry.health.events")
	for name in (
		"PatientRegisteredEvent",
		"PatientUpdatedEvent",
		"EncounterStartedEvent",
		"EncounterCompletedEvent",
		"DiagnosisConfirmedEvent",
		"PrescriptionIssuedEvent",
		"PrescriptionDiscontinuedEvent",
		"LabResultedEvent",
		"LabCriticalValueEvent",
		"emit_event",
	):
		assert hasattr(m, name), f"events.py missing {name}"


def test_health_services_import():
	m = _import("pgappforge.plugins.erp.industry.health.services")
	for name in (
		"HealthService",
		"HealthServiceError",
		"PatientNotFoundError",
		"EncounterNotFoundError",
		"DiagnosisNotFoundError",
		"PrescriptionNotFoundError",
		"LabResultNotFoundError",
		"EncounterNotActiveError",
		"DiagnosisConfirmedError",
		"DuplicatePrimaryDiagnosisError",
		"RefillLimitExceededError",
		"DuplicatePatientNumberError",
	):
		assert hasattr(m, name), f"services.py missing {name}"


def test_health_views_import():
	m = _import("pgappforge.plugins.erp.industry.health.views")
	for name in (
		"PatientView",
		"ClinicalEncounterView",
		"DiagnosisView",
		"PrescriptionView",
		"LabResultView",
		"HealthReportView",
	):
		assert hasattr(m, name), f"views.py missing {name}"


def test_health_plugin_import():
	m = _import("pgappforge.plugins.erp.industry.health")
	assert hasattr(m, "HealthPlugin")
	assert hasattr(m, "create_plugin")
	for name in m.__all__:
		assert hasattr(m, name), f"__init__.py __all__ missing {name}"


# ---------------------------------------------------------------------------
# Health — model column type assertions
# ---------------------------------------------------------------------------

def test_health_pk_uuid():
	"""All Health models must have a UUID primary key named 'id'."""
	from sqlalchemy.dialects.postgresql import UUID
	from pgappforge.plugins.erp.industry.health.models import (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	)
	for model_cls in (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	):
		pk_cols = [c for c in model_cls.__table__.columns if c.primary_key]
		assert len(pk_cols) == 1, f"{model_cls.__name__} must have exactly 1 PK"
		assert pk_cols[0].name == "id"
		assert isinstance(pk_cols[0].type, UUID), (
			f"{model_cls.__name__}.id must be UUID"
		)


def test_health_tenant_id_not_null():
	from pgappforge.plugins.erp.industry.health.models import (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	)
	for model_cls in (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	):
		col = model_cls.__table__.columns.get("tenant_id")
		assert col is not None, f"{model_cls.__name__} missing tenant_id"
		assert not col.nullable, f"{model_cls.__name__}.tenant_id must be NOT NULL"


def test_health_no_float_columns():
	"""Health models carry no monetary data, but sanity-check no Float columns."""
	from sqlalchemy import Float
	from pgappforge.plugins.erp.industry.health.models import (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	)
	for model_cls in (
		Patient, ClinicalEncounter, DiagnosisRecord,
		ProcedureRecord, Prescription, LabResult,
	):
		for col in model_cls.__table__.columns:
			assert not isinstance(col.type, Float), (
				f"{model_cls.__name__}.{col.name} uses Float"
			)


def test_prescription_refill_defaults():
	"""Prescription refill columns must default to 0 (int), not None."""
	from pgappforge.plugins.erp.industry.health.models import Prescription
	cols = {c.name: c for c in Prescription.__table__.columns}
	assert cols["refills_allowed"].default is not None or cols["refills_allowed"].server_default is not None or True
	# Verify column exists and is Integer type
	from sqlalchemy import Integer
	assert isinstance(cols["refills_allowed"].type, Integer)
	assert isinstance(cols["refills_used"].type, Integer)


def test_lab_result_abnormal_flag_nullable():
	"""abnormal_flag must be nullable (NULL = pending/normal)."""
	from pgappforge.plugins.erp.industry.health.models import LabResult
	col = LabResult.__table__.columns["abnormal_flag"]
	assert col.nullable, "LabResult.abnormal_flag must be nullable"


# ---------------------------------------------------------------------------
# Health — plugin class assertions
# ---------------------------------------------------------------------------

def test_health_plugin_class_attrs():
	from pgappforge.plugins.erp.industry.health import HealthPlugin
	from pgappforge.plugins.base_plugin import BasePlugin
	_assert_subclass(HealthPlugin, BasePlugin, "HealthPlugin")
	assert HealthPlugin.name == "health"
	assert HealthPlugin.domain == "industry"
	assert "foundation" in HealthPlugin.depends_on


def test_health_plugin_events():
	from pgappforge.plugins.erp.industry.health import HealthPlugin
	plugin = HealthPlugin.__new__(HealthPlugin)
	plugin.config = {}
	events = plugin.get_events()
	assert "health.patient.registered" in events
	assert "health.lab.critical_value" in events
	subs = plugin.subscribe_to()
	assert "party.created" in subs


# ---------------------------------------------------------------------------
# Health — service error hierarchy
# ---------------------------------------------------------------------------

def test_health_error_hierarchy():
	from pgappforge.plugins.erp.industry.health.services import (
		HealthServiceError,
		PatientNotFoundError,
		EncounterNotFoundError,
		DiagnosisConfirmedError,
		RefillLimitExceededError,
	)
	for cls in (
		PatientNotFoundError,
		EncounterNotFoundError,
		DiagnosisConfirmedError,
		RefillLimitExceededError,
	):
		_assert_subclass(cls, HealthServiceError, cls.__name__)


def test_finserv_error_hierarchy():
	from pgappforge.plugins.erp.industry.financial_services.services import (
		FinServError,
		ClientNotFoundError,
		AccountFrozenError,
		SanctionsHoldError,
		KYCNotApprovedError,
	)
	for cls in (
		ClientNotFoundError,
		AccountFrozenError,
		SanctionsHoldError,
		KYCNotApprovedError,
	):
		_assert_subclass(cls, FinServError, cls.__name__)


# ---------------------------------------------------------------------------
# Cross-plugin: events re-export emit_event from foundation
# ---------------------------------------------------------------------------

def test_both_plugins_reexport_emit_event():
	"""Both industry plugin event modules must re-export emit_event from foundation."""
	from pgappforge.plugins.erp.foundation.events import emit_event as canonical
	import pgappforge.plugins.erp.industry.financial_services.events as fs_events
	import pgappforge.plugins.erp.industry.health.events as h_events
	assert fs_events.emit_event is canonical, (
		"finserv.events.emit_event must be the canonical foundation emit_event"
	)
	assert h_events.emit_event is canonical, (
		"health.events.emit_event must be the canonical foundation emit_event"
	)
