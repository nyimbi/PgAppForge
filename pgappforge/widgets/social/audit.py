"""AuditLogViewerWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.validators import ValidationError


def _js_str(v: Any) -> str:
	"""Emit a Python value as a safe JS string literal via json.dumps."""
	return json.dumps(str(v))


class AuditLogViewerWidget(BS3TextFieldWidget):
	"""
	Comprehensive audit log viewer widget for tracking system changes.

	Features:
	- Detailed change tracking with before/after comparison
	- Advanced filtering by date, user, action type
	- Interactive timeline visualization
	- User activity monitoring and analytics
	- Multi-format export (CSV, PDF, Excel)
	- Full-text search with highlighting
	- Side-by-side field comparison
	- Complete version history
	- Point-in-time data restore
	- Access and security logging
	- IP address and location tracking
	- Custom report generation
	- Compliance reporting (GDPR, SOX, etc)
	- Configurable data retention
	- Flexible event categorization
	- Real-time updates
	- Data visualization
	- Anomaly detection
	- Audit trail integrity
	- Custom field tracking

	Database Type:
		PostgreSQL: JSONB
		SQLAlchemy: JSON

	Required Dependencies:
	- DataTables 1.10+
	- Diff.js 3.5+
	- Timeline.js 3.8+
	- Moment.js 2.29+
	- Chart.js 3.7+
	- jsPDF 2.5+
	- SheetJS 0.18+

	Browser Support:
	- Chrome 60+
	- Firefox 60+
	- Safari 12+
	- Edge 79+
	- Opera 47+
	- iOS Safari 12+
	- Chrome for Android 89+

	Required Permissions:
	- LocalStorage access
	- File download
	- IndexedDB
	- Service Workers

	Performance Considerations:
	- Enable server-side pagination
	- Index audit log table
	- Cache common queries
	- Implement data archival
	- Optimize large datasets
	- Lazy load components
	- Debounce search
	- Throttle real-time updates

	Security Implications:
	- Validate user permissions
	- Sanitize search input
	- Prevent SQL injection
	- Encrypt sensitive data
	- Implement CSRF protection
	- Rate limit API calls
	- Log security events

	Example:
		audit_log = db.Column(db.JSON, nullable=False,
			info={'widget': AuditLogViewerWidget(
				tracked_fields=['name', 'status', 'price'],
				retention_days=365,
				export_formats=['csv', 'pdf', 'excel'],
				show_ip=True,
				track_changes=True,
				track_views=True,
				compliance_mode=True
			)})
	"""

	# JavaScript Dependencies
	JS_DEPENDENCIES = [
		"https://cdn.datatables.net/1.10.24/js/jquery.dataTables.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/diff/3.5.0/diff.min.js",
		"https://cdn.knightlab.com/libs/timeline3/latest/js/timeline.js",
		"https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
		"https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js",
		"/static/js/audit-log-viewer.js",
	]

	# CSS Dependencies
	CSS_DEPENDENCIES = [
		"https://cdn.datatables.net/1.10.24/css/jquery.dataTables.min.css",
		"https://cdn.knightlab.com/libs/timeline3/latest/css/timeline.css",
		"/static/css/audit-log-viewer.css",
	]

	def __init__(self, **kwargs):
		"""
		Initialize AuditLogViewerWidget with custom settings.

		Args:
			tracked_fields (list): Fields to track changes on
			retention_days (int): Number of days to retain audit logs
			export_formats (list): Available export formats
			show_ip (bool): Show IP addresses in logs
			track_changes (bool): Track field changes
			track_views (bool): Track record views
			compliance_mode (bool): Enable compliance features
			page_size (int): Records per page
			update_interval (int): Real-time update interval
			timezone (str): Display timezone
			date_format (str): Date display format
			field_labels (dict): Custom field labels
			chart_enabled (bool): Enable data visualization
			anomaly_detection (bool): Enable anomaly detection
			integrity_check (bool): Enable audit trail verification
			placeholder (str): Input placeholder text
			css_class (str): Additional CSS class(es)
			description (str): Help text displayed below the widget
			readonly (bool): Render widget as read-only
			disabled (bool): Render widget as disabled
		"""
		super().__init__(**kwargs)

		self.tracked_fields = kwargs.get("tracked_fields", [])
		self.retention_days = kwargs.get("retention_days", 365)
		self.export_formats = kwargs.get("export_formats", ["csv", "pdf", "excel"])
		self.show_ip = kwargs.get("show_ip", True)
		self.track_changes = kwargs.get("track_changes", True)
		self.track_views = kwargs.get("track_views", False)
		self.compliance_mode = kwargs.get("compliance_mode", False)
		self.page_size = kwargs.get("page_size", 50)
		self.update_interval = kwargs.get("update_interval", 30)
		self.timezone = kwargs.get("timezone", "UTC")
		self.date_format = kwargs.get("date_format", "YYYY-MM-DD HH:mm:ss")
		self.field_labels = kwargs.get("field_labels", {})
		self.chart_enabled = kwargs.get("chart_enabled", True)
		self.anomaly_detection = kwargs.get("anomaly_detection", False)
		self.integrity_check = kwargs.get("integrity_check", True)

		# Universal widget kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def render_field(self, field, **kwargs):
		"""Render the audit log viewer with all controls and visualizations."""
		kwargs.setdefault("id", field.id)

		# Accessibility and error-state attrs on the hidden input
		label_text = field.label.text if field.label else field.name
		kwargs.setdefault("aria-label", label_text)
		if self.description:
			kwargs["aria-describedby"] = f"{field.id}_help"
		if field.errors:
			kwargs["aria-invalid"] = "true"
			existing = kwargs.get("class", "")
			kwargs["class"] = (existing + " is-invalid").strip()
		if self.placeholder:
			kwargs.setdefault("placeholder", self.placeholder)
		if self.readonly:
			kwargs["readonly"] = True
		if self.disabled:
			kwargs["disabled"] = True
		if self.css_class:
			kwargs["class"] = (kwargs.get("class", "") + " " + self.css_class).strip()

		input_html = super().render_field(field, **kwargs)

		# All values that go into <script> must be JSON-encoded
		field_id_js = json.dumps(field.id)
		timezone_js = _js_str(self.timezone)
		date_format_js = _js_str(self.date_format)

		error_html = ""
		if field.errors:
			escaped_errors = " ".join(str(escape(e)) for e in field.errors)
			error_html = (
				f'<div class="invalid-feedback" id="{escape(field.id)}_error">'
				f'<span>{escaped_errors}</span>'
				f"</div>"
			)

		help_html = ""
		if self.description:
			help_html = (
				f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
				f"{escape(self.description)}</small>"
			)

		ip_header = '<th>IP Address</th>' if self.show_ip else ''
		view_option = '<option value="view">View</option>' if self.track_views else ''
		analytics_tab = (
			'<li class="nav-item">'
			'<a class="nav-link" data-toggle="tab" href="#charts-view" role="tab">Analytics</a>'
			'</li>'
		) if self.chart_enabled else ''
		analytics_pane = (
			f'<div class="tab-pane fade" id="charts-view" role="tabpanel">'
			f'<div class="row">'
			f'<div class="col-md-6"><canvas id="{escape(field.id)}-activity-chart"></canvas></div>'
			f'<div class="col-md-6"><canvas id="{escape(field.id)}-user-chart"></canvas></div>'
			f'</div></div>'
		) if self.chart_enabled else ''

		return Markup(
			f"""
			{self._include_dependencies()}

			<div class="audit-log-viewer" role="region" aria-label="Audit Log Viewer">
				<!-- Controls -->
				<div class="controls mb-3">
					<div class="row">
						<div class="col-md-3">
							<input type="text" class="form-control search"
							       placeholder="Search logs..." aria-label="Search">
						</div>
						<div class="col-md-3">
							<select class="form-control filter-type" aria-label="Event Type">
								<option value="">All Events</option>
								<option value="create">Create</option>
								<option value="update">Update</option>
								<option value="delete">Delete</option>
								{view_option}
							</select>
						</div>
						<div class="col-md-4">
							<div class="input-group">
								<input type="text" class="form-control date-range"
								       aria-label="Date Range">
								<div class="input-group-append">
									<button class="btn btn-outline-secondary" type="button">
										<i class="fa fa-calendar"></i>
									</button>
								</div>
							</div>
						</div>
						<div class="col-md-2">
							{self._render_export_buttons(field.id)}
						</div>
					</div>
				</div>

				<!-- Tabs -->
				<ul class="nav nav-tabs" role="tablist">
					<li class="nav-item">
						<a class="nav-link active" data-toggle="tab" href="#table-view"
						   role="tab">Table View</a>
					</li>
					<li class="nav-item">
						<a class="nav-link" data-toggle="tab" href="#timeline-view"
						   role="tab">Timeline</a>
					</li>
					{analytics_tab}
				</ul>

				<!-- Tab Content -->
				<div class="tab-content">
					<!-- Table View -->
					<div class="tab-pane fade show active" id="table-view" role="tabpanel">
						<table class="table audit-table" aria-label="Audit Log Table">
							<thead>
								<tr>
									<th>Timestamp</th>
									<th>User</th>
									<th>Action</th>
									<th>Details</th>
									{ip_header}
									<th>Actions</th>
								</tr>
							</thead>
							<tbody></tbody>
						</table>
					</div>

					<!-- Timeline View -->
					<div class="tab-pane fade" id="timeline-view" role="tabpanel">
						<div id="{escape(field.id)}-timeline"></div>
					</div>

					<!-- Analytics View -->
					{analytics_pane}
				</div>

				<!-- Change Comparison Modal -->
				<div class="modal fade" id="{escape(field.id)}-diff-modal" tabindex="-1" role="dialog">
					<div class="modal-dialog modal-lg" role="document">
						<div class="modal-content">
							<div class="modal-header">
								<h5 class="modal-title">Change Details</h5>
								<button type="button" class="close" data-dismiss="modal"
								        aria-label="Close">
									<span aria-hidden="true">&times;</span>
								</button>
							</div>
							<div class="modal-body">
								<div class="diff-viewer"></div>
							</div>
						</div>
					</div>
				</div>

				<!-- Loading Indicator -->
				<div class="loading-overlay" style="display:none;" role="alert"
				     aria-busy="true">
					<div class="spinner-border text-primary"></div>
					<span class="sr-only">Loading audit logs...</span>
				</div>

				<!-- Error Messages -->
				<div class="alert alert-danger mt-2" style="display:none;"
				     role="alert" aria-live="polite"></div>

				{input_html}
				{error_html}
				{help_html}
			</div>

			<script>
				$(document).ready(function() {{
					const auditLog = new AuditLogViewer({field_id_js}, {{
						trackedFields: {_js_json(self.tracked_fields)},
						retentionDays: {json.dumps(self.retention_days)},
						exportFormats: {_js_json(self.export_formats)},
						showIp: {json.dumps(self.show_ip)},
						trackChanges: {json.dumps(self.track_changes)},
						trackViews: {json.dumps(self.track_views)},
						complianceMode: {json.dumps(self.compliance_mode)},
						pageSize: {json.dumps(self.page_size)},
						updateInterval: {json.dumps(self.update_interval)},
						timezone: {timezone_js},
						dateFormat: {date_format_js},
						fieldLabels: {_js_json(self.field_labels)},
						chartEnabled: {json.dumps(self.chart_enabled)},
						anomalyDetection: {json.dumps(self.anomaly_detection)},
						integrityCheck: {json.dumps(self.integrity_check)},

						onError: function(error) {{
							showError(error);
						}},
						onLoading: function(loading) {{
							toggleLoading(loading);
						}},
						onDataUpdate: function(data) {{
							$('#' + {field_id_js}).val(JSON.stringify(data));
						}}
					}});

					// Error handling
					function showError(error) {{
						const $alert = $('.audit-log-viewer .alert');
						$alert.text(error).show();
						setTimeout(() => $alert.fadeOut(), 5000);
					}}

					// Loading state
					function toggleLoading(show) {{
						$('.loading-overlay')[show ? 'show' : 'hide']();
					}}

					// Initialize if data exists
					const existingData = $('#' + {field_id_js}).val();
					if (existingData) {{
						auditLog.loadData(JSON.parse(existingData));
					}}

					// Handle window resize
					$(window).on('resize', _.debounce(function() {{
						auditLog.handleResize();
					}}, 250));

					// Cleanup on unload
					$(window).on('unload', function() {{
						auditLog.cleanup();
					}});
				}});
			</script>
		"""
		)

	def _include_dependencies(self):
		"""Include required JavaScript and CSS dependencies."""
		js_includes = "\n".join(
			[f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
		)
		css_includes = "\n".join(
			[f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
		)
		return f"{css_includes}\n{js_includes}"

	def _render_export_buttons(self, field_id):
		"""Render export format buttons."""
		items = "".join(
			f'<a class="dropdown-item" href="#" data-export="{escape(fmt)}">'
			f"Export to {escape(fmt.upper())}</a>"
			for fmt in self.export_formats
		)
		return Markup(
			f'<div class="btn-group">'
			f'<button type="button" class="btn btn-secondary dropdown-toggle"'
			f' data-toggle="dropdown" aria-label="Export Options">'
			f'<i class="fa fa-download"></i> Export</button>'
			f'<div class="dropdown-menu dropdown-menu-right">{items}</div>'
			f"</div>"
		)

	def process_formdata(self, valuelist):
		"""Process form data and validate."""
		if valuelist:
			try:
				data = json.loads(valuelist[0])
				self._validate_audit_data(data)
				self.data = data
			except json.JSONDecodeError as e:
				raise ValueError("Invalid audit log data format") from e
			except ValueError as e:
				raise ValueError(str(e))
		else:
			self.data = None

	def _validate_audit_data(self, data):
		"""Validate audit log data structure and content."""
		if not isinstance(data, dict):
			raise ValueError("Invalid audit log data structure")

		required_keys = ["logs", "metadata"]
		if not all(key in data for key in required_keys):
			raise ValueError("Missing required audit log data keys")

		# Validate individual log entries
		for log in data["logs"]:
			if not all(k in log for k in ["timestamp", "user", "action", "details"]):
				raise ValueError("Invalid log entry structure")

			# Validate timestamp
			try:
				datetime.fromisoformat(log["timestamp"])
			except ValueError:
				raise ValueError("Invalid timestamp format")

			# Validate action type
			valid_actions = ["create", "update", "delete", "view"]
			if log["action"] not in valid_actions:
				raise ValueError(f"Invalid action type: {log['action']}")

	def pre_validate(self, form):
		"""Validate before form processing."""
		if self.data is not None:
			try:
				self._validate_audit_data(self.data)
			except ValueError as e:
				raise ValueError(str(e))
