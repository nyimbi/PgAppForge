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
	# icd10 is a code classification — no person actor
	cfg = reg.get_actor_config("icd10")
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
	assert count >= 3  # patient + practitioner (fhir-r4) + employee (hr-open)
	actor_reg = ActorRegistry.instance()
	assert actor_reg.is_registered("patient")
	assert actor_reg.is_registered("employee")
	assert actor_reg.is_registered("practitioner")


def test_template_registry_get_template_actors():
	reg = TemplateRegistry()
	actors = reg.get_template_actors("fhir-r4")
	assert len(actors) == 2
	roles = {a.role for a in actors}
	assert "patient" in roles
	assert "practitioner" in roles
	primary = next(a for a in actors if a.primary)
	assert primary.role == "patient"
	supporting = next(a for a in actors if not a.primary)
	assert supporting.role == "practitioner"
	assert "doctor" in supporting.sub_roles


def test_template_registry_get_actor_config_returns_primary():
	reg = TemplateRegistry()
	cfg = reg.get_actor_config("fhir-r4")
	assert cfg.role == "patient"  # primary, not practitioner
	assert cfg.primary is True


def test_hr_open_single_actor_format():
	reg = TemplateRegistry()
	actors = reg.get_template_actors("hr-open")
	assert len(actors) == 1
	assert actors[0].role == "employee"


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


# ─── search_all() integration test ────────────────────────────────────────
# Uses the pgaf_test PostgreSQL database — skipped if unavailable.

import os

SEARCH_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
SKIP_DB = pytest.mark.skipif(
    not SEARCH_URI.startswith("postgresql"),
    reason="requires PostgreSQL",
)

@SKIP_DB
def test_search_all_integration():
	"""search_all() returns matching actors from a real SQLAlchemy session."""
	import sqlalchemy as sa
	from sqlalchemy.orm import Session, DeclarativeBase

	class _Base(DeclarativeBase):
		pass

	SEARCH_CONFIG = ActorConfig(
		role="search-test-person",
		table="ci_actor_search_test",
		display=ActorDisplay(singular="Person", plural="Persons"),
		field_map=ActorFieldMap(
			display_name=["given_name", "family_name"],
			contact_email="email",
			status_field="active",
			status_map={"true": "active", "false": "inactive"},
		),
	)

	class CiActorSearchTest(ActorMixin, _Base):
		__tablename__ = "ci_actor_search_test"
		__actor_config__ = SEARCH_CONFIG
		id         = sa.Column(sa.Integer, sa.Sequence("ci_actor_search_id_seq"), primary_key=True)
		given_name  = sa.Column(sa.String(100))
		family_name = sa.Column(sa.String(100))
		email       = sa.Column(sa.String(255))
		active      = sa.Column(sa.Boolean, default=True)

	engine = sa.create_engine(SEARCH_URI)
	_Base.metadata.drop_all(engine)   # clean slate
	_Base.metadata.create_all(engine)

	try:
		with Session(engine) as session:
			session.add_all([
				CiActorSearchTest(given_name="Jane",  family_name="Smith",  email="jane@example.com",  active=True),
				CiActorSearchTest(given_name="John",  family_name="Smith",  email="john@example.com",  active=True),
				CiActorSearchTest(given_name="Alice", family_name="Jones",  email="alice@example.com", active=False),
			])
			session.commit()

			reg = ActorRegistry.instance()
			# CiActorSearchTest auto-registered via __init_subclass__

			# Search by family name
			results = reg.search_all("Smith", session, limit_per_actor=10)
			smith_names = {r.display_name for r in results if r.role == "search-test-person"}
			assert "Jane Smith" in smith_names
			assert "John Smith" in smith_names
			assert "Alice Jones" not in smith_names

			# Search by email fragment
			results2 = reg.search_all("alice@", session, limit_per_actor=10)
			found = [r for r in results2 if r.role == "search-test-person"]
			assert len(found) == 1
			assert found[0].display_name == "Alice Jones"
			assert found[0].status == "inactive"
			assert found[0].contact_email == "alice@example.com"

			# No match returns empty
			results3 = reg.search_all("zzznomatch", session, limit_per_actor=10)
			actor_results = [r for r in results3 if r.role == "search-test-person"]
			assert len(actor_results) == 0
	finally:
		_Base.metadata.drop_all(engine)


@SKIP_DB
def test_actor_schema_state_set_actor():
	"""SchemaState.set_actor() marks a table as primary actor and emits correct snippet."""
	from pgappforge.cli.app_creator_chat import SchemaState
	s = SchemaState()
	s.create_table("patient", [
		{"name": "given_name", "type": "varchar(100)"},
		{"name": "family_name", "type": "varchar(100)"},
		{"name": "email", "type": "varchar(255)"},
		{"name": "active", "type": "boolean"},
	])
	result = s.set_actor("patient", "Patient", "Patients", "patient")
	assert "Patient" in result
	assert s.primary_actor == "patient"
	assert s.actor_display_singular == "Patient"
	assert s.actor_role == "patient"

	snippet = s._actor_mixin_snippet()
	assert "ActorMixin" in snippet
	assert "ActorConfig" in snippet
	assert 'role="patient"' in snippet
	assert 'given_name' in snippet   # auto-detected display_name
	assert 'contact_email="email"' in snippet
	assert 'status_field="active"' in snippet

