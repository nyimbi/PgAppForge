from __future__ import annotations

from flask import current_app, jsonify

from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.finance.period_close.models import (
	PeriodCloseTemplate,
	PeriodClose,
	PeriodCloseTask,
)
from pgappforge.plugins.erp.finance.period_close.services import PeriodCloseService


def _get_session():
	ab = current_app.extensions.get("appbuilder")
	if ab and hasattr(ab, "get_session"):
		return ab.get_session
	db = current_app.extensions.get("sqlalchemy")
	if db:
		return db.session
	raise RuntimeError("Cannot obtain database session outside app context")


class PeriodCloseTemplateView(ModelView):
	datamodel = SQLAInterface(PeriodCloseTemplate)

	list_columns = ['name', 'is_default', 'tenant_id']
	show_columns = ['id', 'name', 'description', 'is_default', 'tasks']
	label_columns = {
		'name': 'Name',
		'is_default': 'Default',
		'tenant_id': 'Tenant',
		'description': 'Description',
		'tasks': 'Tasks',
	}
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


class PeriodCloseView(ModelView):
	datamodel = SQLAInterface(PeriodClose)

	list_columns = ['period', 'entity_id', 'status', 'started_at', 'closed_at', 'started_by']
	show_columns = ['id', 'period', 'entity_id', 'status', 'started_at',
					'closed_at', 'started_by', 'closed_by']
	label_columns = {
		'period': 'Period',
		'entity_id': 'Entity',
		'status': 'Status',
		'started_at': 'Started At',
		'closed_at': 'Closed At',
		'started_by': 'Started By',
		'closed_by': 'Closed By',
	}
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']

	@expose('/check-can-close/<string:close_id>')
	@has_access
	def check_can_close(self, close_id: str):
		session = _get_session()
		result = PeriodCloseService().check_can_close(close_id, session)
		return jsonify(result)


class PeriodCloseTaskView(ModelView):
	datamodel = SQLAInterface(PeriodCloseTask)

	list_columns = ['close_id', 'task_code', 'title', 'status', 'is_mandatory',
					'owner_role', 'owner_id', 'completed_at']
	show_columns = ['id', 'task_code', 'title', 'is_mandatory', 'owner_role',
					'depends_on', 'status', 'owner_id', 'completed_at', 'notes']
	label_columns = {
		'close_id': 'Period Close',
		'task_code': 'Task Code',
		'title': 'Title',
		'status': 'Status',
		'is_mandatory': 'Mandatory',
		'owner_role': 'Owner Role',
		'owner_id': 'Owner',
		'completed_at': 'Completed At',
		'depends_on': 'Depends On',
		'notes': 'Notes',
	}
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'PeriodCloseTemplateView',
	'PeriodCloseView',
	'PeriodCloseTaskView',
]
