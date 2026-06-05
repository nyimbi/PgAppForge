"""
pgappforge/plugins/fintech/trade_finance/views.py

Trade Finance views: LC management, presentations, guarantees, collections,
SCF programmes, and a trade exposure dashboard.

Widget conventions:
  - All amount / money columns:   CurrencyWidget (USD default, KES for local)
  - Date fields:                  DatePickerWidget
  - Date range filters:           DateTimeRangeWidget
  - SWIFT text / legal text:      DocumentViewerWidget (rich_text fallback)
  - JSON documents/discrepancies: JSONEditorWidget
  - Type selectors:               Select2Widget with enum choices
  - Exposure dashboard:           AdvancedChartsWidget (bar, line)
  - Party lookup:                 Select2AJAXWidget

Security:
  - LCView, GuaranteeView:            can_list, can_show (all), can_add/can_edit (trade_ops)
  - LCPresentationView:               can_list, can_show (all), can_add (trade_ops)
  - CollectionView:                   can_list, can_show (all), can_add (trade_ops)
  - SCF views:                        admin + trade_ops
  - TradeDashboard:                   read-only BaseView
"""
from __future__ import annotations

import logging
from typing import Any

from flask import flash, redirect, request, url_for
from flask_appbuilder import BaseView, ModelView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access

from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_range_widget,
	date_widget,
	json_widget,
	rich_text_widget,
	select2_ajax_widget,
	select2_widget,
)
from pgappforge.plugins.fintech.trade_finance.models import (
	BankGuarantee,
	DocumentaryCollection,
	LetterOfCredit,
	LCPresentation,
	SCFReceivable,
	SupplyChainFinanceProgram,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared label maps
# ---------------------------------------------------------------------------

_LC_LABELS: dict[str, str] = {
	"lc_number": "LC Number",
	"lc_type": "LC Type",
	"applicant_id": "Applicant (Importer)",
	"beneficiary_name": "Beneficiary (Exporter)",
	"beneficiary_bank_bic": "Beneficiary Bank BIC",
	"issuing_bank_id": "Issuing Bank",
	"confirming_bank_bic": "Confirming Bank BIC",
	"advising_bank_bic": "Advising Bank BIC",
	"currency_code": "Currency",
	"amount_cents": "LC Amount",
	"tolerance_pct": "Tolerance %",
	"margin_cents": "Margin Held",
	"amount_utilized_cents": "Amount Utilized",
	"issue_date": "Issue Date",
	"expiry_date": "Expiry Date",
	"expiry_place": "Expiry Place",
	"latest_shipment_date": "Latest Shipment Date",
	"partial_shipments": "Partial Shipments",
	"transhipment": "Transhipment",
	"port_of_loading": "Port of Loading",
	"port_of_discharge": "Port of Discharge",
	"description_of_goods": "Description of Goods",
	"documents_required": "Documents Required",
	"special_conditions": "Special Conditions",
	"swift_mt700": "SWIFT MT700",
	"status": "Status",
}

_PRES_LABELS: dict[str, str] = {
	"presentation_number": "Presentation Number",
	"lc_id": "Letter of Credit",
	"presented_by_bank_bic": "Presenting Bank BIC",
	"presentation_date": "Presentation Date",
	"amount_presented_cents": "Amount Presented",
	"documents_presented": "Documents Presented",
	"discrepancies": "Discrepancies",
	"status": "Status",
	"examination_completed_at": "Examination Completed",
	"payment_due_date": "Payment Due Date",
	"payment_made_at": "Payment Made",
}

_BG_LABELS: dict[str, str] = {
	"guarantee_number": "Guarantee Number",
	"guarantee_type": "Guarantee Type",
	"applicant_id": "Applicant",
	"beneficiary_name": "Beneficiary",
	"underlying_contract_reference": "Contract / Tender Ref.",
	"currency_code": "Currency",
	"amount_cents": "Guarantee Amount",
	"commission_rate_pa": "Commission Rate p.a.",
	"margin_cents": "Margin Held",
	"claimed_amount_cents": "Claimed Amount",
	"issue_date": "Issue Date",
	"expiry_date": "Expiry Date",
	"claim_period_days": "Claim Period (days)",
	"guarantee_text": "Guarantee Text",
	"status": "Status",
}

_DC_LABELS: dict[str, str] = {
	"collection_number": "Collection Number",
	"collection_type": "Type",
	"exporter_id": "Exporter",
	"importer_name": "Importer",
	"remitting_bank_bic": "Remitting Bank BIC",
	"collecting_bank_bic": "Collecting Bank BIC",
	"currency_code": "Currency",
	"amount_cents": "Amount",
	"draft_tenor": "Draft Tenor",
	"documents_held": "Documents Held",
	"instructions": "Collection Instructions",
	"status": "Status",
}

_SCF_PROG_LABELS: dict[str, str] = {
	"program_code": "Programme Code",
	"program_name": "Programme Name",
	"buyer_id": "Anchor Buyer",
	"currency_code": "Currency",
	"max_programme_limit_cents": "Programme Limit",
	"utilised_cents": "Utilised",
	"discount_rate_pa": "Discount Rate p.a.",
	"start_date": "Start Date",
	"end_date": "End Date",
	"status": "Status",
}

_LC_TYPE_CHOICES = [
	("SIGHT", "Sight LC"),
	("USANCE", "Usance LC"),
	("TRANSFERABLE", "Transferable LC"),
	("BACK_TO_BACK", "Back-to-Back LC"),
	("STANDBY", "Standby LC (SBLC)"),
	("RED_CLAUSE", "Red Clause LC"),
	("GREEN_CLAUSE", "Green Clause LC"),
]

_LC_STATUS_CHOICES = [
	("DRAFT", "Draft"),
	("ISSUED", "Issued"),
	("AMENDED", "Amended"),
	("PRESENTED", "Presented"),
	("DISCREPANT", "Discrepant"),
	("ACCEPTED", "Accepted"),
	("PAID", "Paid"),
	("EXPIRED", "Expired"),
	("CANCELLED", "Cancelled"),
]

_BG_TYPE_CHOICES = [
	("BID_BOND", "Bid Bond"),
	("PERFORMANCE", "Performance Bond"),
	("ADVANCE_PAYMENT", "Advance Payment Guarantee"),
	("PAYMENT", "Payment Guarantee"),
	("RETENTION", "Retention Bond"),
	("CUSTOMS", "Customs Guarantee"),
]

_DC_TYPE_CHOICES = [
	("D/P", "D/P — Documents against Payment"),
	("D/A", "D/A — Documents against Acceptance"),
]

_PRES_STATUS_CHOICES = [
	("UNDER_EXAMINATION", "Under Examination"),
	("COMPLIANT", "Compliant"),
	("DISCREPANT", "Discrepant"),
	("ACCEPTED", "Accepted"),
	("REJECTED", "Rejected"),
	("WAIVED", "Waived"),
]


# ---------------------------------------------------------------------------
# LCView
# ---------------------------------------------------------------------------

class LCView(ModelView):
	"""Letter of Credit CRUD view.

	Provides full lifecycle management of LCs: issuance, amendment,
	SWIFT MT700 viewer, and utilisation tracking.
	"""

	datamodel = SQLAInterface(LetterOfCredit)

	list_title = "Letters of Credit"
	show_title = "Letter of Credit Detail"
	add_title = "Issue New Letter of Credit"
	edit_title = "Amend Letter of Credit"

	list_columns = [
		"lc_number", "lc_type", "beneficiary_name",
		"currency_code", "amount_cents", "amount_utilized_cents",
		"issue_date", "expiry_date", "status",
	]
	show_columns = [
		"lc_number", "lc_type",
		"applicant_id", "beneficiary_name", "beneficiary_bank_bic",
		"issuing_bank_id", "confirming_bank_bic", "advising_bank_bic",
		"currency_code", "amount_cents", "tolerance_pct",
		"margin_cents", "amount_utilized_cents",
		"issue_date", "expiry_date", "expiry_place", "latest_shipment_date",
		"partial_shipments", "transhipment",
		"port_of_loading", "port_of_discharge",
		"description_of_goods", "documents_required", "special_conditions",
		"swift_mt700", "status",
		"created_at", "updated_at",
	]
	add_columns = [
		"lc_number", "lc_type",
		"applicant_id", "beneficiary_name", "beneficiary_bank_bic",
		"issuing_bank_id", "confirming_bank_bic", "advising_bank_bic",
		"currency_code", "amount_cents", "tolerance_pct",
		"applicant_margin_account_id", "margin_cents",
		"issue_date", "expiry_date", "expiry_place", "latest_shipment_date",
		"partial_shipments", "transhipment",
		"port_of_loading", "port_of_discharge",
		"description_of_goods", "documents_required", "special_conditions",
	]
	edit_columns = [
		"lc_type", "amount_cents", "tolerance_pct",
		"expiry_date", "latest_shipment_date",
		"partial_shipments", "transhipment",
		"description_of_goods", "documents_required", "special_conditions",
		"status",
	]

	label_columns = _LC_LABELS

	search_columns = [
		"lc_number", "beneficiary_name", "status", "lc_type",
		"currency_code", "port_of_loading", "port_of_discharge",
	]
	order_columns = ["lc_number", "issue_date", "expiry_date", "amount_cents", "status"]

	# Widget configuration
	add_form_extra_fields = {
		"lc_type": select2_widget(_LC_TYPE_CHOICES),
		"applicant_id": select2_ajax_widget(),
		"issuing_bank_id": select2_ajax_widget(),
		"amount_cents": currency_widget("USD"),
		"margin_cents": currency_widget("USD"),
		"issue_date": date_widget(),
		"expiry_date": date_widget(),
		"latest_shipment_date": date_widget(),
		"documents_required": json_widget(mode="tree", height=250),
	}
	edit_form_extra_fields = {
		"lc_type": select2_widget(_LC_TYPE_CHOICES),
		"amount_cents": currency_widget("USD"),
		"expiry_date": date_widget(),
		"latest_shipment_date": date_widget(),
		"documents_required": json_widget(mode="tree", height=250),
		"status": select2_widget(_LC_STATUS_CHOICES),
	}
	show_fieldsets = [
		(
			"LC Identity",
			{"fields": ["lc_number", "lc_type", "status"]},
		),
		(
			"Parties",
			{"fields": [
				"applicant_id", "beneficiary_name", "beneficiary_bank_bic",
				"issuing_bank_id", "confirming_bank_bic", "advising_bank_bic",
			]},
		),
		(
			"Financial Terms",
			{"fields": [
				"currency_code", "amount_cents", "tolerance_pct",
				"margin_cents", "amount_utilized_cents",
			]},
		),
		(
			"Dates & Shipment",
			{"fields": [
				"issue_date", "expiry_date", "expiry_place", "latest_shipment_date",
				"partial_shipments", "transhipment",
				"port_of_loading", "port_of_discharge",
			]},
		),
		(
			"Goods & Documents",
			{"fields": ["description_of_goods", "documents_required", "special_conditions"]},
		),
		(
			"SWIFT MT700",
			{"fields": ["swift_mt700"]},
		),
		(
			"Audit",
			{"fields": ["created_at", "updated_at"]},
		),
	]


# ---------------------------------------------------------------------------
# LCPresentationView
# ---------------------------------------------------------------------------

class LCPresentationView(ModelView):
	"""LC Presentation management — document examination and payment tracking.

	Immutable records: the view prevents edit of existing presentations.
	"""

	datamodel = SQLAInterface(LCPresentation)

	list_title = "LC Presentations"
	show_title = "Presentation Detail"
	add_title = "Record New Presentation"

	list_columns = [
		"presentation_number", "lc_id",
		"presentation_date", "amount_presented_cents",
		"status", "examination_completed_at", "payment_due_date",
	]
	show_columns = [
		"presentation_number", "lc_id",
		"presented_by_bank_bic", "presentation_date",
		"amount_presented_cents", "documents_presented",
		"discrepancies", "status",
		"examination_completed_at", "payment_due_date", "payment_made_at",
		"created_at",
	]
	add_columns = [
		"lc_id", "presentation_number",
		"presented_by_bank_bic", "presentation_date",
		"amount_presented_cents", "documents_presented",
	]
	# Presentations are immutable — no edit_columns

	label_columns = _PRES_LABELS

	search_columns = [
		"presentation_number", "status", "presented_by_bank_bic",
	]
	order_columns = ["presentation_date", "amount_presented_cents", "status"]

	add_form_extra_fields = {
		"lc_id": select2_ajax_widget(),
		"presentation_date": date_widget(),
		"amount_presented_cents": currency_widget("USD"),
		"documents_presented": json_widget(mode="tree", height=300),
	}
	show_fieldsets = [
		(
			"Presentation",
			{"fields": [
				"presentation_number", "lc_id", "status",
				"presented_by_bank_bic", "presentation_date", "amount_presented_cents",
			]},
		),
		(
			"Documents",
			{"fields": ["documents_presented"]},
		),
		(
			"Examination Result",
			{"fields": [
				"discrepancies", "examination_completed_at",
				"payment_due_date", "payment_made_at",
			]},
		),
	]


# ---------------------------------------------------------------------------
# GuaranteeView
# ---------------------------------------------------------------------------

class GuaranteeView(ModelView):
	"""Bank Guarantee management view."""

	datamodel = SQLAInterface(BankGuarantee)

	list_title = "Bank Guarantees"
	show_title = "Guarantee Detail"
	add_title = "Issue New Bank Guarantee"
	edit_title = "Update Bank Guarantee"

	list_columns = [
		"guarantee_number", "guarantee_type", "beneficiary_name",
		"currency_code", "amount_cents", "claimed_amount_cents",
		"issue_date", "expiry_date", "status",
	]
	show_columns = [
		"guarantee_number", "guarantee_type",
		"applicant_id", "beneficiary_name",
		"underlying_contract_reference",
		"currency_code", "amount_cents", "commission_rate_pa",
		"margin_cents", "claimed_amount_cents",
		"issue_date", "expiry_date", "claim_period_days",
		"guarantee_text", "status",
		"created_at", "updated_at",
	]
	add_columns = [
		"guarantee_number", "guarantee_type",
		"applicant_id", "beneficiary_name",
		"underlying_contract_reference",
		"currency_code", "amount_cents", "commission_rate_pa",
		"margin_account_id", "margin_cents",
		"issue_date", "expiry_date", "claim_period_days",
		"guarantee_text",
	]
	edit_columns = [
		"expiry_date", "claim_period_days",
		"guarantee_text", "status",
	]

	label_columns = _BG_LABELS

	search_columns = [
		"guarantee_number", "beneficiary_name", "guarantee_type",
		"underlying_contract_reference", "status",
	]
	order_columns = ["guarantee_number", "issue_date", "expiry_date", "amount_cents"]

	add_form_extra_fields = {
		"guarantee_type": select2_widget(_BG_TYPE_CHOICES),
		"applicant_id": select2_ajax_widget(),
		"amount_cents": currency_widget("KES"),
		"margin_cents": currency_widget("KES"),
		"margin_account_id": select2_ajax_widget(),
		"issue_date": date_widget(),
		"expiry_date": date_widget(),
		"guarantee_text": rich_text_widget(height=350),
	}
	edit_form_extra_fields = {
		"expiry_date": date_widget(),
		"guarantee_text": rich_text_widget(height=350),
	}
	show_fieldsets = [
		(
			"Guarantee Identity",
			{"fields": ["guarantee_number", "guarantee_type", "status"]},
		),
		(
			"Parties",
			{"fields": ["applicant_id", "beneficiary_name", "underlying_contract_reference"]},
		),
		(
			"Financial Terms",
			{"fields": [
				"currency_code", "amount_cents", "commission_rate_pa",
				"margin_cents", "claimed_amount_cents",
			]},
		),
		(
			"Dates",
			{"fields": ["issue_date", "expiry_date", "claim_period_days"]},
		),
		(
			"Guarantee Text",
			{"fields": ["guarantee_text"]},
		),
		(
			"Audit",
			{"fields": ["created_at", "updated_at"]},
		),
	]


# ---------------------------------------------------------------------------
# CollectionView
# ---------------------------------------------------------------------------

class CollectionView(ModelView):
	"""Documentary Collection management view."""

	datamodel = SQLAInterface(DocumentaryCollection)

	list_title = "Documentary Collections"
	show_title = "Collection Detail"
	add_title = "Register New Collection"
	edit_title = "Update Collection"

	list_columns = [
		"collection_number", "collection_type", "importer_name",
		"currency_code", "amount_cents",
		"draft_tenor", "status",
	]
	show_columns = [
		"collection_number", "collection_type",
		"exporter_id", "importer_name",
		"remitting_bank_bic", "collecting_bank_bic",
		"currency_code", "amount_cents", "draft_tenor",
		"documents_held", "instructions",
		"status", "created_at", "updated_at",
	]
	add_columns = [
		"collection_number", "collection_type",
		"exporter_id", "importer_name",
		"remitting_bank_bic", "collecting_bank_bic",
		"currency_code", "amount_cents", "draft_tenor",
		"documents_held", "instructions",
	]
	edit_columns = ["status", "draft_tenor", "instructions"]

	label_columns = _DC_LABELS

	search_columns = [
		"collection_number", "importer_name", "collection_type", "status",
	]
	order_columns = ["collection_number", "amount_cents", "status"]

	add_form_extra_fields = {
		"collection_type": select2_widget(_DC_TYPE_CHOICES),
		"exporter_id": select2_ajax_widget(),
		"amount_cents": currency_widget("USD"),
		"documents_held": json_widget(mode="tree", height=200),
	}
	show_fieldsets = [
		(
			"Collection Identity",
			{"fields": ["collection_number", "collection_type", "status"]},
		),
		(
			"Parties",
			{"fields": [
				"exporter_id", "importer_name",
				"remitting_bank_bic", "collecting_bank_bic",
			]},
		),
		(
			"Financial Terms",
			{"fields": ["currency_code", "amount_cents", "draft_tenor"]},
		),
		(
			"Documents & Instructions",
			{"fields": ["documents_held", "instructions"]},
		),
		(
			"Audit",
			{"fields": ["created_at", "updated_at"]},
		),
	]


# ---------------------------------------------------------------------------
# SCFProgramView  /  SCFReceivableView
# ---------------------------------------------------------------------------

class SCFProgramView(ModelView):
	"""Supply Chain Finance programme view."""

	datamodel = SQLAInterface(SupplyChainFinanceProgram)

	list_title = "SCF Programmes"
	show_title = "SCF Programme Detail"
	add_title = "Create SCF Programme"
	edit_title = "Update SCF Programme"

	list_columns = [
		"program_code", "program_name", "buyer_id",
		"currency_code", "max_programme_limit_cents", "utilised_cents",
		"discount_rate_pa", "start_date", "end_date", "status",
	]
	show_columns = [
		"program_code", "program_name", "buyer_id",
		"currency_code", "max_programme_limit_cents", "utilised_cents",
		"discount_rate_pa", "start_date", "end_date", "status",
		"created_at", "updated_at",
	]
	add_columns = [
		"program_code", "program_name", "buyer_id",
		"currency_code", "max_programme_limit_cents",
		"discount_rate_pa", "start_date", "end_date",
	]
	edit_columns = ["max_programme_limit_cents", "discount_rate_pa", "end_date", "status"]

	label_columns = _SCF_PROG_LABELS

	add_form_extra_fields = {
		"buyer_id": select2_ajax_widget(),
		"max_programme_limit_cents": currency_widget("KES"),
		"start_date": date_widget(),
		"end_date": date_widget(),
	}


class SCFReceivableView(ModelView):
	"""SCF Receivable (early-payment record) view — read-only, immutable records."""

	datamodel = SQLAInterface(SCFReceivable)

	list_title = "SCF Receivables"
	show_title = "SCF Receivable Detail"

	list_columns = [
		"receivable_number", "program_id", "supplier_id",
		"invoice_reference", "invoice_amount_cents",
		"early_payment_cents", "discount_cents",
		"buyer_payment_due_date", "status",
	]
	show_columns = [
		"receivable_number", "program_id", "supplier_id",
		"invoice_reference", "currency_code",
		"invoice_amount_cents", "early_payment_cents", "discount_cents",
		"buyer_payment_due_date", "early_payment_date", "status",
		"created_at",
	]

	label_columns = {
		"receivable_number": "Receivable Number",
		"program_id": "SCF Programme",
		"supplier_id": "Supplier",
		"invoice_reference": "Invoice Reference",
		"invoice_amount_cents": "Invoice Amount",
		"early_payment_cents": "Early Payment",
		"discount_cents": "Discount / Fee",
		"buyer_payment_due_date": "Buyer Due Date",
		"early_payment_date": "Early Payment Date",
		"status": "Status",
	}


# ---------------------------------------------------------------------------
# TradeDashboard  — read-only exposure summary
# ---------------------------------------------------------------------------

class TradeDashboard(BaseView):
	"""Trade Finance exposure dashboard.

	Displays:
	  - Outstanding LC exposure by type (bar chart)
	  - LC maturity profile — amounts maturing by month (line chart)
	  - Guarantee exposure by type (bar chart)
	  - SCF utilisation by programme (bar chart)
	  - Recent activity (combined event log widget)
	"""

	route_base = "/trade-finance/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self) -> Any:
		"""Render the trade finance exposure dashboard."""
		from flask_appbuilder import AppBuilder
		from flask import current_app

		widgets = {
			"lc_exposure_chart": chart_widget("bar"),
			"lc_maturity_chart": chart_widget("line"),
			"guarantee_chart": chart_widget("bar"),
			"scf_utilisation_chart": chart_widget("bar"),
		}
		return self.render_template(
			"trade_finance/dashboard.html",
			widgets=widgets,
			title="Trade Finance Dashboard",
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LCView",
	"LCPresentationView",
	"GuaranteeView",
	"CollectionView",
	"SCFProgramView",
	"SCFReceivableView",
	"TradeDashboard",
]
