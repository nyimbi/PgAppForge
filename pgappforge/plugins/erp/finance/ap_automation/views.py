from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.ap_automation.models import InvoiceCapture


class InvoiceCaptureView(ModelView):
	datamodel = SQLAInterface(InvoiceCapture)

	list_columns = ['detected_vendor', 'detected_invoice_number', 'detected_amount_cents',
					'detected_date', 'source_format', 'status', 'confidence_pct',
					'matched_vendor_id']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = ['InvoiceCaptureView']
