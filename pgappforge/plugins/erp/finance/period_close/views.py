from __future__ import annotations
from flask_babel import lazy_gettext as _

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
		'name': _('Name'),
		'is_default': _('Default'),
		'tenant_id': _('Tenant'),
		'description': _('Description'),
		'tasks': _('Tasks'),
	}
	search_columns = ['name', 'tenant_id', 'is_default']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


class PeriodCloseView(ModelView):
	datamodel = SQLAInterface(PeriodClose)

	list_columns = ['period', 'entity_id', 'status', 'started_at', 'closed_at', 'started_by']
	show_columns = ['id', 'period', 'status', 'started_at',
					'closed_at', 'started_by', 'closed_by']
	label_columns = {
		'period': _('Period'),
		'entity_id': _('Entity'),
		'status': _('Status'),
		'started_at': _('Started At'),
		'closed_at': _('Closed At'),
		'started_by': _('Started By'),
		'closed_by': _('Closed By'),
	}
	search_columns = ['period', 'entity_id', 'status', 'started_by', 'closed_by']
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
		'close_id': _('Period Close'),
		'task_code': _('Task Code'),
		'title': _('Title'),
		'status': _('Status'),
		'is_mandatory': _('Mandatory'),
		'owner_role': _('Owner Role'),
		'owner_id': _('Owner'),
		'completed_at': _('Completed At'),
		'depends_on': _('Depends On'),
		'notes': _('Notes'),
	}
	search_columns = ['close_id', 'task_code', 'title', 'status', 'owner_role', 'owner_id']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'PeriodCloseTemplateView',
	'PeriodCloseView',
	'PeriodCloseTaskView',
]
