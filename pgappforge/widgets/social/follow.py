"""FriendFollowWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape
from wtforms.validators import ValidationError


def _js_str(v: Any) -> str:
	"""Emit a Python value as a safe JS string literal via json.dumps."""
	return json.dumps(str(v))


class FriendFollowWidget(BS3TextFieldWidget):
	"""
	Widget for managing friend/follow relationships and social connections.

	Features:
	- Follow/Unfollow functionality with real-time updates
	- Friend requests with notifications
	- AI-powered connection suggestions
	- Interactive network visualization
	- Granular privacy settings
	- User blocking and reporting
	- Custom group management
	- Real-time activity feed
	- Connection analytics and stats
	- Contact import/export
	- Social network analysis
	- Mutual friend discovery
	- Connection categorization
	- Bulk actions and management
	- Mobile-responsive design
	- Accessibility compliance
	- Offline support
	- Rate limiting
	- Data validation

	Database Type:
		PostgreSQL: JSONB for storing connection data
		SQLAlchemy: JSON type

	Required Dependencies:
	- D3.js v7+ (network visualization)
	- Socket.io v4+ (real-time updates)
	- VIS.js v9+ (network analysis)
	- Lodash v4+ (utilities)
	- Bootstrap v4+ (UI components)

	Browser Support:
	- Chrome 60+
	- Firefox 60+
	- Safari 12+
	- Edge 79+
	- Opera 47+
	- iOS Safari 12+
	- Chrome for Android 89+

	Required Permissions:
	- WebSocket connections
	- LocalStorage/IndexedDB
	- Push notifications
	- Contacts API (optional)

	Performance Considerations:
	- Lazy load network visualization
	- Cache connection data
	- Debounce real-time updates
	- Progressive loading
	- Optimize large networks
	- Monitor memory usage
	- Background processing

	Security Implications:
	- Rate limiting
	- Request validation
	- CSRF protection
	- XSS prevention
	- Data encryption
	- Privacy controls
	- Access management

	Best Practices:
	- Enable caching
	- Add error handling
	- Validate inputs
	- Show loading states
	- Make responsive
	- Track analytics
	- Test thoroughly

	Example:
		connections = db.Column(db.JSON,
			info={'widget': FriendFollowWidget(
				connection_type='friend',
				privacy_enabled=True,
				suggestions=True,
				stats=True,
				max_connections=1000,
				categories=['Family', 'Work', 'School'],
				visualization=True,
				offline_support=True
			)})
	"""

	# JavaScript Dependencies
	JS_DEPENDENCIES = [
		"https://d3js.org/d3.v7.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
		"https://unpkg.com/vis-network/standalone/umd/vis-network.min.js",
		"https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
		"/static/js/friend-follow.js",
	]

	# CSS Dependencies
	CSS_DEPENDENCIES = [
		"https://unpkg.com/vis-network/styles/vis-network.min.css",
		"/static/css/friend-follow.css",
	]

	def __init__(self, **kwargs):
		"""
		Initialize FriendFollowWidget with custom settings.

		Args:
			connection_type (str): Type of connection ('friend', 'follow')
			privacy_enabled (bool): Enable privacy settings
			suggestions (bool): Enable connection suggestions
			stats (bool): Show connection statistics
			max_connections (int): Maximum allowed connections
			categories (list): Connection categories
			import_sources (list): Available import sources
			visualization (bool): Enable network visualization
			offline_support (bool): Enable offline mode
			realtime (bool): Enable real-time updates
			suggestion_algorithm (str): Suggestion algorithm type
			notification_config (dict): Notification settings
			analytics_config (dict): Analytics settings
			rate_limit (dict): Rate limiting configuration
			sync_interval (int): Background sync interval
			cache_duration (int): Cache duration in seconds
			placeholder (str): Input placeholder text
			css_class (str): Additional CSS class(es)
			description (str): Help text displayed below the widget
			readonly (bool): Render widget as read-only
			disabled (bool): Render widget as disabled
		"""
		super().__init__(**kwargs)

		# Core Settings
		self.connection_type = kwargs.get("connection_type", "follow")
		self.privacy_enabled = kwargs.get("privacy_enabled", True)
		self.suggestions = kwargs.get("suggestions", True)
		self.stats = kwargs.get("stats", True)
		self.max_connections = kwargs.get("max_connections", 1000)
		self.categories = kwargs.get("categories", ["Friends", "Family", "Work"])
		self.import_sources = kwargs.get("import_sources", ["csv", "vcard", "social"])
		self.visualization = kwargs.get("visualization", False)

		# Advanced Features
		self.offline_support = kwargs.get("offline_support", True)
		self.realtime = kwargs.get("realtime", True)
		self.suggestion_algorithm = kwargs.get("suggestion_algorithm", "collaborative")

		# Technical Configuration
		self.notification_config = kwargs.get(
			"notification_config", {"email": True, "push": True, "in_app": True}
		)
		self.analytics_config = kwargs.get(
			"analytics_config",
			{
				"track_interactions": True,
				"track_suggestions": True,
				"track_engagement": True,
			},
		)
		self.rate_limit = kwargs.get(
			"rate_limit",
			{
				"requests": {"count": 100, "interval": 3600},
				"connections": {"count": 50, "interval": 86400},
			},
		)
		self.sync_interval = kwargs.get("sync_interval", 300)
		self.cache_duration = kwargs.get("cache_duration", 3600)

		# Universal widget kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def render_field(self, field, **kwargs):
		"""Render the friend/follow widget with all controls."""
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
		connection_type_js = _js_str(self.connection_type)
		suggestion_algorithm_js = _js_str(self.suggestion_algorithm)

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

		return Markup(
			f"""
			{self._include_dependencies()}

			<div class="friend-follow-widget" id="{escape(field.id)}-container">
				<!-- Network Visualization -->
				{self._render_network(field.id) if self.visualization else ''}

				<!-- Connection Management -->
				<div class="connection-manager">
					<div class="tabs">
						<nav class="nav nav-tabs" role="tablist">
							<a class="nav-link active" data-toggle="tab" href="#connections" role="tab">
								Connections <span class="badge badge-primary connection-count"></span>
							</a>
							<a class="nav-link" data-toggle="tab" href="#requests" role="tab">
								Requests <span class="badge badge-warning request-count"></span>
							</a>
							<a class="nav-link" data-toggle="tab" href="#suggestions" role="tab">
								Suggestions
							</a>
						</nav>

						<div class="tab-content">
							<div class="tab-pane fade show active" id="connections" role="tabpanel">
								<div class="connection-list"></div>
								<div class="load-more" style="display:none;">
									<button class="btn btn-link">Load More</button>
								</div>
							</div>

							<div class="tab-pane fade" id="requests" role="tabpanel">
								<div class="request-list"></div>
							</div>

							<div class="tab-pane fade" id="suggestions" role="tabpanel">
								<div class="suggestion-list"></div>
							</div>
						</div>
					</div>
				</div>

				<!-- Connection Stats -->
				{self._render_stats(field.id) if self.stats else ''}

				<!-- Loading States -->
				<div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
					<div class="spinner-border"></div>
					<span class="sr-only">Loading connections...</span>
				</div>

				<!-- Error Messages -->
				<div class="alert alert-danger" style="display:none;" role="alert"></div>

				{input_html}
				{error_html}
				{help_html}
			</div>

			<script>
				$(document).ready(function() {{
					const network = new FriendFollowNetwork({field_id_js}, {{
						connectionType: {connection_type_js},
						privacyEnabled: {json.dumps(self.privacy_enabled)},
						suggestions: {json.dumps(self.suggestions)},
						stats: {json.dumps(self.stats)},
						maxConnections: {json.dumps(self.max_connections)},
						categories: {_js_json(self.categories)},
						importSources: {_js_json(self.import_sources)},
						visualization: {json.dumps(self.visualization)},
						offlineSupport: {json.dumps(self.offline_support)},
						realtime: {json.dumps(self.realtime)},
						suggestionAlgorithm: {suggestion_algorithm_js},
						notificationConfig: {_js_json(self.notification_config)},
						analyticsConfig: {_js_json(self.analytics_config)},
						rateLimit: {_js_json(self.rate_limit)},
						syncInterval: {json.dumps(self.sync_interval)},
						cacheDuration: {json.dumps(self.cache_duration)},

						onError: function(error) {{
							showError(error);
						}},
						onLoading: function(loading) {{
							toggleLoading(loading);
						}},
						onChange: function(data) {{
							$('#' + {field_id_js}).val(JSON.stringify(data));
						}}
					}});

					// Error handling
					function showError(error) {{
						const $alert = $('.friend-follow-widget .alert');
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
						network.loadData(JSON.parse(existingData));
					}}

					// Cleanup on unload
					$(window).on('unload', function() {{
						network.cleanup();
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

	def _render_network(self, field_id):
		"""Render network visualization container."""
		safe_id = escape(field_id)
		return Markup(f"""
			<div class="network-visualization">
				<div id="{safe_id}-network" class="network-container"></div>
				<div class="network-controls">
					<button class="btn btn-sm btn-light zoom-in" aria-label="Zoom in">
						<i class="fa fa-search-plus"></i>
					</button>
					<button class="btn btn-sm btn-light zoom-out" aria-label="Zoom out">
						<i class="fa fa-search-minus"></i>
					</button>
					<button class="btn btn-sm btn-light fit" aria-label="Fit view">
						<i class="fa fa-expand"></i>
					</button>
				</div>
			</div>
		""")

	def _render_stats(self, field_id):
		"""Render connection statistics."""
		safe_id = escape(field_id)
		return Markup(f"""
			<div class="connection-stats">
				<div class="row">
					<div class="col-md-4">
						<div class="stat-card">
							<h6>Total Connections</h6>
							<div class="stat-value" id="{safe_id}-total"></div>
						</div>
					</div>
					<div class="col-md-4">
						<div class="stat-card">
							<h6>Mutual Connections</h6>
							<div class="stat-value" id="{safe_id}-mutual"></div>
						</div>
					</div>
					<div class="col-md-4">
						<div class="stat-card">
							<h6>Growth Rate</h6>
							<div class="stat-value" id="{safe_id}-growth"></div>
						</div>
					</div>
				</div>
			</div>
		""")

	def process_formdata(self, valuelist):
		"""Process form data and validate."""
		if valuelist:
			try:
				data = json.loads(valuelist[0])
				self._validate_connection_data(data)
				self.data = data
			except json.JSONDecodeError:
				raise ValueError("Invalid connection data format")
			except ValueError as e:
				raise ValueError(str(e))
		else:
			self.data = None

	def _validate_connection_data(self, data):
		"""Validate connection data structure and content."""
		if not isinstance(data, dict):
			raise ValueError("Invalid connection data structure")

		required_keys = ["connections", "requests", "metadata"]
		if not all(key in data for key in required_keys):
			raise ValueError("Missing required data keys")

		# Validate connections
		if len(data.get("connections", [])) > self.max_connections:
			raise ValueError(f"Maximum connections ({self.max_connections}) exceeded")

		# Validate individual connections
		for connection in data.get("connections", []):
			if not all(k in connection for k in ["id", "type", "status", "timestamp"]):
				raise ValueError("Invalid connection structure")

	def pre_validate(self, form):
		"""Validate before form processing."""
		if self.data is not None:
			try:
				self._validate_connection_data(self.data)
			except ValueError as e:
				raise ValueError(str(e))
