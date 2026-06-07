from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"EmissionRecordedEvent",
	"EmissionReportGeneratedEvent",
	"EmissionFactorUpdatedEvent",
	"ReductionTargetSetEvent",
	"OffsetAppliedEvent",
]


@dataclass
class EmissionRecordedEvent(DomainEvent):
	event_type: str = field(default="platform.carbon.emission.recorded", init=False)
	record_id: str = ""
	scope: int = 0
	source_type: str = ""
	co2e_kg: str = ""  # Decimal serialised as str
	tenant_id: str = ""


@dataclass
class EmissionReportGeneratedEvent(DomainEvent):
	event_type: str = field(default="platform.carbon.report.generated", init=False)
	report_id: str = ""
	period: str = ""
	total_co2e_kg: str = ""  # Decimal serialised as str


@dataclass
class EmissionFactorUpdatedEvent(DomainEvent):
	event_type: str = field(default="platform.carbon.factor.updated", init=False)
	factor_id: str = ""
	source_type: str = ""
	co2e_per_unit: str = ""  # Decimal serialised as str


@dataclass
class ReductionTargetSetEvent(DomainEvent):
	event_type: str = field(default="platform.carbon.target.set", init=False)
	target_id: str = ""
	target_year: int = 0
	reduction_pct: str = ""  # Decimal serialised as str
	baseline_co2e_kg: str = ""  # Decimal serialised as str


@dataclass
class OffsetAppliedEvent(DomainEvent):
	event_type: str = field(default="platform.carbon.offset.applied", init=False)
	offset_id: str = ""
	co2e_kg: str = ""  # Decimal serialised as str
	provider: str = ""
	cost_cents: int = 0
