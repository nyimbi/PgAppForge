"""WorkflowDiagramWidget — PgAppForge widget(s)."""

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

class WorkflowDiagramWidget(BS3TextFieldWidget):
    """
    Interactive workflow diagram widget for visualizing and managing business processes.
    Uses JointJS for diagram manipulation and Socket.io for real-time collaboration.
    Stores workflow data as JSONB in PostgreSQL.

    Features:
    - Drag-and-drop editing with touch support
    - Multiple node types with custom styling
    - Smart connectors with validation
    - Conditional flows with expressions
    - Nested subprocess support
    - Full state management with undo/redo
    - Version control with diff view
    - Multiple export formats
    - Template library with categories
    - Validation rules engine
    - Real-time collaboration
    - Mobile-responsive design
    - Search and filtering
    - Usage analytics
    - Accessibility support
    - Auto-save

    Node Types:
    - Start/End: Beginning and end points
    - Task/Activity: Work items
    - Decision: Conditional branching
    - Subprocess: Nested workflows
    - Event: Triggers and catches
    - Gateway: Flow control
    - Timer: Time-based triggers
    - Message: Communication points

    Database Type:
        PostgreSQL: JSONB for storing workflow data and version history
        SQLAlchemy: JSON type with schema validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47

    Required Permissions:
    - LocalStorage for undo/redo
    - WebSocket for collaboration
    - File system for exports

    Performance Considerations:
    - Lazy loading of subprocesses
    - Throttled auto-save
    - Web worker for validation
    - SVG optimization
    - Memory management

    Security Implications:
    - Input sanitization
    - Expression validation
    - CORS configuration
    - WebSocket authentication
    - Export validation

    Best Practices:
    - Enable auto-save
    - Set reasonable subprocess depth
    - Configure validation rules
    - Use templates for consistency
    - Implement error handling
    - Monitor analytics

    Troubleshooting:
    - Check browser console
    - Verify WebSocket connection
    - Validate JSON schema
    - Check localStorage quota
    - Monitor memory usage
    - Review error logs

    Required Dependencies:
    - JointJS/GoJS for diagram rendering
    - Socket.io for collaboration
    - SVG.js for export
    - Lodash for utilities
    - Day.js for timing

    Example:
        workflow = StringField('Process Flow',
                             widget=WorkflowDiagramWidget(
                                 editable=True,
                                 node_types=['task', 'decision', 'event'],
                                 templates=True,
                                 validation=True,
                                 auto_save=True,
                                 collaboration=True
                             ))
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.5.5/joint.min.js",
        "https://cdn.socket.io/4.5.0/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/svg.js/3.1.1/svg.min.js",
        "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js",
        "https://cdn.jsdelivr.net/npm/dayjs@1.11.5/dayjs.min.js",
        "/static/js/workflow-diagram.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.5.5/joint.min.css",
        "/static/css/workflow-diagram.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize WorkflowDiagramWidget with custom settings.

        Args:
            editable (bool): Enable editing (default: True)
            node_types (list): Available node types (default: ['task', 'decision', 'event'])
            templates (bool): Enable template library (default: True)
            validation (bool): Enable validation rules (default: True)
            collaboration (bool): Enable real-time collaboration (default: False)
            auto_layout (bool): Enable automatic layout (default: True)
            custom_nodes (dict): Custom node definitions (default: {})
            version_control (bool): Enable version tracking (default: False)
            export_formats (list): Available export formats (default: ['svg', 'png'])
            subprocess_depth (int): Maximum subprocess nesting (default: 3)
            auto_save (bool): Enable auto-save (default: True)
            save_interval (int): Auto-save interval in ms (default: 30000)
            undo_levels (int): Maximum undo history (default: 50)
            validation_rules (dict): Custom validation rules
            collaboration_server (str): WebSocket server URL
            analytics_enabled (bool): Enable usage analytics
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.editable = kwargs.get("editable", True)
        self.node_types = kwargs.get("node_types", ["task", "decision", "event"])
        self.templates = kwargs.get("templates", True)
        self.validation = kwargs.get("validation", True)
        self.collaboration = kwargs.get("collaboration", False)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.custom_nodes = kwargs.get("custom_nodes", {})
        self.version_control = kwargs.get("version_control", False)
        self.export_formats = kwargs.get("export_formats", ["svg", "png"])
        self.subprocess_depth = kwargs.get("subprocess_depth", 3)

        # Advanced Settings
        self.auto_save = kwargs.get("auto_save", True)
        self.save_interval = max(5000, kwargs.get("save_interval", 30000))
        self.undo_levels = min(100, max(10, kwargs.get("undo_levels", 50)))
        self.validation_rules = kwargs.get("validation_rules", {})
        self.collaboration_server = kwargs.get("collaboration_server", None)
        self.analytics_enabled = kwargs.get("analytics_enabled", False)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._graph = None
        self._socket = None
        self._undo_stack = []
        self._redo_stack = []
        self._auto_save_timer = None
        self._last_saved = None

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the workflow diagram widget with controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="workflow-diagram-widget" id="{field.id}-container">
                <!-- Toolbar -->
                <div class="editor-toolbar" role="toolbar" aria-label="Workflow Editor Tools">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Main Diagram Area -->
                <div class="diagram-area">
                    <div id="{field.id}-paper" class="workflow-paper"
                         role="application" aria-label="Workflow Diagram"></div>

                    <!-- Diagram Controls -->
                    <div class="diagram-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In" aria-label="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out" aria-label="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom" aria-label="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Node Palette -->
                <div class="node-palette" role="region" aria-label="Node Types">
                    {self._render_node_palette(field.id)}
                </div>

                <!-- Properties Panel -->
                <div class="properties-panel" style="display:none;"
                     role="complementary" aria-label="Node Properties">
                    <div class="panel-header">
                        <h3 class="node-name"></h3>
                        <button class="close" aria-label="Close">&times;</button>
                    </div>
                    <div class="panel-content"></div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;" role="alert">
                    <div class="spinner"></div>
                    <span>Loading workflow...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"
                     role="alert" aria-live="polite"></div>

                <!-- Templates -->
                {self._render_templates(field.id) if self.templates else ''}

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const workflow = new WorkflowDiagram('{field.id}', {{
                        editable: {str(self.editable).lower()},
                        nodeTypes: {_js_json(self.node_types)},
                        templates: {str(self.templates).lower()},
                        validation: {str(self.validation).lower()},
                        collaboration: {str(self.collaboration).lower()},
                        autoLayout: {str(self.auto_layout).lower()},
                        customNodes: {_js_json(self.custom_nodes)},
                        versionControl: {str(self.version_control).lower()},
                        exportFormats: {_js_json(self.export_formats)},
                        subprocessDepth: {self.subprocess_depth},
                        autoSave: {str(self.auto_save).lower()},
                        saveInterval: {self.save_interval},
                        undoLevels: {self.undo_levels},
                        validationRules: {_js_json(self.validation_rules)},
                        collaborationServer: {_js_json(self.collaboration_server)},
                        analyticsEnabled: {str(self.analytics_enabled).lower()},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                            updateUndoRedo(data);
                        }},
                        onSave: function(success) {{
                            updateSaveStatus(success);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.workflow-diagram-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function updateUndoRedo(data) {{
                        $('#{field.id}-undo').prop('disabled', !data.canUndo);
                        $('#{field.id}-redo').prop('disabled', !data.canRedo);
                    }}

                    function updateSaveStatus(success) {{
                        const icon = $('#{field.id}-save i');
                        icon.removeClass('fa-save fa-check fa-times')
                            .addClass(success ? 'fa-check' : 'fa-times');
                        setTimeout(() => icon.addClass('fa-save')
                            .removeClass('fa-check fa-times'), 2000);
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        workflow.loadDiagram(JSON.parse(existingData));
                    }}

                    // Setup collaboration if enabled
                    if ({str(self.collaboration).lower()}) {{
                        workflow.initializeCollaboration();
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        workflow.cleanup();
                    }});

                    // Handle responsiveness
                    window.addEventListener('resize', _.debounce(function() {{
                        workflow.resize();
                    }}, 250));
                }});
            </script>
        """
        )

    def _validate_config(self):
        """Validate widget configuration settings"""
        # Validate node types
        valid_nodes = [
            "start",
            "end",
            "task",
            "decision",
            "subprocess",
            "event",
            "gateway",
            "timer",
            "message",
        ]
        invalid_nodes = [n for n in self.node_types if n not in valid_nodes]
        if invalid_nodes:
            raise ValueError(f"Invalid node types: {', '.join(invalid_nodes)}")

        # Validate export formats
        valid_formats = ["svg", "png", "pdf", "json"]
        invalid_formats = [f for f in self.export_formats if f not in valid_formats]
        if invalid_formats:
            raise ValueError(f"Invalid export formats: {', '.join(invalid_formats)}")

        # Validate subprocess depth
        if not 1 <= self.subprocess_depth <= 10:
            raise ValueError("subprocess_depth must be between 1 and 10")

        # Validate collaboration settings
        if self.collaboration and not self.collaboration_server:
            raise ValueError(
                "collaboration_server required when collaboration is enabled"
            )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        css_includes = [
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        ]
        return "\n".join(css_includes + js_includes)

    def cleanup(self):
        """Clean up resources and connections"""
        try:
            if self._socket:
                self._socket.disconnect()
                self._socket = None

            if self._auto_save_timer:
                clearTimeout(self._auto_save_timer)
                self._auto_save_timer = None

            self._graph = None
            self._undo_stack = []
            self._redo_stack = []

        except Exception as e:
            if self.debug_mode:
                raise
