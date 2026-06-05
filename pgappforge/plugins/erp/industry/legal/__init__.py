"""
pgappforge/plugins/erp/industry/legal/__init__.py

LegalPlugin — Legal Services ERP plugin.

Provides:
  - LegalMatter    (matter_type: LITIGATION/TRANSACTION/ADVISORY/COMPLIANCE/IP)
  - LegalDocument  (CONTRACT/PLEADING/BRIEF/ORDER/JUDGMENT/MEMO; versioned)
  - LegalTimeEntry      (UTBMS activity codes; billable time tracking)
  - Deadline       (STATUTE_OF_LIMITATIONS/FILING/HEARING/DISCOVERY_CLOSE)
  - LegalInvoice   (generated from approved time entries)
  - Precedent      (case law; jurisdiction + legal_issues[] search)

Business rules enforced:
  - matter_number unique per tenant
  - invoice_number unique per tenant
  - LegalTimeEntry.amount_cents = round_half_up(hours × rate_cents_per_hour)
  - Invoice total = time_charges + disbursements + tax (all integer cents)
  - Precedent search uses PostgreSQL array overlap (&&) on legal_issues

Events emitted:
  legal.matter.opened
  legal.matter.status_changed
  legal.matter.closed
  legal.document.created
  legal.document.executed
  legal.time_entry.recorded
  legal.invoice.generated
  legal.invoice.paid
  legal.deadline.tracked
  legal.deadline.missed

Events consumed:
  party.created  (optionally create matter shell for new client parties)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.legal",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class LegalPlugin(BasePlugin):
	"""Legal Services ERP plugin.

	Class-level routing metadata:
	    name       = "legal"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "legal"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="legal",
			version="1.0.0",
			description=(
				"Legal Services — matter management, billable time tracking, "
				"UTBMS activity codes, legal document versioning, deadline calendar "
				"(statute of limitations, filing, hearing, discovery close), "
				"invoice generation from approved time entries, and case law "
				"precedent search via PostgreSQL array overlap."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "legal", "law", "billing", "matter-management"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_legal_matter_read",
				"can_legal_matter_write",
				"can_legal_matter_close",
				"can_legal_document_read",
				"can_legal_document_write",
				"can_legal_document_execute",
				"can_legal_time_read",
				"can_legal_time_write",
				"can_legal_time_approve",
				"can_legal_deadline_read",
				"can_legal_deadline_write",
				"can_legal_invoice_read",
				"can_legal_invoice_write",
				"can_legal_invoice_send",
				"can_legal_precedent_read",
				"can_legal_precedent_write",
				"can_legal_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"legal.matter.opened",
			"legal.matter.status_changed",
			"legal.matter.closed",
			"legal.document.created",
			"legal.document.executed",
			"legal.time_entry.recorded",
			"legal.invoice.generated",
			"legal.invoice.paid",
			"legal.deadline.tracked",
			"legal.deadline.missed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"party.created",  # Optionally pre-register client shell on party creation
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"LEGAL_MENU_CATEGORY": "Legal Services",
			"LEGAL_SEED_RULES_ON_INIT": True,
			"LEGAL_DEFAULT_CURRENCY": "USD",
			"LEGAL_DEADLINE_WARN_DAYS": 14,
		}
		self.config = {**defaults, **self.config}
		log.info("LegalPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("LEGAL_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Legal views under the configured menu category."""
		from pgappforge.plugins.erp.industry.legal.views import (
			MatterView,
			DocumentView,
			TimeEntryView,
			DeadlineCalendarView,
			LegalInvoiceView,
			LegalReportView,
		)

		cat = self.config.get("LEGAL_MENU_CATEGORY", "Legal Services")

		self.add_view(MatterView, "Matters", icon="fa-briefcase", category=cat)
		self.add_view(DocumentView, "Documents", icon="fa-file-text-o", category=cat)
		self.add_view(TimeEntryView, "Time Entries", icon="fa-clock-o", category=cat)
		self.add_view(
			DeadlineCalendarView, "Deadlines", icon="fa-calendar-o", category=cat
		)
		self.add_view(LegalInvoiceView, "Invoices", icon="fa-usd", category=cat)
		self.add_view(
			LegalReportView, "Legal Reports", icon="fa-bar-chart", category=cat
		)

		log.info("LegalPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.legal.models import (
			LegalMatter,
			LegalDocument,
			LegalTimeEntry,
			Deadline,
			LegalInvoice,
			Precedent,
		)
		return [LegalMatter, LegalDocument, LegalTimeEntry, Deadline, LegalInvoice, Precedent]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Legal Services domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("LegalPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "legal.time_entry.no_billed_edit",
				"description": "Block editing a BILLED time entry",
				"model_name": "LegalTimeEntry",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_billed_entry_edit",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "BILLED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"LegalTimeEntry is BILLED — it cannot be modified. "
									"Create a correction entry instead."
								),
							}
						],
					},
				],
			},
			{
				"name": "legal.deadline.hard_deadline_warn",
				"description": "Log warning when a hard deadline is set within 7 days",
				"model_name": "Deadline",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_imminent_hard_deadline",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "is_hard_deadline", "op": "eq", "value": True},
							{"field": "days_until_deadline", "op": "lte", "value": 7},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"Hard deadline {{deadline_type}} for matter {{matter_id}} "
									"is within 7 days ({{deadline_date}})"
								),
							}
						],
					},
				],
			},
			{
				"name": "legal.invoice.no_negative_total",
				"description": "Block invoice with negative total_cents",
				"model_name": "LegalInvoice",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_negative_total",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "total_cents", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "LegalInvoice total_cents cannot be negative.",
							}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("LegalPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("LegalPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> LegalPlugin:
	return LegalPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.legal.models import (  # noqa: E402
	LegalMatter,
	LegalDocument,
	LegalTimeEntry,
	Deadline,
	LegalInvoice,
	Precedent,
)
from pgappforge.plugins.erp.industry.legal.events import (  # noqa: E402
	emit_event,
	MatterOpenedEvent,
	MatterStatusChangedEvent,
	MatterClosedEvent,
	DocumentCreatedEvent,
	DocumentExecutedEvent,
	TimeEntryRecordedEvent,
	InvoiceGeneratedEvent,
	InvoicePaidEvent,
	DeadlineTrackedEvent,
	DeadlineMissedEvent,
)
from pgappforge.plugins.erp.industry.legal.services import (  # noqa: E402
	LegalService,
	LegalServiceError,
	MatterNotFoundError,
	DocumentNotFoundError,
	TimeEntryNotFoundError,
	DeadlineNotFoundError,
	InvoiceNotFoundError,
	DuplicateMatterNumberError,
	DuplicateInvoiceNumberError,
	MatterNotActiveError,
)

__all__ = [
	# plugin
	"LegalPlugin",
	"create_plugin",
	# models
	"LegalMatter",
	"LegalDocument",
	"LegalTimeEntry",
	"Deadline",
	"LegalInvoice",
	"Precedent",
	# events
	"emit_event",
	"MatterOpenedEvent",
	"MatterStatusChangedEvent",
	"MatterClosedEvent",
	"DocumentCreatedEvent",
	"DocumentExecutedEvent",
	"TimeEntryRecordedEvent",
	"InvoiceGeneratedEvent",
	"InvoicePaidEvent",
	"DeadlineTrackedEvent",
	"DeadlineMissedEvent",
	# services
	"LegalService",
	"LegalServiceError",
	"MatterNotFoundError",
	"DocumentNotFoundError",
	"TimeEntryNotFoundError",
	"DeadlineNotFoundError",
	"InvoiceNotFoundError",
	"DuplicateMatterNumberError",
	"DuplicateInvoiceNumberError",
	"MatterNotActiveError",
]
