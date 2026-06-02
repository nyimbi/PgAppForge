"""
pgappforge/plugins/erp/finance/assets/events.py

Domain events for the Asset Accounting plugin.

Emitted events:
  asset.capitalised       — new fixed asset created and capitalised
  asset.depreciation_run  — periodic depreciation batch completed
  asset.disposed          — asset removed from register
  asset.impaired          — impairment loss recognised
  asset.impairment_reversed — impairment reversal

Subscribed events (upstream):
  exchange_rate.updated   — to revalue foreign-currency assets
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event


# ---------------------------------------------------------------------------
# Asset events
# ---------------------------------------------------------------------------

@dataclass
class AssetCapitalisedEvent(DomainEvent):
	"""Fired when a new fixed asset is capitalised into the register."""
	event_type: str = "asset.capitalised"
	asset_id: str = ""
	asset_number: str = ""
	asset_class_id: str = ""
	acquisition_cost_cents: int = 0
	currency: str = "NGN"
	acquisition_date: str = ""


@dataclass
class AssetDepreciationRunEvent(DomainEvent):
	"""Fired after a depreciation batch run completes for a period."""
	event_type: str = "asset.depreciation_run"
	period_id: str = ""
	assets_processed: int = 0
	total_depreciation_cents: int = 0
	currency: str = "NGN"


@dataclass
class AssetDisposedEvent(DomainEvent):
	"""Fired when a fixed asset is disposed of (sold, scrapped, donated)."""
	event_type: str = "asset.disposed"
	asset_id: str = ""
	asset_number: str = ""
	disposal_date: str = ""
	proceeds_cents: int = 0
	gain_loss_cents: int = 0  # positive = gain, negative = loss
	currency: str = "NGN"


@dataclass
class AssetImpairedEvent(DomainEvent):
	"""Fired when an IAS 36 impairment loss is recognised."""
	event_type: str = "asset.impaired"
	asset_id: str = ""
	asset_number: str = ""
	impairment_date: str = ""
	impairment_loss_cents: int = 0
	recoverable_amount_cents: int = 0
	currency: str = "NGN"


@dataclass
class AssetImpairmentReversedEvent(DomainEvent):
	"""Fired when a prior impairment is reversed (IAS 36 §117)."""
	event_type: str = "asset.impairment_reversed"
	asset_id: str = ""
	asset_number: str = ""
	reversal_date: str = ""
	reversal_amount_cents: int = 0
	currency: str = "NGN"


__all__ = [
	"AssetCapitalisedEvent",
	"AssetDepreciationRunEvent",
	"AssetDisposedEvent",
	"AssetImpairedEvent",
	"AssetImpairmentReversedEvent",
	"emit_event",
]
