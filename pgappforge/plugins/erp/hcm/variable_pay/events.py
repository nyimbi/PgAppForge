"""
pgappforge/plugins/erp/hcm/variable_pay/events.py

Domain events for the HCM Variable Pay plugin.

All monetary amounts are integer cents — never float.

Events emitted:
  hcm.variable_pay.quota.assigned         — quota assigned to employee
  hcm.variable_pay.attainment.recorded    — actual attainment recorded against quota
  hcm.variable_pay.commission.calculated  — commission calculation completed
  hcm.variable_pay.commission.approved    — payout approved for payment
  hcm.variable_pay.commission.paid        — payout disbursed via payrun
  hcm.variable_pay.accelerator.applied    — accelerator multiplier applied above threshold

Events consumed:
  hcm.payroll.run.calculated  — optionally triggers commission payment marking
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class QuotaAssignedEvent(DomainEvent):
	"""Emitted when a quota is assigned to an employee for a plan period."""
	event_type: str = "hcm.variable_pay.quota.assigned"
	quota_id: str = ""
	employee_id: str = ""
	amount_cents: int = 0
	period: str = ""
	tenant_id: str = ""


@dataclass
class AttainmentRecordedEvent(DomainEvent):
	"""Emitted when actual attainment is recorded against a quota."""
	event_type: str = "hcm.variable_pay.attainment.recorded"
	quota_id: str = ""
	actual_cents: int = 0
	attainment_pct: float = 0.0


@dataclass
class CommissionCalculatedEvent(DomainEvent):
	"""Emitted when commission calculation completes for an employee period."""
	event_type: str = "hcm.variable_pay.commission.calculated"
	employee_id: str = ""
	period: str = ""
	commission_cents: int = 0


@dataclass
class CommissionApprovedEvent(DomainEvent):
	"""Emitted when a commission payout is approved for payment."""
	event_type: str = "hcm.variable_pay.commission.approved"
	payout_id: str = ""
	employee_id: str = ""
	amount_cents: int = 0
	approved_by: str = ""


@dataclass
class CommissionPaidEvent(DomainEvent):
	"""Emitted when a commission payout is disbursed via a payrun."""
	event_type: str = "hcm.variable_pay.commission.paid"
	payout_id: str = ""
	employee_id: str = ""
	amount_cents: int = 0
	payrun_id: str = ""


@dataclass
class AcceleratorAppliedEvent(DomainEvent):
	"""Emitted when an accelerator multiplier kicks in above threshold attainment."""
	event_type: str = "hcm.variable_pay.accelerator.applied"
	quota_id: str = ""
	attainment_pct: float = 0.0
	multiplier: float = 1.0


__all__ = [
	"QuotaAssignedEvent",
	"AttainmentRecordedEvent",
	"CommissionCalculatedEvent",
	"CommissionApprovedEvent",
	"CommissionPaidEvent",
	"AcceleratorAppliedEvent",
]
