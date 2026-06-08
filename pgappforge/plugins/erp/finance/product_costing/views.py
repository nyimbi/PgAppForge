from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.product_costing.models import (
	CostVersion,
	CostElement,
	ProductStandardCost,
	ProductionOrderActualCost,
)


class CostVersionView(ModelView):
	datamodel = SQLAInterface(CostVersion)

	list_columns = ['product_id', 'version_type', 'status', 'effective_from',
					'effective_to', 'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class CostElementView(ModelView):
	datamodel = SQLAInterface(CostElement)

	list_columns = ['version_id', 'element_type', 'description',
					'unit_cost_cents', 'total_cost_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class StandardCostView(ModelView):
	datamodel = SQLAInterface(ProductStandardCost)

	list_columns = ['product_id', 'effective_from', 'total_standard_cost_cents',
					'material_cost_cents', 'labor_cost_cents', 'overhead_cost_cents',
					'currency_code']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class ActualCostView(ModelView):
	datamodel = SQLAInterface(ProductionOrderActualCost)

	list_columns = ['product_id', 'production_order_id', 'period',
					'total_actual_cents', 'total_standard_cents', 'total_variance_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


class CostVarianceReportView(ModelView):
	datamodel = SQLAInterface(ProductionOrderActualCost)

	list_title = 'Cost Variance Report'
	list_columns = ['product_id', 'period', 'total_actual_cents',
					'total_standard_cents', 'total_variance_cents',
					'price_variance_cents', 'qty_variance_cents']
	add_exclude_columns = ['id', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_at', 'updated_at']


__all__ = [
	'CostVersionView',
	'CostElementView',
	'StandardCostView',
	'ActualCostView',
	'CostVarianceReportView',
]
