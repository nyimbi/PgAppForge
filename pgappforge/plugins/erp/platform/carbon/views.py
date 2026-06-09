"""
pgappforge/plugins/erp/platform/carbon/views.py

Flask-AppBuilder views for the Carbon Accounting plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.carbon.models import (
	EmissionFactor,
	EmissionRecord,
	GHGReport,
)

log = logging.getLogger(__name__)


class EmissionFactorView(ModelView):
	datamodel = SQLAInterface(EmissionFactor)
	list_columns = ['source_type', 'country_code', 'scope', 'co2e_per_unit', 'unit', 'effective_from', 'effective_to']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EmissionRecordView(ModelView):
	datamodel = SQLAInterface(EmissionRecord)
	list_columns = ['scope', 'source_type', 'description', 'activity_data', 'unit', 'co2e_kg', 'period']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class GHGReportView(ModelView):
	datamodel = SQLAInterface(GHGReport)
	list_columns = ['period', 'scope1_co2e_kg', 'scope2_co2e_kg', 'scope3_co2e_kg', 'total_co2e_kg', 'methodology']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CarbonDashboardView(BaseERPView):
	route_base = "/platform/carbon"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.platform.carbon.models import EmissionRecord
			import sqlalchemy as sa
			sess = self._session()
			total_co2e = int(sess.execute(
				sa.select(sa.func.coalesce(sa.func.sum(EmissionRecord.co2e_kg), 0))
			).scalar_one())
			scope1 = int(sess.execute(
				sa.select(sa.func.coalesce(sa.func.sum(EmissionRecord.co2e_kg), 0))
				.where(EmissionRecord.scope == 1)
			).scalar_one())
			scope2 = int(sess.execute(
				sa.select(sa.func.coalesce(sa.func.sum(EmissionRecord.co2e_kg), 0))
				.where(EmissionRecord.scope == 2)
			).scalar_one())
		except Exception:
			total_co2e = scope1 = scope2 = 0
		kpi_html = self.kpi_cards([
			{"label": "Total CO2e (kg)", "value": total_co2e, "icon": "fa-leaf", "color": "#0e9f6e"},
			{"label": "Scope 1 (kg)", "value": scope1, "icon": "fa-fire", "color": "#ff5a1f"},
			{"label": "Scope 2 (kg)", "value": scope2, "icon": "fa-bolt", "color": "#1a56db"},
		])
		return render_template(
			"platform_carbon/carbon_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"EmissionFactorView",
	"EmissionRecordView",
	"GHGReportView",
	"CarbonDashboardView",
]
