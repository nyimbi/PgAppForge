"""
pgappforge/plugins/erp/platform/anomaly_detection/views.py

Flask-AppBuilder views for the Anomaly Detection plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.anomaly_detection.models import (
	Anomaly,
	AnomalyDetectionRun,
)

log = logging.getLogger(__name__)


class AnomalyDetectionRunView(ModelView):
	datamodel = SQLAInterface(AnomalyDetectionRun)
	list_columns = ['run_type', 'period', 'status', 'anomalies_found', 'created_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnomalyView(ModelView):
	datamodel = SQLAInterface(Anomaly)
	list_columns = ['anomaly_type', 'severity', 'source_module', 'source_record_id', 'status', 'created_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class AnomalyDashboardView(BaseERPView):
	route_base = "/platform/anomaly-detection"

	@expose("/")
	@has_access
	def index(self):
		try:
			sess = self._session()
			open_anomalies = self._count(Anomaly, session=sess, status="OPEN")
			critical = self._count(Anomaly, session=sess, severity="CRITICAL")
			resolved = self._count(Anomaly, session=sess, status="RESOLVED")
		except Exception:
			open_anomalies = critical = resolved = 0
		kpi_html = self.kpi_cards([
			{"label": "Open Anomalies", "value": open_anomalies, "icon": "fa-exclamation-circle", "color": "#9e1c00"},
			{"label": "Critical Severity", "value": critical, "icon": "fa-bolt", "color": "#ff5a1f"},
			{"label": "Resolved Today", "value": resolved, "icon": "fa-check-circle", "color": "#0e9f6e"},
		])
		return render_template(
			"platform_anomaly/anomaly_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"AnomalyDetectionRunView",
	"AnomalyView",
	"AnomalyDashboardView",
]
