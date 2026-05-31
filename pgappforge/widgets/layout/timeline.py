"""ActivityTimelineWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class ActivityTimelineWidget(BS3TextFieldWidget):
    """
    Chronological timeline widget for displaying activity history and events from tables with AuditMixin.
    Supports real-time updates, filtering, grouping and rich interactions.

    Features:
    - Multiple event types with custom icons and colors
    - Customizable timeline styles and layouts
    - Advanced filtering by date, type, user etc.
    - Flexible grouping by day/week/month/year
    - Rich content with markdown and attachments
    - Infinite scroll with lazy loading
    - Real-time updates via WebSocket
    - Interactive event details modal
    - Full-text search capabilities
    - Export to PDF/CSV/Excel
    - Date range picker integration
    - Custom event icons and badges
    - Nested child timelines
    - File attachments and previews
    - Threaded comments and reactions

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON
        Audit Table: Created via AuditMixin

    Required Dependencies:
    - Timeline.js 3.6+
    - Moment.js 2.29+
    - Socket.io 4.0+
    - Markdown-it 12.0+
    - Vue.js 2.6+
    - Axios 0.21+

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
    - LocalStorage access
    - File downloads for exports
    - Camera/mic for attachments

    Performance Considerations:
    - Enable pagination/infinite scroll
    - Limit initial load size
    - Optimize attachment previews
    - Cache common queries
    - Use WebSocket heartbeats
    - Compress payloads
    - Lazy load media
    - Throttle real-time updates

    Security Implications:
    - Validate WebSocket origin
    - Sanitize markdown content
    - Verify file uploads
    - Rate limit API calls
    - Implement CSRF protection
    - Control access permissions
    - Audit sensitive actions
    - Encrypt attachments

    Example:
        activity_log = db.Column(db.JSON, nullable=False,
            info={'widget': ActivityTimelineWidget(
                event_types=['create', 'update', 'delete', 'comment'],
                real_time=True,
                group_by='day',
                enable_comments=True,
                items_per_page=50,
                enable_export=True
            )})
    """

    # JavaScript/CSS Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/timeline.js/3.6.6/js/timeline.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/markdown-it/12.0.6/markdown-it.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/vue/2.6.14/vue.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/axios/0.21.1/axios.min.js",
        "/static/js/activity-timeline.js",
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/timeline.js/3.6.6/css/timeline.min.css",
        "/static/css/activity-timeline.css",
    ]

    # Default event type configurations
    DEFAULT_EVENT_TYPES = {
        "create": {"icon": "fa-plus-circle", "color": "#28a745"},
        "update": {"icon": "fa-edit", "color": "#007bff"},
        "delete": {"icon": "fa-trash", "color": "#dc3545"},
        "comment": {"icon": "fa-comment", "color": "#6c757d"},
    }

    # Default grouping options
    GROUP_BY_OPTIONS = ["hour", "day", "week", "month", "year"]

    def __init__(self, **kwargs):
        """
        Initialize ActivityTimelineWidget with custom settings.

        Args:
            event_types (list): Available event types with icons/colors
            real_time (bool): Enable real-time updates via WebSocket
            group_by (str): Grouping method (hour/day/week/month/year)
            enable_comments (bool): Enable comment threading
            items_per_page (int): Items to load per page
            sort_order (str): Timeline sort order (asc/desc)
            filters (list): Available filter options
            enable_export (bool): Enable export functionality
            enable_search (bool): Enable search functionality
            max_attachments (int): Maximum attachments per event
            max_file_size (int): Maximum attachment size in bytes
            websocket_url (str): Custom WebSocket endpoint
            cache_ttl (int): Cache TTL in seconds
            locale (str): Interface language
        """
        super().__init__(**kwargs)

        self.event_types = {**self.DEFAULT_EVENT_TYPES, **kwargs.get("event_types", {})}
        self.real_time = kwargs.get("real_time", True)
        self.group_by = kwargs.get("group_by", "day")
        self.enable_comments = kwargs.get("enable_comments", True)
        self.items_per_page = kwargs.get("items_per_page", 50)
        self.sort_order = kwargs.get("sort_order", "desc")
        self.filters = kwargs.get("filters", ["type", "user", "date"])
        self.enable_export = kwargs.get("enable_export", True)
        self.enable_search = kwargs.get("enable_search", True)
        self.max_attachments = kwargs.get("max_attachments", 5)
        self.max_file_size = kwargs.get("max_file_size", 5 * 1024 * 1024)
        self.websocket_url = kwargs.get("websocket_url", "/timeline/ws")
        self.cache_ttl = kwargs.get("cache_ttl", 300)
        self.locale = kwargs.get("locale", "en")

    def render_field(self, field, **kwargs):
        """Render the timeline widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="activity-timeline-widget" role="complementary"
                 aria-label="Activity Timeline">

                <!-- Controls -->
                <div class="timeline-controls" role="toolbar"
                     aria-label="Timeline Controls">
                    <div class="btn-group">
                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-refresh" aria-label="Refresh Timeline">
                            <i class="fa fa-sync"></i>
                        </button>
                        <button type="button" class="btn btn-secondary"
                                id="{field.id}-filter" aria-label="Filter Timeline">
                            <i class="fa fa-filter"></i>
                        </button>
                        {f'''
                        <button type="button" class="btn btn-secondary dropdown-toggle"
                                data-toggle="dropdown" aria-label="Export Options">
                            <i class="fa fa-download"></i>
                        </button>
                        <div class="dropdown-menu">
                            <a class="dropdown-item" href="#" data-export="pdf">
                                Export as PDF
                            </a>
                            <a class="dropdown-item" href="#" data-export="csv">
                                Export as CSV
                            </a>
                            <a class="dropdown-item" href="#" data-export="excel">
                                Export as Excel
                            </a>
                        </div>
                        ''' if self.enable_export else ''}
                    </div>

                    {f'''
                    <div class="search-box ml-2">
                        <input type="text" class="form-control"
                               id="{field.id}-search"
                               placeholder="Search timeline..."
                               aria-label="Search timeline">
                    </div>
                    ''' if self.enable_search else ''}

                    <div class="date-range ml-2">
                        <input type="text" class="form-control"
                               id="{field.id}-daterange"
                               aria-label="Date range">
                    </div>

                    <select class="custom-select ml-2" id="{field.id}-grouping"
                            aria-label="Group by">
                        {self._render_group_options()}
                    </select>
                </div>

                <!-- Timeline View -->
                <div class="timeline-container mt-3" id="{field.id}-timeline"></div>

                <!-- Loading Indicator -->
                <div class="timeline-loading" style="display:none;" role="status">
                    <div class="spinner-border text-primary"></div>
                    <span class="sr-only">Loading timeline...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger mt-2" style="display:none"
                     role="alert" aria-live="polite"></div>

                <!-- Event Details Modal -->
                <div class="modal fade" id="{field.id}-event-modal" tabindex="-1"
                     role="dialog">
                    <div class="modal-dialog" role="document">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Event Details</h5>
                                <button type="button" class="close" data-dismiss="modal"
                                        aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div class="modal-body"></div>
                        </div>
                    </div>
                </div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const timeline = new ActivityTimeline('{field.id}', {{
                        eventTypes: {_js_json(self.event_types)},
                        realTime: {str(self.real_time).lower()},
                        groupBy: '{self.group_by}',
                        enableComments: {str(self.enable_comments).lower()},
                        itemsPerPage: {self.items_per_page},
                        sortOrder: '{self.sort_order}',
                        filters: {_js_json(self.filters)},
                        enableExport: {str(self.enable_export).lower()},
                        enableSearch: {str(self.enable_search).lower()},
                        maxAttachments: {self.max_attachments},
                        maxFileSize: {self.max_file_size},
                        websocketUrl: '{self.websocket_url}',
                        cacheTTL: {self.cache_ttl},
                        locale: '{self.locale}',

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onUpdate: function(data) {{
                            handleUpdate(data);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.activity-timeline-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.timeline-loading')[show ? 'show' : 'hide']();
                    }}

                    // Update handler
                    function handleUpdate(data) {{
                        $('#{field.id}').val(JSON.stringify(data));
                    }}

                    // Initialize timeline if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        timeline.loadData(JSON.parse(existingData));
                    }}

                    // Responsive handlers
                    $(window).on('resize', function() {{
                        timeline.handleResize();
                    }});

                    // Cleanup
                    $(window).on('unload', function() {{
                        timeline.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )

        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )

        return f"{css_includes}\n{js_includes}"

    def _render_group_options(self):
        """Render grouping dropdown options"""
        options = []
        for group in self.GROUP_BY_OPTIONS:
            selected = "selected" if group == self.group_by else ""
            options.append(
                f'<option value="{group}" {selected}>' f"{group.capitalize()}</option>"
            )
        return "\n".join(options)

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_timeline_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid timeline data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_timeline_data(self, data):
        """Validate timeline data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid timeline data structure")

        required_keys = ["events", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required timeline data keys")

        # Validate events
        if not isinstance(data["events"], list):
            raise ValueError("Events must be a list")

        for event in data["events"]:
            if not isinstance(event, dict):
                raise ValueError("Invalid event structure")

            required_event_keys = ["id", "type", "timestamp", "user"]
            if not all(key in event for key in required_event_keys):
                raise ValueError("Missing required event keys")

            if event["type"] not in self.event_types:
                raise ValueError(f'Invalid event type: {event["type"]}')

    def pre_validate(self, form):
        """Validate timeline data before form processing"""
        if self.data is not None:
            try:
                self._validate_timeline_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))
