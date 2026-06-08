from __future__ import annotations

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.finance.period_close.models import (
	PeriodCloseTemplate,
	PeriodClose,
	PeriodCloseTask,
)


class PeriodCloseTemplateView(ModelView):
	datamodel = SQLAInterface(PeriodCloseTemplate)

	list_columns = ['name', 'is_default', 'tenant_id']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


class PeriodCloseView(ModelView):
	datamodel = SQLAInterface(PeriodClose)

	list_columns = ['period', 'entity_id', 'status', 'started_at', 'closed_at', 'started_by']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


class PeriodCloseTaskView(ModelView):
	datamodel = SQLAInterface(PeriodCloseTask)

	list_columns = ['close_id', 'task_code', 'title', 'status', 'is_mandatory',
					'owner_role', 'owner_id', 'completed_at']
	add_exclude_columns = ['id']
	edit_exclude_columns = ['id']


__all__ = [
	'PeriodCloseTemplateView',
	'PeriodCloseView',
	'PeriodCloseTaskView',
]
