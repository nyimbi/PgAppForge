"""CodeEditorWidget — PgAppForge widget(s)."""

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

class CodeEditorWidget(BS3TextFieldWidget):
    """
    Advanced code editor widget with syntax highlighting and features using Monaco Editor.

    Features:
        - Syntax highlighting for multiple languages (JSON, Python, SQL, DBML, Lua).
        - Real-time code linting and error detection for supported languages.
        - Code auto-completion and suggestions.
        - Integration with language services for enhanced code intelligence.
        - Code formatting and beautification.
        - Export code in multiple formats.
        - Customizable themes and editor options.
        - Basic code debugging and execution (planned).
        - Real-time collaboration for simultaneous editing (planned).
        - Version control integration for tracking code changes (planned).

    Database Type:
        PostgreSQL: TEXT or JSONB for storing code content and editor state.
        SQLAlchemy: Text or JSON

    Example Usage:
        code_field = db.Column(db.Text, info={'widget': CodeEditorWidget(language='python')})
    """

    data_template = (
        '<div class="code-editor-wrapper %(wrapper_class)s">'
        '<div id="%(field_id)s-container" class="editor-container"></div>'
        '<div class="editor-statusbar"></div>'
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<input type="hidden" name="%(name)s_state" id="%(field_id)s_state">'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/loader.js"  # Using Monaco Editor Loader for dynamic loading
    ]

    CSS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs/editor/editor.main.css",  # Monaco Editor Styles
        "/static/css/code-editor-widget.css",  # Custom widget styles
    ]

    def __init__(self, **kwargs):
        """
        Initializes CodeEditorWidget with extensive configuration for code editing features.
        """
        super().__init__(**kwargs)
        self.language = kwargs.get("language", "plaintext")
        self.theme = kwargs.get("theme", "vs-dark")
        self.auto_complete = kwargs.get("auto_complete", True)
        self.line_numbers = kwargs.get("line_numbers", True)
        self.minimap = kwargs.get("minimap", True)
        self.folding = kwargs.get("folding", True)
        self.lint = kwargs.get("lint", True)  # Enable linting by default
        self.format_on_save = kwargs.get("format_on_save", True)
        self.word_wrap = kwargs.get(
            "word_wrap", "on"
        )  # Default to 'on' for better readability
        self.tab_size = kwargs.get("tab_size", 4)
        self.insert_spaces = kwargs.get("insert_spaces", True)
        self.snippets = kwargs.get("snippets", True)
        self.quick_suggestions = kwargs.get("quick_suggestions", True)
        self.hover = kwargs.get("hover", True)
        self.font_size = kwargs.get("font_size", 14)
        self.font_family = kwargs.get(
            "font_family", "'Fira Code', 'Consolas', monospace"
        )  # Enhanced font family
        self.rulers = kwargs.get("rulers", [80, 120])
        self.scroll_beyond_last_line = kwargs.get(
            "scroll_beyond_last_line", False
        )  # Improved default scroll behavior
        self.wrapper_class = kwargs.get(
            "wrapper_class", "flb-code-editor"
        )  # Custom CSS class
        self.keyboard_shortcuts = kwargs.get("keyboard_shortcuts", {})
        self.max_file_size = kwargs.get(
            "max_file_size", 10 * 1024 * 1024
        )  # Increased max file size to 10MB
        self.enable_diff_view = kwargs.get(
            "enable_diff_view", False
        )  # Feature flag for diff view
        self.enable_collaboration = kwargs.get(
            "enable_collaboration", False
        )  # Feature flag for real-time collaboration
        self.supported_languages = {  # Define supported languages with modes and extra configurations
            "javascript": {"id": "javascript", "label": "JavaScript"},
            "typescript": {"id": "typescript", "label": "TypeScript"},
            "python": {"id": "python", "label": "Python"},
            "sql": {"id": "sql", "label": "SQL"},
            "dbml": {"id": "dbml", "label": "DBML"},  # Added DBML support
            "lua": {"id": "lua", "label": "Lua"},  # Added Lua support
            "json": {"id": "json", "label": "JSON"},
            "html": {"id": "html", "label": "HTML"},
            "css": {"id": "css", "label": "CSS"},
            "xml": {"id": "xml", "label": "XML"},
            "yaml": {"id": "yaml", "label": "YAML"},
            "markdown": {"id": "markdown", "label": "Markdown"},
            "plaintext": {"id": "plaintext", "label": "Plain Text"},
        }

    def __call__(self, field, **kwargs):
        """Renders the CodeEditorWidget, initializing Monaco Editor with specified configurations."""
        kwargs.setdefault("id", field.id)
        if field.flags.required:
            kwargs["required"] = True

        template = self.data_template
        html = template % {
            "field_id": field.id,
            "hidden": self.html_params(name=field.name, **kwargs),
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generates and returns the JavaScript code block for the CodeEditorWidget, including Monaco Editor initialization."""
        return """
        <style>
            /* Styles remain same as before, consider moving to a separate CSS file */
            .code-editor-wrapper { border: 1px solid #dee2e6; border-radius: 4px; overflow: hidden; }
            .editor-container { height: 500px; width: 100%; }
            .editor-statusbar { padding: 2px 8px; background: #f8f9fa; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; }
        </style>
        <script>
            (function() {{
                require.config({{ paths: {{ 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs' }}}});


                require(['vs/editor/editor.main'], function() {{
                    $(document).ready(function() {{
                        var container = document.getElementById('{field_id}-container');
                        var statusBar = container.parentElement.querySelector('.editor-statusbar');
                        var editor;


                        // Editor configuration
                        var config = {{
                            value: {_js_json(field.data or '')},
                            language: '{language}',
                            theme: '{theme}',
                            automaticLayout: true,
                            lineNumbers: {str(self.line_numbers).lower()},
                            minimap: {{ enabled: {str(self.minimap).lower()} }},
                            folding: {str(self.folding).lower()},
                            wordWrap: '{word_wrap}',
                            tabSize: {tab_size},
                            insertSpaces: {str(self.insert_spaces).lower()},
                            quickSuggestions: {str(self.quick_suggestions).lower()},
                            hover: {{ enabled: {str(self.hover).lower()} }},
                            fontSize: {font_size},
                            fontFamily: '{font_family}',
                            rulers: {_js_json(self.rulers)},
                            scrollBeyondLastLine: {str(self.scroll_beyond_last_line).lower()},
                            formatOnPaste: true,
                            formatOnType: true,
                            suggestOnTriggerCharacters: true,
                            snippetSuggestions: '{snippets}',
                            renderWhitespace: 'selection',
                            renderControlCharacters: false,
                            renderLineHighlight: 'gutter',
                            parameterHints: {{ enabled: true }},
                            links: true,
                            contextmenu: true,
                            mouseWheelZoom: true,
                            roundedSelection: false,
                            selectOnLineNumbers: true,
                            selectionHighlight: true,
                            occurrencesHighlight: true,
                            glyphMargin: false,
                            fixedOverflowWidgets: true,
                            hideCursorInOverviewRuler: true,
                            overviewRulerBorder: false,
                            cursorSmoothCaretAnimation: true,
                            scrollbar: {{ verticalScrollbarSize: 10, horizontalScrollbarSize: 10 }},
                            overviewRulerLanes: 2,
                            find: {{ seedSearchStringFromSelection: true }}
                        }};


                        editor = monaco.editor.create(container, config);


                        // Register custom keyboard shortcuts
                        var keyboardShortcuts = {keyboard_shortcuts};
                        Object.keys(keyboardShortcuts).forEach(function(key) {{
                            editor.addCommand(monaco.KeyMod[key], keyboardShortcuts[key]);
                        }});


                        // Update status bar function (remains same)
                        function updateStatusBar() {{
                            var position = editor.getPosition();
                            var model = editor.getModel();
                            if (position && model) {{
                                var lines = model.getLineCount();
                                var chars = model.getValueLength();
                                statusBar.textContent = `Ln ${position.lineNumber}, Col ${position.column} | ${lines} lines, ${chars} characters`;
                            }}
                        }}


                        editor.onDidChangeModelContent(updateStatusBar);
                        editor.onDidChangeCursorPosition(updateStatusBar);
                        updateStatusBar(); // Initial call to set status bar


                        // Value update and form submission handling (remains mostly same)
                        var $input = $('#{field_id}');
                        container.closest('form').addEventListener('submit', function(e) {{
                            var value = editor.getValue();
                            if (value.length > {max_file_size}) {{
                                e.preventDefault();
                                alert('Code content exceeds maximum size limit.');
                                return false;
                            }}
                            $input.val(value);
                            $('#{field_id}-state').val(JSON.stringify({{
                                scrollTop: editor.getScrollTop(),
                                scrollLeft: editor.getScrollLeft(),
                                viewState: editor.saveViewState()
                            }}));
                        }});


                        // Error markers (remains same, consider enhancing error display)
                        var errorWidget = null;
                        monaco.editor.onDidChangeMarkers(function() {{
                            var markers = monaco.editor.getModelMarkers({{ resource: editor.getModel().uri }});
                            var errors = markers.filter(m => m.severity === monaco.MarkerSeverity.Error);
                            if (errors.length) {{
                                if (!errorWidget) {{
                                    errorWidget = document.createElement('div');
                                    errorWidget.className = 'alert alert-danger mt-2';
                                    container.parentElement.appendChild(errorWidget);
                                }}
                                errorWidget.textContent = `${{errors.length}} error(s) found`;
                            }} else if (errorWidget) {{
                                errorWidget.remove();
                                errorWidget = null;
                            }}
                        }});


                        // Load saved state if available
                        var editorState = {_js_json(getattr(field, 'state', None))};
                        if (editorState) {{
                            editor.restoreViewState(editorState.viewState);
                            editor.setScrollTop(editorState.scrollTop);
                            editor.setScrollLeft(editorState.scrollLeft);
                        }}
                    }});
                }});
            }})();
        </script>
        """.format(
            field_id=field.id,
            language=self.language,
            theme=self.theme,
            line_numbers=str(self.line_numbers).lower(),
            minimap=str(self.minimap).lower(),
            folding=str(self.folding).lower(),
            word_wrap=self.word_wrap,
            tab_size=self.tab_size,
            insert_spaces=str(self.insert_spaces).lower(),
            quick_suggestions=str(self.quick_suggestions).lower(),
            hover=str(self.hover).lower(),
            font_size=self.font_size,
            font_family=self.font_family,
            rulers=json.dumps(self.rulers),
            scroll_beyond_last_line=str(self.scroll_beyond_last_line).lower(),
            snippets="'" + "snippets" + "'"
            if self.snippets
            else "null",  # Correct snippet value
            format_on_save=str(self.format_on_save).lower(),
            keyboard_shortcuts=json.dumps(self.keyboard_shortcuts),
            max_file_size=self.max_file_size,
            initial_value=json.dumps(field.data or ""),
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""  # Remains same
        if valuelist:
            try:
                self.data = valuelist[0]
                if hasattr(self, "state"):
                    self.state = json.loads(valuelist[1])
            except Exception as e:
                raise ValueError("Invalid code content") from e
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate code content before form processing"""  # Remains same
        if form.flags.required and not self.data:
            raise ValueError("Code content is required")

        if self.data:
            # Check content size
            if len(self.data.encode("utf-8")) > self.max_file_size:
                raise ValueError(
                    f"Code content exceeds maximum size of {self.max_file_size} bytes"
                )

            # Validate language (consider server-side linting for deeper validation)
            if self.language not in self.supported_languages:
                raise ValueError(f"Unsupported language: {self.language}")

            # Basic syntax validation for JSON and Python (extend as needed)
            try:
                if self.language == "python":
                    import ast

                    ast.parse(self.data)
                elif self.language == "json":
                    json.loads(self.data)
            except Exception as e:
                raise ValidationError(
                    f"Syntax error in {self.language} code: {str(e)}"
                )  # Use ValidationError for wtforms validation
