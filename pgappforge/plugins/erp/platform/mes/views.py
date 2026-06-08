"""
pgappforge/plugins/erp/platform/mes/views.py

Flask-AppBuilder views for the Manufacturing Execution System plugin.
"""
from __future__ import annotations

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

log = logging.getLogger(__name__)


class MachineDefinitionView(ModelView):
	from pgappforge.plugins.erp.platform.mes.models import MachineDefinition
	datamodel = SQLAInterface(MachineDefinition)
	list_columns = ['machine_code', 'work_center_id', 'opc_ua_endpoint', 'is_active', 'downtime_threshold_minutes', 'quality_threshold_pct']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MachineReadingView(ModelView):
	from pgappforge.plugins.erp.platform.mes.models import MachineReading
	datamodel = SQLAInterface(MachineReading)
	list_columns = ['machine_id', 'reading_at', 'production_order_id']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ProductionAlertView(ModelView):
	from pgappforge.plugins.erp.platform.mes.models import ProductionAlert
	datamodel = SQLAInterface(ProductionAlert)
	list_columns = ['machine_id', 'alert_type', 'severity', 'message', 'status', 'created_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"MachineDefinitionView",
	"MachineReadingView",
	"ProductionAlertView",
]
