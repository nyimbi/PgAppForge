"""
pgappforge/plugins/fintech/regulatory/events.py

Regulatory Compliance domain events.

Event catalogue
---------------
  reg.aml.alert_generated       — new AML alert raised by rule engine
  reg.aml.alert_escalated       — alert escalated by analyst
  reg.aml.alert_closed          — alert closed (false positive, SAR filed, no action)
  reg.sar.filed                 — SAR filed with FRC Kenya
  reg.sar.acknowledged          — regulator acknowledged SAR
  reg.capital.report_generated  — capital adequacy report computed
  reg.capital.breached          — one or more CBK minimum ratios breached
  reg.ifrs9.run_completed       — IFRS 9 ECL provision run completed
  reg.pep.match_found           — customer matched against PEP list
  reg.pep.entry_added           — new PEP list entry added
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# AML events
# ---------------------------------------------------------------------------

@dataclass
class AMLAlertGeneratedEvent(DomainEvent):
	"""Emitted when the rule engine generates a new AML alert."""
	event_type: str = "reg.aml.alert_generated"
	alert_id: str = ""
	alert_number: str = ""
	rule_id: str = ""
	rule_code: str = ""
	customer_id: str = ""
	account_id: str = ""
	risk_score: int = 0
	triggering_transaction_count: int = 0


@dataclass
class AMLAlertEscalatedEvent(DomainEvent):
	"""Emitted when an analyst escalates an AML alert."""
	event_type: str = "reg.aml.alert_escalated"
	alert_id: str = ""
	alert_number: str = ""
	escalated_by: str = ""
	previous_status: str = ""
	due_by: str = ""  # ISO datetime string


@dataclass
class AMLAlertClosedEvent(DomainEvent):
	"""Emitted when an AML alert is closed."""
	event_type: str = "reg.aml.alert_closed"
	alert_id: str = ""
	alert_number: str = ""
	closed_by: str = ""
	resolution: str = ""  # CLOSED_FALSE_POSITIVE | CLOSED_SAR_FILED | CLOSED_NO_ACTION


# ---------------------------------------------------------------------------
# SAR events
# ---------------------------------------------------------------------------

@dataclass
class SARFiledEvent(DomainEvent):
	"""Emitted when a SAR is filed with FRC Kenya."""
	event_type: str = "reg.sar.filed"
	sar_id: str = ""
	sar_number: str = ""
	alert_id: str = ""
	subject_id: str = ""
	total_amount_cents: int = 0
	currency_code: str = "KES"
	filed_by: str = ""
	filed_at: str = ""  # ISO datetime string
	regulator: str = "FRC_KENYA"


@dataclass
class SARAcknowledgedEvent(DomainEvent):
	"""Emitted when the regulator acknowledges a SAR."""
	event_type: str = "reg.sar.acknowledged"
	sar_id: str = ""
	sar_number: str = ""
	regulator_reference: str = ""
	acknowledged_at: str = ""  # ISO datetime string


# ---------------------------------------------------------------------------
# Capital adequacy events
# ---------------------------------------------------------------------------

@dataclass
class CapitalReportGeneratedEvent(DomainEvent):
	"""Emitted when a capital adequacy report is computed."""
	event_type: str = "reg.capital.report_generated"
	report_id: str = ""
	report_date: str = ""  # ISO date string
	reporting_period: str = ""
	cet1_ratio_pct: str = ""   # Decimal serialised as string
	tier1_ratio_pct: str = ""
	total_capital_ratio_pct: str = ""
	leverage_ratio_pct: str = ""
	meets_minimum: bool = True


@dataclass
class CapitalBreachedEvent(DomainEvent):
	"""Emitted when one or more CBK minimum capital ratios are breached."""
	event_type: str = "reg.capital.breached"
	report_id: str = ""
	report_date: str = ""
	breached_ratios: list = field(default_factory=list)
	# e.g. [{"ratio": "CET1", "actual": "6.5", "minimum": "7.0"}]
	severity: str = ""  # WARNING | CRITICAL


# ---------------------------------------------------------------------------
# IFRS 9 events
# ---------------------------------------------------------------------------

@dataclass
class IFRS9RunCompletedEvent(DomainEvent):
	"""Emitted when an IFRS 9 ECL provision run completes."""
	event_type: str = "reg.ifrs9.run_completed"
	run_id: str = ""
	run_date: str = ""  # ISO date string
	run_type: str = ""
	total_ecl_cents: int = 0
	provision_movement_cents: int = 0
	stage1_ecl_cents: int = 0
	stage2_ecl_cents: int = 0
	stage3_ecl_cents: int = 0


# ---------------------------------------------------------------------------
# PEP events
# ---------------------------------------------------------------------------

@dataclass
class PEPMatchFoundEvent(DomainEvent):
	"""Emitted when a customer matches a PEP list entry."""
	event_type: str = "reg.pep.match_found"
	party_id: str = ""
	pep_entry_id: str = ""
	pep_type: str = ""
	match_source: str = ""
	risk_score: int = 0


@dataclass
class PEPEntryAddedEvent(DomainEvent):
	"""Emitted when a new PEP list entry is added."""
	event_type: str = "reg.pep.entry_added"
	pep_entry_id: str = ""
	party_id: str = ""
	pep_type: str = ""
	source: str = ""
	country_code: str = ""


# ---------------------------------------------------------------------------
# Sanctions events  [CRITICAL]
# ---------------------------------------------------------------------------

@dataclass
class SanctionsHitEvent(DomainEvent):
	"""Emitted when a transaction or customer matches a sanctions list entry."""
	event_type: str = "reg.sanctions.hit"
	entity_name: str = ""
	matched_entry_id: str = ""
	matched_name: str = ""
	list_source: str = ""
	similarity_score: float = 0.0
	transaction_id: str = ""
	customer_id: str = ""


@dataclass
class SanctionsListUpdatedEvent(DomainEvent):
	"""Emitted when a sanctions list bulk-upsert completes."""
	event_type: str = "reg.sanctions.list_updated"
	list_source: str = ""
	records_upserted: int = 0
	records_delisted: int = 0


# ---------------------------------------------------------------------------
# Scheduler events  [CRITICAL]
# ---------------------------------------------------------------------------

@dataclass
class ScheduledReportGeneratedEvent(DomainEvent):
	"""Emitted when SchedulerService.tick() successfully generates a report."""
	event_type: str = "reg.scheduler.report_generated"
	schedule_id: str = ""
	report_type: str = ""
	report_id: str = ""
	submitted_to_regulator: bool = False


@dataclass
class ScheduledReportFailedEvent(DomainEvent):
	"""Emitted when a scheduled report generation or submission fails."""
	event_type: str = "reg.scheduler.report_failed"
	schedule_id: str = ""
	report_type: str = ""
	error_message: str = ""
	retry_count: int = 0


# ---------------------------------------------------------------------------
# Limit events  [HIGH]
# ---------------------------------------------------------------------------

@dataclass
class LimitBreachedEvent(DomainEvent):
	"""Emitted when a regulatory limit is breached (action=ALERT or REPORT)."""
	event_type: str = "reg.limit.breached"
	limit_id: str = ""
	limit_type: str = ""
	entity_id: str = ""
	limit_amount_cents: int = 0
	proposed_amount_cents: int = 0
	current_utilisation_cents: int = 0
	breach_action: str = ""


# ---------------------------------------------------------------------------
# SLA events  [HIGH]
# ---------------------------------------------------------------------------

@dataclass
class AlertSLABreachedEvent(DomainEvent):
	"""Emitted when an AML alert investigation SLA deadline is missed."""
	event_type: str = "reg.sla.alert_breached"
	alert_id: str = ""
	alert_number: str = ""
	sla_due_at: str = ""   # ISO datetime string
	breached_at: str = ""  # ISO datetime string
	assigned_to: str = ""


@dataclass
class SARFilingDeadlineBreachedEvent(DomainEvent):
	"""Emitted when the CBK 3-day SAR filing deadline is missed."""
	event_type: str = "reg.sla.sar_deadline_breached"
	alert_id: str = ""
	alert_number: str = ""
	sar_filing_deadline: str = ""  # ISO datetime string
	breached_at: str = ""


# ---------------------------------------------------------------------------
# Reversal events  [HIGH]
# ---------------------------------------------------------------------------

@dataclass
class SARReversedEvent(DomainEvent):
	"""Emitted when a SAR is formally reversed and superseded."""
	event_type: str = "reg.sar.reversed"
	original_sar_id: str = ""
	original_sar_number: str = ""
	replacement_sar_id: str = ""
	reversal_record_id: str = ""
	reason_code: str = ""
	reversed_by: str = ""


# ---------------------------------------------------------------------------
# Reconciliation events  [HIGH]
# ---------------------------------------------------------------------------

@dataclass
class ReconciliationFailedEvent(DomainEvent):
	"""Emitted when a reconciliation run detects variance beyond tolerance."""
	event_type: str = "reg.reconciliation.failed"
	run_id: str = ""
	report_type: str = ""
	period: str = ""
	variance_pct: str = ""  # Decimal serialised as string
	tolerance_pct: str = ""


# ---------------------------------------------------------------------------
# GL posting events  [CRITICAL]
# ---------------------------------------------------------------------------

@dataclass
class IFRS9GLPostedEvent(DomainEvent):
	"""Emitted when IFRS 9 ECL delta is successfully posted to the GL."""
	event_type: str = "reg.ifrs9.gl_posted"
	run_id: str = ""
	gl_journal_id: str = ""
	delta_ecl_cents: int = 0
	provision_expense_account: str = ""
	loan_loss_reserve_account: str = ""


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

REG_AML_ALERT_GENERATED = "reg.aml.alert_generated"
REG_AML_ALERT_ESCALATED = "reg.aml.alert_escalated"
REG_AML_ALERT_CLOSED = "reg.aml.alert_closed"
REG_SAR_FILED = "reg.sar.filed"
REG_SAR_ACKNOWLEDGED = "reg.sar.acknowledged"
REG_SAR_REVERSED = "reg.sar.reversed"
REG_CAPITAL_REPORT_GENERATED = "reg.capital.report_generated"
REG_CAPITAL_BREACHED = "reg.capital.breached"
REG_IFRS9_RUN_COMPLETED = "reg.ifrs9.run_completed"
REG_IFRS9_GL_POSTED = "reg.ifrs9.gl_posted"
REG_PEP_MATCH_FOUND = "reg.pep.match_found"
REG_PEP_ENTRY_ADDED = "reg.pep.entry_added"
REG_SANCTIONS_HIT = "reg.sanctions.hit"
REG_SANCTIONS_LIST_UPDATED = "reg.sanctions.list_updated"
REG_SCHEDULER_REPORT_GENERATED = "reg.scheduler.report_generated"
REG_SCHEDULER_REPORT_FAILED = "reg.scheduler.report_failed"
REG_LIMIT_BREACHED = "reg.limit.breached"
REG_SLA_ALERT_BREACHED = "reg.sla.alert_breached"
REG_SLA_SAR_DEADLINE_BREACHED = "reg.sla.sar_deadline_breached"
REG_RECONCILIATION_FAILED = "reg.reconciliation.failed"

ALL_REG_EVENT_TYPES: list[str] = [
	REG_AML_ALERT_GENERATED,
	REG_AML_ALERT_ESCALATED,
	REG_AML_ALERT_CLOSED,
	REG_SAR_FILED,
	REG_SAR_ACKNOWLEDGED,
	REG_SAR_REVERSED,
	REG_CAPITAL_REPORT_GENERATED,
	REG_CAPITAL_BREACHED,
	REG_IFRS9_RUN_COMPLETED,
	REG_IFRS9_GL_POSTED,
	REG_PEP_MATCH_FOUND,
	REG_PEP_ENTRY_ADDED,
	REG_SANCTIONS_HIT,
	REG_SANCTIONS_LIST_UPDATED,
	REG_SCHEDULER_REPORT_GENERATED,
	REG_SCHEDULER_REPORT_FAILED,
	REG_LIMIT_BREACHED,
	REG_SLA_ALERT_BREACHED,
	REG_SLA_SAR_DEADLINE_BREACHED,
	REG_RECONCILIATION_FAILED,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"AMLAlertGeneratedEvent",
	"AMLAlertEscalatedEvent",
	"AMLAlertClosedEvent",
	"SARFiledEvent",
	"SARAcknowledgedEvent",
	"SARReversedEvent",
	"CapitalReportGeneratedEvent",
	"CapitalBreachedEvent",
	"IFRS9RunCompletedEvent",
	"IFRS9GLPostedEvent",
	"PEPMatchFoundEvent",
	"PEPEntryAddedEvent",
	"SanctionsHitEvent",
	"SanctionsListUpdatedEvent",
	"ScheduledReportGeneratedEvent",
	"ScheduledReportFailedEvent",
	"LimitBreachedEvent",
	"AlertSLABreachedEvent",
	"SARFilingDeadlineBreachedEvent",
	"ReconciliationFailedEvent",
	# type constants
	"REG_AML_ALERT_GENERATED",
	"REG_AML_ALERT_ESCALATED",
	"REG_AML_ALERT_CLOSED",
	"REG_SAR_FILED",
	"REG_SAR_ACKNOWLEDGED",
	"REG_SAR_REVERSED",
	"REG_CAPITAL_REPORT_GENERATED",
	"REG_CAPITAL_BREACHED",
	"REG_IFRS9_RUN_COMPLETED",
	"REG_IFRS9_GL_POSTED",
	"REG_PEP_MATCH_FOUND",
	"REG_PEP_ENTRY_ADDED",
	"REG_SANCTIONS_HIT",
	"REG_SANCTIONS_LIST_UPDATED",
	"REG_SCHEDULER_REPORT_GENERATED",
	"REG_SCHEDULER_REPORT_FAILED",
	"REG_LIMIT_BREACHED",
	"REG_SLA_ALERT_BREACHED",
	"REG_SLA_SAR_DEADLINE_BREACHED",
	"REG_RECONCILIATION_FAILED",
	"ALL_REG_EVENT_TYPES",
]
