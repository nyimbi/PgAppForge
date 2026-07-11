"""
pgappforge/plugins/erp/platform/mes/views.py

Flask-AppBuilder views for the Manufacturing Execution System plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

import logging

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.platform.mes.models import (
	MachineDefinition,
	MachineReading,
	ProductionAlert,
)

log = logging.getLogger(__name__)


class MachineDefinitionView(ModelView):
	datamodel = SQLAInterface(MachineDefinition)
	list_columns = ['machine_code', 'work_center_id', 'opc_ua_endpoint', 'is_active']
	show_columns = ['tenant_id', 'machine_code', 'work_center_id', 'opc_ua_endpoint', 'telemetry_schema', 'is_active']
	label_columns = {
		'tenant_id': _('Tenant'),
		'machine_code': _('Machine Code'),
		'work_center_id': _('Work Center'),
		'opc_ua_endpoint': _('OPC UA Endpoint'),
		'telemetry_schema': _('Telemetry Schema'),
		'is_active': _('Active'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class MachineReadingView(ModelView):
	datamodel = SQLAInterface(MachineReading)
	list_columns = ['machine_id', 'reading_at', 'readings']
	show_columns = ['machine_id', 'reading_at', 'readings']
	label_columns = {
		'machine_id': _('Machine'),
		'reading_at': _('Reading Time'),
		'readings': _('Readings'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ProductionAlertView(ModelView):
	datamodel = SQLAInterface(ProductionAlert)
	list_columns = ['machine_id', 'alert_type', 'severity', 'started_at', 'resolved_at']
	show_columns = ['machine_id', 'alert_type', 'severity', 'started_at', 'resolved_at', 'description']
	label_columns = {
		'machine_id': _('Machine'),
		'alert_type': _('Alert Type'),
		'severity': _('Severity'),
		'started_at': _('Started At'),
		'resolved_at': _('Resolved At'),
		'description': _('Description'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


__all__ = [
	"MachineDefinitionView",
	"MachineReadingView",
	"ProductionAlertView",
]
