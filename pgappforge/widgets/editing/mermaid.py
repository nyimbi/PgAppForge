"""MermaidEditorWidget — PgAppForge widget(s)."""

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

class MermaidEditorWidget(BS3TextFieldWidget):
    """
    Interactive Mermaid diagram editor and renderer with live preview.

    Features:
    - Syntax highlighting with Monaco Editor
    - Live diagram preview with auto-refresh
    - Multiple diagram types (flowchart, sequence, class, ERD, etc.)
    - Theme customization (light/dark)
    - Export to SVG, PNG, PDF
    - Local version history
    - Template library with common patterns
    - Real-time collaboration support
    - Interactive pan/zoom controls
    - Responsive mobile layout
    - ARIA accessibility support
    - Custom CSS styling
    - Real-time error highlighting
    - Auto diagram layout
    - Reusable code snippets

    Supported Diagrams:
    - Flowchart
    - Sequence Diagram
    - Class Diagram
    - Entity Relationship Diagram
    - State Diagram
    - Gantt Chart
    - Pie Chart
    - User Journey
    - Git Graph
    - Requirement Diagram

    Database Type:
        PostgreSQL: JSONB for storing diagram content and metadata
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - Mermaid.js >= 9.3.0
    - Monaco Editor >= 0.33.0
    - html-to-image >= 1.11.0
    - Socket.IO >= 4.5.0 (collaboration)
    - pako >= 2.1.0 (compression)

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47

    Required Permissions:
    - LocalStorage (preferences)
    - IndexedDB (version history)
    - WebSocket (collaboration)
    - Clipboard (export)
    - File system (import/export)

    Performance Considerations:
    - Use worker threads for rendering
    - Cache rendered diagrams
    - Debounce preview updates
    - Compress diagram storage
    - Lazy load templates
    - Optimize large diagrams
    - Memory cleanup

    Security:
    - Validate diagram input
    - Sanitize custom styles
    - Rate limit operations
    - Scope localStorage
    - Secure WebSocket
    - XSS prevention

    Example:
        mermaid_editor = db.Column(db.JSON,
            info={'widget': MermaidEditorWidget(
                theme='default',
                live_preview=True,
                export_formats=['svg', 'png'],
                templates=True,
                collaboration=False
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/mermaid@9.3.0/dist/mermaid.min.js",
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/loader.js",
        "https://cdn.jsdelivr.net/npm/html-to-image@1.11.0/dist/html-to-image.min.js",
        "https://cdn.jsdelivr.net/npm/socket.io-client@4.5.0/dist/socket.io.min.js",
        "https://cdn.jsdelivr.net/npm/pako@2.1.0/dist/pako.min.js",
        "/static/js/mermaid-editor.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/mermaid@9.3.0/dist/mermaid.min.css",
        "/static/css/mermaid-editor.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize MermaidEditorWidget with custom settings.

        Args:
            theme (str): Editor theme ('default', 'dark', 'forest', 'neutral')
            live_preview (bool): Enable live preview updates
            export_formats (list): Available export formats
            templates (bool): Enable template library
            auto_layout (bool): Enable automatic layout optimization
            pan_zoom (bool): Enable diagram pan/zoom controls
            custom_styles (dict): Custom CSS style definitions
            sequence_numbering (bool): Enable sequence diagram numbering
            flowchart_direction (str): Default flowchart direction
            collaboration (bool): Enable real-time collaboration
            cache_diagrams (bool): Enable diagram caching
            max_diagram_size (int): Maximum diagram size in bytes
            worker_threads (int): Number of rendering worker threads
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.theme = kwargs.get("theme", "default")
        self.live_preview = kwargs.get("live_preview", True)
        self.export_formats = kwargs.get("export_formats", ["svg", "png"])
        self.templates = kwargs.get("templates", True)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.pan_zoom = kwargs.get("pan_zoom", True)
        self.custom_styles = kwargs.get("custom_styles", {})
        self.sequence_numbering = kwargs.get("sequence_numbering", False)
        self.flowchart_direction = kwargs.get("flowchart_direction", "TB")

        # Advanced Features
        self.collaboration = kwargs.get("collaboration", False)
        self.cache_diagrams = kwargs.get("cache_diagrams", True)
        self.max_diagram_size = kwargs.get("max_diagram_size", 1024 * 1024)  # 1MB
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.debug_mode = kwargs.get("debug_mode", False)

        # Internal State
        self._initialize_mermaid()
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the Mermaid editor widget with controls and preview"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="mermaid-editor-widget" id="{field.id}-container">
                <!-- Editor Panel -->
                <div class="editor-panel">
                    <div id="{field.id}-editor" class="monaco-editor"></div>
                </div>

                <!-- Preview Panel -->
                <div class="preview-panel">
                    <div id="{field.id}-preview" class="mermaid-preview"></div>
                    <div class="preview-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="editor-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Status Bar -->
                <div class="status-bar">
                    <span class="error-count"></span>
                    <span class="cursor-position"></span>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Rendering diagram...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const editor = new MermaidEditor('{field.id}', {{
                        theme: '{self.theme}',
                        livePreview: {str(self.live_preview).lower()},
                        exportFormats: {_js_json(self.export_formats)},
                        templates: {str(self.templates).lower()},
                        autoLayout: {str(self.auto_layout).lower()},
                        panZoom: {str(self.pan_zoom).lower()},
                        customStyles: {_js_json(self.custom_styles)},
                        sequenceNumbering: {str(self.sequence_numbering).lower()},
                        flowchartDirection: '{self.flowchart_direction}',
                        collaboration: {str(self.collaboration).lower()},
                        cacheDiagrams: {str(self.cache_diagrams).lower()},
                        maxDiagramSize: {self.max_diagram_size},
                        workerThreads: {self.worker_threads},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(content) {{
                            $('#{field.id}').val(content);
                            validateDiagram(content);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.mermaid-editor-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    function validateDiagram(content) {{
                        if (content.length > {self.max_diagram_size}) {{
                            showError('Diagram size exceeds maximum allowed');
                            return false;
                        }}
                        return editor.validateDiagram(content);
                    }}

                    // Initialize with existing diagram
                    const existingDiagram = $('#{field.id}').val();
                    if (existingDiagram) {{
                        editor.setContent(existingDiagram);
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        editor.cleanup();
                    }});
                }});
            </script>
        """
        )

    def render_diagram(self, content: str, format: str = "svg") -> str:
        """
        Render Mermaid diagram to specified format.

        Args:
            content (str): Mermaid diagram content
            format (str): Output format (svg, png, pdf)

        Returns:
            str: Rendered diagram in specified format

        Raises:
            ValueError: If format is unsupported or content is invalid
            RuntimeError: If rendering fails
        """
        try:
            if not content:
                raise ValueError("Empty diagram content")

            if format not in self.export_formats:
                raise ValueError(f"Unsupported format: {format}")

            # Validate syntax before rendering
            errors = self._validate_syntax(content)
            if errors:
                raise ValueError(f"Invalid diagram syntax: {errors}")

            # Apply theme and optimize layout
            content = self._apply_theme(self._optimize_layout(content))

            # Render using appropriate method
            if format == "svg":
                return self._render_svg(content)
            elif format == "png":
                return self._render_png(content)
            elif format == "pdf":
                return self._render_pdf(content)

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Error rendering diagram: {str(e)}"

    def _validate_syntax(self, content: str) -> list:
        """
        Validate Mermaid diagram syntax.

        Returns:
            list: List of validation errors, empty if valid
        """
        try:
            # Basic structure validation
            if not content.strip():
                return ["Empty diagram"]

            # Check for required keywords based on type
            diagram_type = content.split()[0].lower()
            required_keywords = {
                "graph": ["-->"],
                "sequenceDiagram": ["->"],
                "classDiagram": ["class"],
                "erDiagram": ["||"],
                "stateDiagram": ["state"],
                "gantt": ["section"],
                "pie": ["title"],
                "journey": ["section"],
            }

            if diagram_type not in required_keywords:
                return [f"Unsupported diagram type: {diagram_type}"]

            keywords = required_keywords[diagram_type]
            if not any(k in content for k in keywords):
                return [f"Missing required keywords for {diagram_type}"]

            return []

        except Exception as e:
            return [f"Syntax validation error: {str(e)}"]

    def _optimize_layout(self, content: str) -> str:
        """
        Optimize diagram layout for better readability.

        Returns:
            str: Optimized diagram content
        """
        try:
            if not self.auto_layout:
                return content

            # Add proper spacing
            content = re.sub(r"\s+", " ", content)

            # Align arrows and relationships
            content = re.sub(r"(-->|->|\|\|)", r" \1 ", content)

            # Add line breaks for readability
            content = re.sub(r"([{};])", r"\1\n", content)

            return content

        except Exception:
            return content  # Return original if optimization fails

    def _apply_theme(self, content: str) -> str:
        """
        Apply theme styling to diagram.

        Returns:
            str: Themed diagram content
        """
        try:
            theme_config = {
                "default": {"background": "#ffffff", "fontFamily": "arial"},
                "dark": {
                    "background": "#2b2b2b",
                    "fontFamily": "arial",
                    "primaryColor": "#6eaa6e",
                },
                "forest": {
                    "background": "#f8f9fa",
                    "fontFamily": "courier",
                    "primaryColor": "#185619",
                },
                "neutral": {"background": "#f5f5f5", "fontFamily": "helvetica"},
            }

            config = theme_config.get(self.theme, theme_config["default"])

            # Apply theme config
            themed_content = f"""
                %%{_js_json(config)}%%
                {content}
            """

            # Apply custom styles if defined
            if self.custom_styles:
                themed_content = f"""
                    %%{_js_json(self.custom_styles)}%%
                    {themed_content}
                """

            return themed_content.strip()

        except Exception:
            return content  # Return original if theming fails

    def _generate_preview(self, content: str) -> str:
        """
        Generate preview of diagram for display.

        Returns:
            str: HTML preview of diagram
        """
        try:
            # Generate optimized SVG for preview
            preview_svg = self.render_diagram(content, "svg")

            # Add preview container with controls
            preview_html = f"""
                <div class="diagram-preview" role="img"
                     aria-label="Diagram preview">
                    {preview_svg}
                </div>
            """

            return preview_html

        except Exception as e:
            return (
                f'<div class="preview-error">Preview generation failed: {str(e)}</div>'
            )

    def _initialize_mermaid(self):
        """Initialize Mermaid.js configuration"""
        mermaid_config = {
            "theme": self.theme,
            "securityLevel": "strict",
            "startOnLoad": True,
            "flowchart": {
                "htmlLabels": True,
                "curve": "basis",
                "defaultRenderer": "dagre",
            },
            "sequence": {
                "showSequenceNumbers": self.sequence_numbering,
                "actorFontSize": 14,
                "noteFontSize": 14,
            },
            "gantt": {"titleTopMargin": 25, "barHeight": 20, "barGap": 4},
        }

        # Initialize Mermaid with config
        init_script = f"""
            mermaid.initialize({_js_json(mermaid_config)});
        """

        return Markup(init_script)

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES
        )
        css_includes = "\n".join(
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        )
        return f"{css_includes}\n{js_includes}"

    def _render_toolbar(self, field_id):
        """Render editor toolbar with controls"""
        return f"""
            <div class="btn-group">
                <button type="button" class="btn btn-default"
                        id="{field_id}-export" title="Export Diagram">
                    <i class="fa fa-download"></i>
                </button>
                <button type="button" class="btn btn-default"
                        id="{field_id}-copy" title="Copy as SVG">
                    <i class="fa fa-copy"></i>
                </button>
                {self._render_template_dropdown(field_id) if self.templates else ''}
                <button type="button" class="btn btn-default"
                        id="{field_id}-format" title="Format Code">
                    <i class="fa fa-align-left"></i>
                </button>
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration settings"""
        valid_themes = ["default", "dark", "forest", "neutral"]
        if self.theme not in valid_themes:
            raise ValueError(
                f"Invalid theme. Must be one of: {', '.join(valid_themes)}"
            )

        if not isinstance(self.export_formats, list):
            raise ValueError("export_formats must be a list")

        valid_formats = ["svg", "png", "pdf"]
        invalid_formats = [
            fmt for fmt in self.export_formats if fmt not in valid_formats
        ]
        if invalid_formats:
            raise ValueError(f"Invalid export formats: {', '.join(invalid_formats)}")

        if self.worker_threads < 1 or self.worker_threads > 16:
            raise ValueError("worker_threads must be between 1 and 16")
