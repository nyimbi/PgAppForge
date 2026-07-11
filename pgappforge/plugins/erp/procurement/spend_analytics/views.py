from __future__ import annotations
from flask_babel import lazy_gettext as _

from decimal import Decimal

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.procurement.spend_analytics.models import SpendSnapshot

try:
	from pgappforge.charts.widgets import ChartWidget as BarChartWidget
except Exception:
	BarChartWidget = None


def _format_cents(value):
	if value is None:
		return ""
	return f"{Decimal(int(value)) / Decimal('100'):,.2f}"


class SpendSnapshotView(ModelView):
	datamodel = SQLAInterface(SpendSnapshot)

	label_columns = {
		'period': _('Period'),
		'supplier_id': _('Supplier'),
		'supplier_name': _('Supplier Name'),
		'category': _('Category'),
		'department': _('Department'),
		'amount_cents': _('Amount'),
		'invoice_count': _('Invoice Count'),
		'created_at': _('Created At'),
		'updated_at': _('Updated At'),
	}
	list_columns = ['period', 'supplier_id', 'supplier_name', 'category',
					'department', 'amount_cents', 'invoice_count']
	show_columns = ['tenant_id', 'period', 'supplier_id', 'supplier_name',
					'category', 'department', 'amount_cents', 'invoice_count',
					'created_at', 'updated_at']
	search_columns = ['period', 'supplier_id', 'supplier_name', 'category',
					  'department']
	add_columns = ['tenant_id', 'period', 'supplier_id', 'supplier_name', 'category',
				   'department', 'amount_cents', 'invoice_count']
	edit_columns = add_columns
	formatters_columns = {'amount_cents': _format_cents}
	spend_by_category_chart_widget = BarChartWidget


__all__ = ['SpendSnapshotView']
