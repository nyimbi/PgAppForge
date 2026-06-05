"""
pgappforge/plugins/fintech/trade_finance/events.py

Trade Finance domain events.

All events extend DomainEvent from erp.foundation.events.
Emitted by TradeFinanceService, persisted atomically to DomainEventLog
within the same SQLAlchemy session. Event emission never causes service failure
(wrapped in try/except in services.py).

Event catalogue
---------------
  tf.lc.issued              — new LC issued to applicant
  tf.lc.amended             — LC terms amended (SWIFT MT707)
  tf.lc.presentation.received   — documents presented for examination
  tf.lc.presentation.compliant  — presentation examined, no discrepancies
  tf.lc.presentation.discrepant — presentation examined, discrepancies found
  tf.lc.presentation.accepted   — discrepancies waived or compliant, accepted
  tf.lc.presentation.rejected   — discrepancies not waived, rejected
  tf.lc.settled             — payment made, LC closed
  tf.lc.expired             — LC expired without full utilisation
  tf.guarantee.issued       — bank guarantee issued
  tf.guarantee.extended     — guarantee expiry extended
  tf.guarantee.claimed      — beneficiary lodged a claim
  tf.guarantee.expired      — guarantee expired without claim
  tf.collection.received    — documentary collection received from remitting bank
  tf.collection.presented   — documents presented to importer
  tf.collection.paid        — D/P collection: importer paid
  tf.collection.accepted    — D/A collection: importer accepted draft
  tf.collection.protested   — non-payment/non-acceptance — formal protest
  tf.scf.receivable.funded  — supplier received early payment
  tf.scf.receivable.repaid  — buyer repaid the bank at maturity
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


# ---------------------------------------------------------------------------
# Letter of Credit events
# ---------------------------------------------------------------------------

@dataclass
class LCIssuedEvent(DomainEvent):
	"""Emitted when a Letter of Credit transitions DRAFT → ISSUED."""
	event_type: str = "tf.lc.issued"
	lc_id: str = ""
	lc_number: str = ""
	applicant_id: str = ""
	beneficiary_name: str = ""
	lc_type: str = ""
	currency_code: str = ""
	amount_cents: int = 0
	issue_date: str = ""		# ISO date string
	expiry_date: str = ""		# ISO date string
	margin_cents: int = 0


@dataclass
class LCAmendedEvent(DomainEvent):
	"""Emitted when an LC is amended (generates SWIFT MT707)."""
	event_type: str = "tf.lc.amended"
	lc_id: str = ""
	lc_number: str = ""
	amendments: dict = field(default_factory=dict)
	# keys are field names, values are {before, after} dicts
	swift_mt707: str = ""


@dataclass
class LCPresentationReceivedEvent(DomainEvent):
	"""Emitted when documents are received for examination (clock starts: 5 banking days)."""
	event_type: str = "tf.lc.presentation.received"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	presentation_number: str = ""
	presentation_date: str = ""		# ISO date string
	amount_presented_cents: int = 0
	presented_by_bank_bic: str = ""


@dataclass
class LCPresentationCompliantEvent(DomainEvent):
	"""Emitted when examination finds no discrepancies (UCP 600 Art 15)."""
	event_type: str = "tf.lc.presentation.compliant"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	presentation_number: str = ""
	amount_presented_cents: int = 0
	payment_due_date: str = ""		# ISO date, empty for sight LCs (immediate)


@dataclass
class LCPresentationDiscrepantEvent(DomainEvent):
	"""Emitted when examination reveals discrepancies (UCP 600 Art 16)."""
	event_type: str = "tf.lc.presentation.discrepant"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	presentation_number: str = ""
	discrepancies: list = field(default_factory=list)
	discrepancy_count: int = 0


@dataclass
class LCPresentationAcceptedEvent(DomainEvent):
	"""Emitted when presentation is accepted (compliant or discrepancies waived)."""
	event_type: str = "tf.lc.presentation.accepted"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	presentation_number: str = ""
	waived_discrepancies: list = field(default_factory=list)
	amount_cents: int = 0


@dataclass
class LCPresentationRejectedEvent(DomainEvent):
	"""Emitted when discrepancies are not waived and presentation is refused."""
	event_type: str = "tf.lc.presentation.rejected"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	presentation_number: str = ""
	rejection_reason: str = ""


@dataclass
class LCSettledEvent(DomainEvent):
	"""Emitted when LC payment is executed and instrument is closed."""
	event_type: str = "tf.lc.settled"
	lc_id: str = ""
	lc_number: str = ""
	presentation_id: str = ""
	amount_paid_cents: int = 0
	currency_code: str = ""
	debit_journal_id: str = ""		# applicant account debit
	credit_journal_id: str = ""		# beneficiary / nostro credit
	margin_released_cents: int = 0


@dataclass
class LCExpiredEvent(DomainEvent):
	"""Emitted when an LC reaches expiry_date without full utilisation."""
	event_type: str = "tf.lc.expired"
	lc_id: str = ""
	lc_number: str = ""
	expiry_date: str = ""			# ISO date string
	amount_cents: int = 0
	amount_utilized_cents: int = 0
	unutilised_cents: int = 0
	margin_released_cents: int = 0


# ---------------------------------------------------------------------------
# Bank Guarantee events
# ---------------------------------------------------------------------------

@dataclass
class GuaranteeIssuedEvent(DomainEvent):
	"""Emitted when a Bank Guarantee is issued."""
	event_type: str = "tf.guarantee.issued"
	guarantee_id: str = ""
	guarantee_number: str = ""
	applicant_id: str = ""
	beneficiary_name: str = ""
	guarantee_type: str = ""
	currency_code: str = ""
	amount_cents: int = 0
	issue_date: str = ""			# ISO date string
	expiry_date: str = ""			# ISO date string
	margin_cents: int = 0
	commission_charged_cents: int = 0


@dataclass
class GuaranteeExtendedEvent(DomainEvent):
	"""Emitted when a guarantee's expiry date is extended."""
	event_type: str = "tf.guarantee.extended"
	guarantee_id: str = ""
	guarantee_number: str = ""
	previous_expiry_date: str = ""	# ISO date string
	new_expiry_date: str = ""		# ISO date string
	additional_commission_cents: int = 0


@dataclass
class GuaranteeClaimedEvent(DomainEvent):
	"""Emitted when beneficiary lodges a claim against a guarantee."""
	event_type: str = "tf.guarantee.claimed"
	guarantee_id: str = ""
	guarantee_number: str = ""
	claim_amount_cents: int = 0
	claim_reason: str = ""
	margin_used_cents: int = 0
	bank_exposure_cents: int = 0	# amount paid from bank's own funds (margin shortfall)
	payment_journal_id: str = ""


@dataclass
class GuaranteeExpiredEvent(DomainEvent):
	"""Emitted when a guarantee expires without a claim being lodged."""
	event_type: str = "tf.guarantee.expired"
	guarantee_id: str = ""
	guarantee_number: str = ""
	expiry_date: str = ""			# ISO date string
	margin_released_cents: int = 0


# ---------------------------------------------------------------------------
# Documentary Collection events
# ---------------------------------------------------------------------------

@dataclass
class CollectionReceivedEvent(DomainEvent):
	"""Emitted when a documentary collection arrives from remitting bank."""
	event_type: str = "tf.collection.received"
	collection_id: str = ""
	collection_number: str = ""
	exporter_id: str = ""
	importer_name: str = ""
	collection_type: str = ""		# D/P or D/A
	amount_cents: int = 0
	currency_code: str = ""
	remitting_bank_bic: str = ""


@dataclass
class CollectionPresentedEvent(DomainEvent):
	"""Emitted when collecting bank presents documents to importer."""
	event_type: str = "tf.collection.presented"
	collection_id: str = ""
	collection_number: str = ""
	presentation_date: str = ""		# ISO date string


@dataclass
class CollectionPaidEvent(DomainEvent):
	"""Emitted for D/P collections when importer pays and receives documents."""
	event_type: str = "tf.collection.paid"
	collection_id: str = ""
	collection_number: str = ""
	amount_paid_cents: int = 0
	payment_journal_id: str = ""


@dataclass
class CollectionAcceptedEvent(DomainEvent):
	"""Emitted for D/A collections when importer accepts draft (gets documents, pays later)."""
	event_type: str = "tf.collection.accepted"
	collection_id: str = ""
	collection_number: str = ""
	acceptance_date: str = ""		# ISO date string
	maturity_date: str = ""			# ISO date string — when payment falls due


@dataclass
class CollectionProtestedEvent(DomainEvent):
	"""Emitted when importer refuses to pay or accept — formal protest lodged."""
	event_type: str = "tf.collection.protested"
	collection_id: str = ""
	collection_number: str = ""
	protest_reason: str = ""		# NON_PAYMENT | NON_ACCEPTANCE


# ---------------------------------------------------------------------------
# Supply Chain Finance events
# ---------------------------------------------------------------------------

@dataclass
class SCFReceivableFundedEvent(DomainEvent):
	"""Emitted when a supplier receives early payment under an SCF programme."""
	event_type: str = "tf.scf.receivable.funded"
	receivable_id: str = ""
	receivable_number: str = ""
	program_id: str = ""
	supplier_id: str = ""
	invoice_reference: str = ""
	invoice_amount_cents: int = 0
	early_payment_cents: int = 0
	discount_cents: int = 0
	payment_journal_id: str = ""


@dataclass
class SCFReceivableRepaidEvent(DomainEvent):
	"""Emitted when anchor buyer repays the bank at invoice maturity."""
	event_type: str = "tf.scf.receivable.repaid"
	receivable_id: str = ""
	receivable_number: str = ""
	program_id: str = ""
	invoice_amount_cents: int = 0
	repayment_journal_id: str = ""


# ---------------------------------------------------------------------------
# Event type string constants
# ---------------------------------------------------------------------------

TF_LC_ISSUED = "tf.lc.issued"
TF_LC_AMENDED = "tf.lc.amended"
TF_LC_PRESENTATION_RECEIVED = "tf.lc.presentation.received"
TF_LC_PRESENTATION_COMPLIANT = "tf.lc.presentation.compliant"
TF_LC_PRESENTATION_DISCREPANT = "tf.lc.presentation.discrepant"
TF_LC_PRESENTATION_ACCEPTED = "tf.lc.presentation.accepted"
TF_LC_PRESENTATION_REJECTED = "tf.lc.presentation.rejected"
TF_LC_SETTLED = "tf.lc.settled"
TF_LC_EXPIRED = "tf.lc.expired"
TF_GUARANTEE_ISSUED = "tf.guarantee.issued"
TF_GUARANTEE_EXTENDED = "tf.guarantee.extended"
TF_GUARANTEE_CLAIMED = "tf.guarantee.claimed"
TF_GUARANTEE_EXPIRED = "tf.guarantee.expired"
TF_COLLECTION_RECEIVED = "tf.collection.received"
TF_COLLECTION_PRESENTED = "tf.collection.presented"
TF_COLLECTION_PAID = "tf.collection.paid"
TF_COLLECTION_ACCEPTED = "tf.collection.accepted"
TF_COLLECTION_PROTESTED = "tf.collection.protested"
TF_SCF_RECEIVABLE_FUNDED = "tf.scf.receivable.funded"
TF_SCF_RECEIVABLE_REPAID = "tf.scf.receivable.repaid"

ALL_TF_EVENT_TYPES: list[str] = [
	TF_LC_ISSUED,
	TF_LC_AMENDED,
	TF_LC_PRESENTATION_RECEIVED,
	TF_LC_PRESENTATION_COMPLIANT,
	TF_LC_PRESENTATION_DISCREPANT,
	TF_LC_PRESENTATION_ACCEPTED,
	TF_LC_PRESENTATION_REJECTED,
	TF_LC_SETTLED,
	TF_LC_EXPIRED,
	TF_GUARANTEE_ISSUED,
	TF_GUARANTEE_EXTENDED,
	TF_GUARANTEE_CLAIMED,
	TF_GUARANTEE_EXPIRED,
	TF_COLLECTION_RECEIVED,
	TF_COLLECTION_PRESENTED,
	TF_COLLECTION_PAID,
	TF_COLLECTION_ACCEPTED,
	TF_COLLECTION_PROTESTED,
	TF_SCF_RECEIVABLE_FUNDED,
	TF_SCF_RECEIVABLE_REPAID,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# event classes
	"LCIssuedEvent",
	"LCAmendedEvent",
	"LCPresentationReceivedEvent",
	"LCPresentationCompliantEvent",
	"LCPresentationDiscrepantEvent",
	"LCPresentationAcceptedEvent",
	"LCPresentationRejectedEvent",
	"LCSettledEvent",
	"LCExpiredEvent",
	"GuaranteeIssuedEvent",
	"GuaranteeExtendedEvent",
	"GuaranteeClaimedEvent",
	"GuaranteeExpiredEvent",
	"CollectionReceivedEvent",
	"CollectionPresentedEvent",
	"CollectionPaidEvent",
	"CollectionAcceptedEvent",
	"CollectionProtestedEvent",
	"SCFReceivableFundedEvent",
	"SCFReceivableRepaidEvent",
	# type string constants
	"TF_LC_ISSUED",
	"TF_LC_AMENDED",
	"TF_LC_PRESENTATION_RECEIVED",
	"TF_LC_PRESENTATION_COMPLIANT",
	"TF_LC_PRESENTATION_DISCREPANT",
	"TF_LC_PRESENTATION_ACCEPTED",
	"TF_LC_PRESENTATION_REJECTED",
	"TF_LC_SETTLED",
	"TF_LC_EXPIRED",
	"TF_GUARANTEE_ISSUED",
	"TF_GUARANTEE_EXTENDED",
	"TF_GUARANTEE_CLAIMED",
	"TF_GUARANTEE_EXPIRED",
	"TF_COLLECTION_RECEIVED",
	"TF_COLLECTION_PRESENTED",
	"TF_COLLECTION_PAID",
	"TF_COLLECTION_ACCEPTED",
	"TF_COLLECTION_PROTESTED",
	"TF_SCF_RECEIVABLE_FUNDED",
	"TF_SCF_RECEIVABLE_REPAID",
	"ALL_TF_EVENT_TYPES",
]
