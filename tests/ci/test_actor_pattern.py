"""Tests for the Actor pattern — ActorConfig, ActorMixin, ActorRegistry."""

from __future__ import annotations

import pytest

from pgappforge.templates.core.actor import (
	ActorConfig,
	ActorDisplay,
	ActorFieldMap,
	ActorMixin,
	ActorRegistry,
	ActorSubRole,
)
from pgappforge.templates.registry import TemplateRegistry


# ─── Fixtures ─────────────────────────────────────────────────────────────

PATIENT_CONFIG = ActorConfig(
	role="patient",
	table="patient",
	display=ActorDisplay(singular="Patient", plural="Patients", icon="fa-user-md"),
	field_map=ActorFieldMap(
		display_name=["given_name", "family_name"],
		contact_email="email",
		contact_phone="phone",
		status_field="active",
		status_map={"true": "active", "false": "inactive"},
		external_ids={"mrn": "medical_record_number"},
	),
	related_collections=["encounter", "observation"],
	tags=["hipaa", "person"],
)

EMPLOYEE_CONFIG = ActorConfig(
	role="employee",
	table="hro_person_profile",
	display=ActorDisplay(singular="Employee", plural="Employees", icon="fa-id-badge"),
	field_map=ActorFieldMap(
		display_name=["given_name", "family_name"],
		status_field="status",
		status_map={"active": "active", "inactive": "inactive", "on-leave": "active"},
	),
)


@pytest.fixture(autouse=True)
def reset_registry():
	ActorRegistry.reset()
	yield
	ActorRegistry.reset()


# ─── ActorConfig validation ────────────────────────────────────────────────

def test_actor_config_valid():
	assert PATIENT_CONFIG.role == "patient"
	assert PATIENT_CONFIG.display.plural == "Patients"
	assert PATIENT_CONFIG.qualified_role == "patient"


def test_actor_config_schema_qualified_role():
	re_tenant = ActorConfig(
		role="tenant",
		table="tenants",
		schema_name="real-estate",
		display=ActorDisplay(singular="Tenant", plural="Tenants"),
		field_map=ActorFieldMap(display_name=["full_name"]),
	)
	saas_tenant = ActorConfig(
		role="tenant",
		table="organizations",
		schema_name="saas",
		display=ActorDisplay(singular="Organization", plural="Organizations"),
		field_map=ActorFieldMap(display_name=["name"]),
	)
	assert re_tenant.qualified_role == "real-estate/tenant"
	assert saas_tenant.qualified_role == "saas/tenant"
	assert re_tenant.qualified_role != saas_tenant.qualified_role


def test_actor_config_role_slug_validation():
	with pytest.raises(ValueError, match="lowercase slug"):
		ActorConfig(
			role="My Patient",
			table="patients",
			display=ActorDisplay(singular="Patient", plural="Patients"),
			field_map=ActorFieldMap(display_name="name"),
		)


# ─── ActorMixin property computation ──────────────────────────────────────

class FakePatient(ActorMixin):
	"""Minimal mock of a Patient model (no SQLAlchemy needed for unit tests)."""
	__actor_config__ = PATIENT_CONFIG

	def __init__(self, **kwargs):
		for k, v in kwargs.items():
			setattr(self, k, v)


def test_actor_display_name_joined():
	p = FakePatient(given_name="Jane", family_name="Smith")
	assert p.actor_display_name == "Jane Smith"


def test_actor_display_name_partial():
	p = FakePatient(given_name="Jane", family_name=None)
	assert p.actor_display_name == "Jane"


def test_actor_display_name_single_field():
	cfg = ActorConfig(
		role="customer",
		table="customers",
		display=ActorDisplay(singular="Customer", plural="Customers"),
		field_map=ActorFieldMap(display_name="full_name"),
	)

	class FakeCustomer(ActorMixin):
		__actor_config__ = cfg

		def __init__(self, **kw):
			for k, v in kw.items(): setattr(self, k, v)

	c = FakeCustomer(full_name="Acme Corp")
	assert c.actor_display_name == "Acme Corp"


def test_actor_contact_email():
	p = FakePatient(email="jane@example.com")
	assert p.actor_contact_email == "jane@example.com"


def test_actor_contact_email_missing_field():
	class FakeEmployee(ActorMixin):
		__actor_config__ = EMPLOYEE_CONFIG
		def __init__(self, **kw):
			for k, v in kw.items(): setattr(self, k, v)

	e = FakeEmployee(given_name="Bob", family_name="Lee")
	assert e.actor_contact_email is None


def test_actor_status_boolean_mapping():
	p = FakePatient(active=True)
	assert p.actor_status == "active"
	assert p.actor_is_active is True

	p2 = FakePatient(active=False)
	assert p2.actor_status == "inactive"
	assert p2.actor_is_active is False


def test_actor_status_string_mapping():
	class FakeEmployee(ActorMixin):
		__actor_config__ = EMPLOYEE_CONFIG
		def __init__(self, **kw):
			for k, v in kw.items(): setattr(self, k, v)

	assert FakeEmployee(status="active").actor_status == "active"
	assert FakeEmployee(status="on-leave").actor_status == "active"
	assert FakeEmployee(status="inactive").actor_status == "inactive"


def test_actor_status_no_field():
	cfg = ActorConfig(
		role="thing",
		table="things",
		display=ActorDisplay(singular="Thing", plural="Things"),
		field_map=ActorFieldMap(display_name="name"),
	)
	class FakeThing(ActorMixin):
		__actor_config__ = cfg
		name = "widget"
	assert FakeThing().actor_status == "unknown"
	assert FakeThing().actor_is_active is False


def test_actor_external_ids():
	p = FakePatient(medical_record_number="MRN-001")
	assert p.actor_external_ids == {"mrn": "MRN-001"}


def test_actor_external_ids_missing_value():
	p = FakePatient()  # no medical_record_number
	assert p.actor_external_ids == {}


def test_actor_to_dict():
	p = FakePatient(given_name="Jane", family_name="Smith",
	                email="jane@example.com", active=True,
	                medical_record_number="MRN-007")
	d = p.actor_to_dict()
	assert d["role"] == "patient"
	assert d["display_name"] == "Jane Smith"
	assert d["contact_email"] == "jane@example.com"
	assert d["status"] == "active"
	assert d["is_active"] is True
	assert d["external_ids"] == {"mrn": "MRN-007"}


# ─── ActorRegistry ─────────────────────────────────────────────────────────

def test_registry_singleton():
	r1 = ActorRegistry.instance()
	r2 = ActorRegistry.instance()
	assert r1 is r2


def test_registry_register_and_get():
	reg = ActorRegistry.instance()
	reg.register(PATIENT_CONFIG)
	cfg = reg.get("patient")
	assert cfg is not None
	assert cfg.role == "patient"


def test_registry_namespaced_roles():
	reg = ActorRegistry.instance()
	re_tenant = ActorConfig(
		role="tenant", table="tenants", schema_name="real-estate",
		display=ActorDisplay(singular="Tenant", plural="Tenants"),
		field_map=ActorFieldMap(display_name="full_name"),
	)
	saas_tenant = ActorConfig(
		role="tenant", table="organizations", schema_name="saas",
		display=ActorDisplay(singular="Organization", plural="Organizations"),
		field_map=ActorFieldMap(display_name="name"),
	)
	reg.register(re_tenant)
	reg.register(saas_tenant)
	assert reg.get("tenant", schema_name="real-estate").table == "tenants"
	assert reg.get("tenant", schema_name="saas").table == "organizations"
	assert reg.get("tenant") is None  # unqualified lookup — both require schema


def test_registry_auto_register_on_subclass():
	reg = ActorRegistry.instance()
	class AutoPatient(ActorMixin):
		__actor_config__ = PATIENT_CONFIG
		def __init__(self, **kw):
			for k, v in kw.items(): setattr(self, k, v)

	assert reg.is_registered("patient")
	assert reg.get_model_class("patient") is AutoPatient


def test_registry_all_roles():
	reg = ActorRegistry.instance()
	reg.register(PATIENT_CONFIG)
	reg.register(EMPLOYEE_CONFIG)
	roles = reg.all_roles()
	assert "patient" in roles
	assert "employee" in roles


def test_registry_is_registered():
	reg = ActorRegistry.instance()
	assert not reg.is_registered("patient")
	reg.register(PATIENT_CONFIG)
	assert reg.is_registered("patient")


# ─── TemplateRegistry integration ──────────────────────────────────────────

def test_template_registry_get_actor_config():
	reg = TemplateRegistry()
	cfg = reg.get_actor_config("fhir-r4")
	assert cfg is not None
	assert cfg.role == "patient"
	assert cfg.display.singular == "Patient"
	assert cfg.field_map.status_field == "active"
	assert "mrn" in cfg.field_map.external_ids


def test_template_registry_get_actor_config_none_when_absent():
	reg = TemplateRegistry()
	# A template without an actor section should return None
	# Use a template we know has no actor (e.g. activitypub)
	cfg = reg.get_actor_config("activitypub")
	assert cfg is None


def test_template_registry_all_actor_configs():
	reg = TemplateRegistry()
	configs = reg.all_actor_configs()
	assert "fhir-r4" in configs
	assert "hr-open" in configs
	for name, cfg in configs.items():
		assert cfg.role  # all actors have a non-empty role


def test_template_registry_register_actors():
	reg = TemplateRegistry()
	count = reg.register_actors()
	assert count >= 2  # at least fhir-r4 and hr-open
	actor_reg = ActorRegistry.instance()
	assert actor_reg.is_registered("patient")
	assert actor_reg.is_registered("employee")


# ─── Sub-role disambiguation ───────────────────────────────────────────────

PRACTITIONER_CONFIG = ActorConfig(
	role="practitioner",
	table="practitioner",
	primary=False,
	display=ActorDisplay(singular="Practitioner", plural="Practitioners", icon="fa-user-nurse"),
	field_map=ActorFieldMap(display_name=["given_name", "family_name"], status_field="active",
	                        status_map={"true": "active", "false": "inactive"}),
	sub_roles={
		"doctor":     ActorSubRole("qualification", ["MD", "DO"],  ActorDisplay("Doctor",     "Doctors",     "fa-user-md")),
		"nurse":      ActorSubRole("qualification", ["RN", "NP"],  ActorDisplay("Nurse",      "Nurses",      "fa-stethoscope")),
		"pharmacist": ActorSubRole("qualification", ["PharmD"],    ActorDisplay("Pharmacist", "Pharmacists", "fa-pills")),
	},
)


class FakePractitioner(ActorMixin):
	__actor_config__ = PRACTITIONER_CONFIG
	def __init__(self, **kw):
		for k, v in kw.items(): setattr(self, k, v)


def test_sub_role_detected_on_instance():
	assert FakePractitioner(qualification="MD").actor_sub_role == "doctor"
	assert FakePractitioner(qualification="DO").actor_sub_role == "doctor"
	assert FakePractitioner(qualification="RN").actor_sub_role == "nurse"
	assert FakePractitioner(qualification="PharmD").actor_sub_role == "pharmacist"
	assert FakePractitioner(qualification="PT").actor_sub_role is None


def test_sub_role_display():
	reg = ActorRegistry.instance()
	reg.register(PRACTITIONER_CONFIG)  # explicit — autouse reset clears class-level auto-reg
	result = reg.get_sub_role("doctor")
	assert result is not None
	actor_cfg, sub = result
	assert actor_cfg.role == "practitioner"
	assert sub.display.singular == "Doctor"
	assert "MD" in sub.filter_values


def test_sub_role_unknown_returns_none():
	reg = ActorRegistry.instance()
	assert reg.get_sub_role("veterinarian") is None


def test_actor_config_from_dict_with_sub_roles():
	data = {
		"role": "practitioner",
		"table": "practitioner",
		"primary": False,
		"display": {"singular": "Practitioner", "plural": "Practitioners"},
		"field_map": {"display_name": ["given_name", "family_name"]},
		"sub_roles": {
			"doctor": {
				"filter_field": "qualification",
				"filter_values": ["MD", "DO"],
				"display": {"singular": "Doctor", "plural": "Doctors"},
			}
		},
	}
	cfg = ActorConfig.from_dict(data)
	assert cfg.role == "practitioner"
	assert "doctor" in cfg.sub_roles
	assert cfg.sub_roles["doctor"].filter_values == ["MD", "DO"]
	assert not cfg.primary


def test_actor_to_dict_includes_sub_role():
	p = FakePractitioner(given_name="Jane", family_name="Smith",
	                     active=True, qualification="RN")
	d = p.actor_to_dict()
	assert d["role"] == "practitioner"
	assert d["sub_role"] == "nurse"
	assert d["display_name"] == "Jane Smith"
	assert d["is_active"] is True
