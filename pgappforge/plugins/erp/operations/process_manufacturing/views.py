"""
pgappforge/plugins/erp/operations/process_manufacturing/views.py

Flask-AppBuilder views for the Process Manufacturing plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.operations.process_manufacturing.models import (
	BatchRecord,
	Recipe,
	RecipeIngredient,
)

log = logging.getLogger(__name__)


class RecipeView(ModelView):
	datamodel = SQLAInterface(Recipe)
	list_columns = ['product_id', 'version', 'status', 'batch_size', 'batch_size_unit', 'yield_pct', 'process_time_minutes']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RecipeIngredientView(ModelView):
	datamodel = SQLAInterface(RecipeIngredient)
	list_columns = ['recipe_id', 'material_id', 'qty', 'unit', 'is_critical']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class BatchRecordView(ModelView):
	datamodel = SQLAInterface(BatchRecord)
	list_columns = ['batch_ref', 'recipe_id', 'status', 'planned_qty', 'actual_qty', 'started_at', 'completed_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ProcessManufacturingDashboardView(BaseERPView):
	route_base = "/operations/process-manufacturing"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.process_manufacturing.models import Recipe, BatchRecord

		approved_recipes = self._count(Recipe, status="APPROVED")
		active_batches = self._count(BatchRecord, status="IN_PROCESS")
		completed_batches = self._count(BatchRecord, status="COMPLETED")

		kpi_html = self.kpi_cards([
			{"label": "Approved Recipes", "value": approved_recipes, "icon": "fa-flask", "color": "#1a56db"},
			{"label": "Active Batches", "value": active_batches, "icon": "fa-cog fa-spin", "color": "#ff5a1f"},
			{"label": "Completed Batches", "value": completed_batches, "icon": "fa-check", "color": "#0e9f6e"},
		])
		return render_template(
			"operations_ui/process_manufacturing.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"RecipeView",
	"RecipeIngredientView",
	"BatchRecordView",
	"ProcessManufacturingDashboardView",
]
