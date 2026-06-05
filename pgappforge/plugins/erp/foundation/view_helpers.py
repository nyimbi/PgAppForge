"""
View creation utilities for ERP plugins.

Provides widget configurations and common label maps so plugin views.py files
stay DRY and use consistent widget choices across the suite.

Usage::

	from pgappforge.plugins.erp.foundation.view_helpers import (
		currency_widget, date_widget, address_widget, phone_widget,
		json_widget, file_widget, select2_widget, select2_ajax_widget,
		MONEY_LABELS, DATE_LABELS, STATUS_LABELS,
	)
"""
from __future__ import annotations

from typing import Any


# ── Widget config factories ────────────────────────────────────────────────
# Each function returns a plain dict that FAB widget machinery consumes.
# Keeping them as functions (not module-level dicts) lets callers pass
# per-field overrides without mutating a shared object.

def currency_widget(currency: str = "USD") -> dict[str, Any]:
	return {"type": "CurrencyWidget", "config": {"currency": currency, "decimal_places": 2}}


def date_widget(placeholder: str = "YYYY-MM-DD") -> dict[str, Any]:
	return {"type": "DatePickerWidget", "config": {"placeholder": placeholder}}


def datetime_widget() -> dict[str, Any]:
	return {"type": "DateTimePickerWidget", "config": {}}


def date_range_widget() -> dict[str, Any]:
	return {"type": "DateTimeRangeWidget", "config": {"date_format": "YYYY-MM-DD"}}


def address_widget() -> dict[str, Any]:
	return {
		"type": "AddressAutocompleteWidget",
		"config": {"geocode_on_select": True, "show_map": True},
	}


def rich_text_widget(height: int = 200) -> dict[str, Any]:
	return {
		"type": "RichTextEditorWidget",
		"config": {"height": height, "toolbar": "standard"},
	}


def json_widget(mode: str = "tree", height: int = 200, readonly: bool = False) -> dict[str, Any]:
	return {
		"type": "JSONEditorWidget",
		"config": {
			"mode": mode,
			"height": height,
			"readonly": readonly,
			"schema_validation": True,
		},
	}


def map_widget(zoom: int = 13) -> dict[str, Any]:
	return {
		"type": "GeoPointWidget",
		"config": {"map_provider": "openstreetmap", "default_zoom": zoom},
	}


def phone_widget() -> dict[str, Any]:
	return {
		"type": "PhoneNumberWidget",
		"config": {
			"default_country": "KE",
			"preferred_countries": ["KE", "US", "GB", "NG", "ZA", "TZ", "UG"],
		},
	}


def star_widget(max_rating: int = 5, readonly: bool = False) -> dict[str, Any]:
	return {
		"type": "StarRatingWidget",
		"config": {"max_rating": max_rating, "allow_half": True, "readonly": readonly},
	}


def progress_widget(max_value: int = 100) -> dict[str, Any]:
	return {
		"type": "RangeSliderWidget",
		"config": {
			"step": 1,
			"show_value": True,
			"show_ticks": False,
			"readonly": True,
			"max": max_value,
		},
	}


def signature_widget() -> dict[str, Any]:
	return {
		"type": "SignaturePadWidget",
		"config": {"pen_color": "#000000", "pen_size": 2, "require_name": False},
	}


def file_widget(multiple: bool = False, types: list[str] | None = None) -> dict[str, Any]:
	return {
		"type": "FileUploadWidget",
		"config": {
			"multiple": multiple,
			"allowed_extensions": types or ["pdf", "jpg", "png", "docx"],
		},
	}


def chart_widget(chart_type: str = "bar") -> dict[str, Any]:
	return {
		"type": "AdvancedChartsWidget",
		"config": {"chart_type": chart_type, "responsive": True, "animation": True},
	}


def select2_widget(choices: list | None = None) -> dict[str, Any]:
	cfg: dict[str, Any] = {}
	if choices is not None:
		cfg["choices"] = choices
	return {"type": "Select2Widget", "config": cfg}


def select2_ajax_widget(min_chars: int = 1) -> dict[str, Any]:
	return {
		"type": "Select2AJAXWidget",
		"config": {"delay": 250, "minimum_input_length": min_chars},
	}


def select2_many_widget() -> dict[str, Any]:
	return {"type": "Select2ManyWidget", "config": {"close_on_select": False}}


def password_widget() -> dict[str, Any]:
	return {
		"type": "PasswordStrengthWidget",
		"config": {"min_length": 12, "require_special": True},
	}


def qr_widget(size: int = 200) -> dict[str, Any]:
	return {"type": "QrCodeWidget", "config": {"size": size, "error_correction": "M"}}


def heatmap_widget() -> dict[str, Any]:
	return {"type": "GeographicHeatmapWidget", "config": {"radius": 25, "opacity": 0.8}}


# ── Common label sets ──────────────────────────────────────────────────────
# Merge these into a view's ``label_columns`` dict to get consistent human
# labels across all ERP list/detail views without repeating the mapping.

MONEY_LABELS: dict[str, str] = {
	"amount_cents": "Amount",
	"total_cents": "Total",
	"balance_due_cents": "Balance Due",
	"paid_cents": "Paid",
	"subtotal_cents": "Subtotal",
	"tax_cents": "Tax",
	"discount_cents": "Discount",
	"gross_pay_cents": "Gross Pay",
	"net_pay_cents": "Net Pay",
	"credit_limit_cents": "Credit Limit",
	"budget_cents": "Budget",
}

DATE_LABELS: dict[str, str] = {
	"invoice_date": "Invoice Date",
	"due_date": "Due Date",
	"payment_date": "Payment Date",
	"start_date": "Start Date",
	"end_date": "End Date",
	"effective_date": "Effective Date",
	"created_at": "Created",
	"updated_at": "Last Updated",
}

STATUS_LABELS: dict[str, str] = {
	"status": "Status",
	"approval_status": "Approval",
	"match_status": "Match Status",
	"payment_status": "Payment Status",
	"enrollment_status": "Enrollment",
}

# Convenience: merged label set for views that carry all three categories.
ERP_LABELS: dict[str, str] = {**MONEY_LABELS, **DATE_LABELS, **STATUS_LABELS}


# ── Public API ─────────────────────────────────────────────────────────────

__all__ = [
	# widgets
	"currency_widget",
	"date_widget",
	"datetime_widget",
	"date_range_widget",
	"address_widget",
	"rich_text_widget",
	"json_widget",
	"map_widget",
	"phone_widget",
	"star_widget",
	"progress_widget",
	"signature_widget",
	"file_widget",
	"chart_widget",
	"select2_widget",
	"select2_ajax_widget",
	"select2_many_widget",
	"password_widget",
	"qr_widget",
	"heatmap_widget",
	# labels
	"MONEY_LABELS",
	"DATE_LABELS",
	"STATUS_LABELS",
	"ERP_LABELS",
]
