"""
Actor pattern for pgappforge templates.

The "Actor" is the primary subject of a domain — the entity everything else
relates to. It appears under many names across templates:

  Healthcare  → Patient (or Practitioner, Nurse — see ActorConfig.sub_roles)
  HR          → Employee (or Manager, Contractor)
  Finance     → Client / Account
  E-commerce  → Customer (or Salesperson, Manager)
  SaaS        → Organization / Subscriber
  Real Estate → Tenant  (distinct from SaaS Tenant — use schema_name)
  CRM         → Contact / Lead

Key design rules:
  - Auth User is NEVER an Actor. Actors optionally FK to users for login.
  - "Tenant" in SaaS ≠ "Tenant" in Real Estate. Disambiguate with schema_name.
  - One primary actor per template; additional actors listed in supporting[].
  - Sub-roles (doctor/nurse within practitioner) are filtered views, not
    separate tables — declared with ActorSubRole.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
	from sqlalchemy.orm import Session


# ─── Value objects ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActorDisplay:
	"""Human-readable labels and visual identity for an actor type."""

	singular: str
	plural: str
	icon: str = "fa-user"
	color: str = "primary"


@dataclass(frozen=True)
class ActorFieldMap:
	"""Maps canonical Actor properties to the domain model's actual field names.

	``status_map`` keys must be strings — boolean fields use ``"true"``/``"false"``::

	    ActorFieldMap(
	        display_name=["given_name", "family_name"],
	        status_field="active",
	        status_map={"true": "active", "false": "inactive"},
	    )

	String status fields::

	    ActorFieldMap(
	        display_name="full_name",
	        status_field="status",
	        status_map={"active": "active", "discharged": "inactive", "on-leave": "active"},
	    )
	"""

	display_name: str | list[str]
	contact_email: str | None = None
	contact_phone: str | None = None
	status_field: str | None = None
	status_map: dict[str, str] | None = None
	external_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActorSubRole:
	"""A filtered view of an actor table for a specialised role.

	Example — doctors and nurses both live in the ``practitioner`` table
	and are distinguished by a ``qualification`` column::

	    sub_roles={
	        "doctor":     ActorSubRole("qualification", ["MD", "DO"], ActorDisplay("Doctor",     "Doctors",    "fa-user-md")),
	        "nurse":      ActorSubRole("qualification", ["RN", "NP"], ActorDisplay("Nurse",      "Nurses",     "fa-stethoscope")),
	        "pharmacist": ActorSubRole("qualification", ["PharmD"],   ActorDisplay("Pharmacist", "Pharmacists","fa-pills")),
	    }
	"""

	filter_field: str
	filter_values: list[str]
	display: ActorDisplay


@dataclass
class ActorConfig:
	"""Full actor declaration — stored under the 'actors' key in a template JSON.

	JSON example (primary actor)::

	    {
	        "role": "patient",
	        "table": "patient",
	        "primary": true,
	        "display": {"singular": "Patient", "plural": "Patients", "icon": "fa-user-md"},
	        "field_map": {
	            "display_name": ["given_name", "family_name"],
	            "contact_email": "email",
	            "status_field": "active",
	            "status_map": {"true": "active", "false": "inactive"},
	            "external_ids": {"mrn": "identifier"}
	        },
	        "related_collections": ["encounter", "observation"],
	        "tags": ["hipaa", "person", "billable"]
	    }

	JSON example (supporting actor with sub-roles)::

	    {
	        "role": "practitioner",
	        "table": "practitioner",
	        "primary": false,
	        "display": {"singular": "Practitioner", "plural": "Practitioners", "icon": "fa-user-nurse"},
	        "field_map": {"display_name": ["given_name", "family_name"]},
	        "sub_roles": {
	            "doctor":     {"filter_field": "qualification", "filter_values": ["MD", "DO"],    "display": {"singular": "Doctor",     "plural": "Doctors",     "icon": "fa-user-md"}},
	            "nurse":      {"filter_field": "qualification", "filter_values": ["RN", "NP"],    "display": {"singular": "Nurse",      "plural": "Nurses",      "icon": "fa-stethoscope"}},
	            "pharmacist": {"filter_field": "qualification", "filter_values": ["PharmD"],      "display": {"singular": "Pharmacist", "plural": "Pharmacists", "icon": "fa-pills"}}
	        }
	    }
	"""

	role: str
	table: str
	display: ActorDisplay
	field_map: ActorFieldMap
	primary: bool = True
	schema_name: str | None = None
	related_collections: list[str] = field(default_factory=list)
	tags: list[str] = field(default_factory=list)
	sub_roles: dict[str, ActorSubRole] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if not re.match(r"^[a-z][a-z0-9-]*$", self.role):
			raise ValueError(
				f"ActorConfig.role must be a lowercase slug (e.g. 'patient'), got: {self.role!r}"
			)
		if not self.table.strip():
			raise ValueError("ActorConfig.table must not be empty")

	@property
	def qualified_role(self) -> str:
		"""Unique key including schema namespace: 'real-estate/tenant' or 'patient'."""
		return f"{self.schema_name}/{self.role}" if self.schema_name else self.role

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> ActorConfig:
		"""Deserialise from a template JSON actor object."""
		display_raw = data.get("display", {})
		display = ActorDisplay(
			singular=display_raw["singular"],
			plural=display_raw["plural"],
			icon=display_raw.get("icon", "fa-user"),
			color=display_raw.get("color", "primary"),
		)
		fm_raw = data.get("field_map", {})
		field_map = ActorFieldMap(
			display_name=fm_raw["display_name"],
			contact_email=fm_raw.get("contact_email"),
			contact_phone=fm_raw.get("contact_phone"),
			status_field=fm_raw.get("status_field"),
			status_map=fm_raw.get("status_map"),
			external_ids=fm_raw.get("external_ids", {}),
		)
		sub_roles: dict[str, ActorSubRole] = {}
		for sr_key, sr_raw in data.get("sub_roles", {}).items():
			if not re.match(r"^[a-z][a-z0-9-]*$", sr_key):
				raise ValueError(f"sub_role key must be a slug, got: {sr_key!r}")
			sr_display_raw = sr_raw.get("display", {})
			sub_roles[sr_key] = ActorSubRole(
				filter_field=sr_raw["filter_field"],
				filter_values=list(sr_raw["filter_values"]),
				display=ActorDisplay(
					singular=sr_display_raw.get("singular", sr_key.title()),
					plural=sr_display_raw.get("plural", sr_key.title() + "s"),
					icon=sr_display_raw.get("icon", "fa-user"),
					color=sr_display_raw.get("color", "secondary"),
				),
			)
		return cls(
			role=data["role"],
			table=data["table"],
			display=display,
			field_map=field_map,
			primary=data.get("primary", True),
			schema_name=data.get("schema_name"),
			related_collections=list(data.get("related_collections", [])),
			tags=list(data.get("tags", [])),
			sub_roles=sub_roles,
		)


# ─── SQLAlchemy mixin ──────────────────────────────────────────────────────

class ActorMixin:
	"""SQLAlchemy mixin for models that represent an actor in a domain.

	Declare ``__actor_config__`` on your model class and this mixin
	automatically registers with ActorRegistry and exposes canonical
	``actor_*`` properties regardless of what the domain calls its fields.

	Usage::

	    class Patient(ActorMixin, Base):
	        __tablename__ = "patient"
	        __actor_config__ = ActorConfig(
	            role="patient",
	            table="patient",
	            display=ActorDisplay(singular="Patient", plural="Patients"),
	            field_map=ActorFieldMap(
	                display_name=["given_name", "family_name"],
	                contact_email="email",
	                status_field="active",
	                status_map={"true": "active", "false": "inactive"},
	            ),
	        )
	"""

	__actor_config__: ClassVar[ActorConfig]

	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)
		if "__actor_config__" in cls.__dict__:
			ActorRegistry.instance().register(cls.__actor_config__, model_class=cls)

	@property
	def actor_display_name(self) -> str:
		fm = self.__actor_config__.field_map
		if isinstance(fm.display_name, list):
			parts = [str(getattr(self, f, "") or "") for f in fm.display_name]
			return " ".join(p for p in parts if p)
		return str(getattr(self, fm.display_name, "") or "")

	@property
	def actor_contact_email(self) -> str | None:
		fm = self.__actor_config__.field_map
		return getattr(self, fm.contact_email, None) if fm.contact_email else None

	@property
	def actor_contact_phone(self) -> str | None:
		fm = self.__actor_config__.field_map
		return getattr(self, fm.contact_phone, None) if fm.contact_phone else None

	@property
	def actor_status(self) -> str:
		fm = self.__actor_config__.field_map
		if not fm.status_field:
			return "unknown"
		raw = getattr(self, fm.status_field, None)
		if raw is None:
			return "unknown"
		key = str(raw).lower()
		if fm.status_map:
			return fm.status_map.get(key, fm.status_map.get(str(raw), key))
		return key

	@property
	def actor_is_active(self) -> bool:
		return self.actor_status == "active"

	@property
	def actor_external_ids(self) -> dict[str, str]:
		fm = self.__actor_config__.field_map
		return {
			id_type: str(getattr(self, field_name, "") or "")
			for id_type, field_name in fm.external_ids.items()
			if getattr(self, field_name, None) is not None
		}

	@property
	def actor_role(self) -> str:
		return self.__actor_config__.role

	@property
	def actor_sub_role(self) -> str | None:
		"""Return the matching sub-role for this instance, or None."""
		for sub_key, sub in self.__actor_config__.sub_roles.items():
			raw = str(getattr(self, sub.filter_field, "") or "")
			if raw in sub.filter_values:
				return sub_key
		return None

	def actor_to_dict(self) -> dict[str, Any]:
		return {
			"role": self.actor_role,
			"sub_role": self.actor_sub_role,
			"display_name": self.actor_display_name,
			"contact_email": self.actor_contact_email,
			"contact_phone": self.actor_contact_phone,
			"status": self.actor_status,
			"is_active": self.actor_is_active,
			"external_ids": self.actor_external_ids,
		}


# ─── Registry ──────────────────────────────────────────────────────────────

@dataclass
class _ActorRegistration:
	config: ActorConfig
	model_class: type | None = None


@dataclass
class ActorSearchResult:
	role: str
	sub_role: str | None
	display_name: str
	contact_email: str | None
	status: str
	external_ids: dict[str, str]
	instance: Any


class ActorRegistry:
	"""Thread-safe singleton mapping qualified_role → ActorConfig + model class.

	Keys are qualified roles: ``"patient"``, ``"real-estate/tenant"``, ``"saas/tenant"``.
	"""

	_lock: ClassVar[threading.Lock] = threading.Lock()
	_instance: ClassVar[ActorRegistry | None] = None

	def __init__(self) -> None:
		self._regs: dict[str, _ActorRegistration] = {}

	@classmethod
	def instance(cls) -> ActorRegistry:
		if cls._instance is None:
			with cls._lock:
				if cls._instance is None:
					cls._instance = cls()
		return cls._instance

	@classmethod
	def reset(cls) -> None:
		"""Reset the singleton — for tests only."""
		with cls._lock:
			cls._instance = None

	def register(self, config: ActorConfig, model_class: type | None = None) -> None:
		with self._lock:
			self._regs[config.qualified_role] = _ActorRegistration(config, model_class)

	def get(self, role: str, schema_name: str | None = None) -> ActorConfig | None:
		key = f"{schema_name}/{role}" if schema_name else role
		reg = self._regs.get(key)
		return reg.config if reg else None

	def get_model_class(self, role: str, schema_name: str | None = None) -> type | None:
		key = f"{schema_name}/{role}" if schema_name else role
		reg = self._regs.get(key)
		return reg.model_class if reg else None

	def get_sub_role(self, sub_role: str, schema_name: str | None = None) -> tuple[ActorConfig, ActorSubRole] | None:
		"""Find which actor config contains a given sub-role key, and return both."""
		for reg in self._regs.values():
			if schema_name and reg.config.schema_name != schema_name:
				continue
			if sub_role in reg.config.sub_roles:
				return reg.config, reg.config.sub_roles[sub_role]
		return None

	def all_roles(self) -> list[str]:
		return list(self._regs)

	def all_configs(self) -> list[ActorConfig]:
		return [r.config for r in self._regs.values()]

	def primary_configs(self) -> list[ActorConfig]:
		"""Return only primary actors (one per template)."""
		return [r.config for r in self._regs.values() if r.config.primary]

	def is_registered(self, role: str, schema_name: str | None = None) -> bool:
		key = f"{schema_name}/{role}" if schema_name else role
		return key in self._regs

	def search_all(
		self,
		query: str,
		session: Session,
		limit_per_actor: int = 5,
	) -> list[ActorSearchResult]:
		"""Full-text search across all registered actor types with a model class."""
		from sqlalchemy import or_, cast, String, select

		results: list[ActorSearchResult] = []
		for reg in self._regs.values():
			if reg.model_class is None:
				continue
			fm = reg.config.field_map
			fields: list[str] = (
				list(fm.display_name) if isinstance(fm.display_name, list)
				else [fm.display_name]
			)
			if fm.contact_email:
				fields = [*fields, fm.contact_email]
			filters = [
				cast(getattr(reg.model_class, f), String).ilike(f"%{query}%")
				for f in fields
				if hasattr(reg.model_class, f)
			]
			if not filters:
				continue
			rows = session.execute(
				select(reg.model_class).where(or_(*filters)).limit(limit_per_actor)
			).scalars().all()
			for obj in rows:
				results.append(ActorSearchResult(
					role=reg.config.role,
					sub_role=getattr(obj, "actor_sub_role", None),
					display_name=obj.actor_display_name,
					contact_email=obj.actor_contact_email,
					status=obj.actor_status,
					external_ids=obj.actor_external_ids,
					instance=obj,
				))
		return results
