"""
pgappforge/plugins/erp/operations/process_manufacturing/views.py

Flask-AppBuilder views for the Process Manufacturing plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

log = logging.getLogger(__name__)


class RecipeView(ModelView):
	from pgappforge.plugins.erp.operations.process_manufacturing.models import Recipe
	datamodel = SQLAInterface(Recipe)
	list_columns = ['product_id', 'version', 'status', 'batch_size', 'batch_size_unit', 'yield_pct', 'process_time_minutes']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class RecipeIngredientView(ModelView):
	from pgappforge.plugins.erp.operations.process_manufacturing.models import RecipeIngredient
	datamodel = SQLAInterface(RecipeIngredient)
	list_columns = ['recipe_id', 'material_id', 'qty', 'unit', 'is_critical']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class BatchRecordView(ModelView):
	from pgappforge.plugins.erp.operations.process_manufacturing.models import BatchRecord
	datamodel = SQLAInterface(BatchRecord)
	list_columns = ['batch_ref', 'recipe_id', 'status', 'planned_qty', 'actual_qty', 'started_at', 'completed_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"RecipeView",
	"RecipeIngredientView",
	"BatchRecordView",
]
