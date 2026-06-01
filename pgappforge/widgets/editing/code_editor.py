"""CodeEditorWidget — PgAppForge widget(s)."""

from __future__ import annotations
import html
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms.validators import ValidationError

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
        # Universal widget kwargs
        self.placeholder = kwargs.get("placeholder", "")
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        # Editor-specific
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
        if self.readonly:
            kwargs["readonly"] = True
        if self.disabled:
            kwargs["disabled"] = True

        has_errors = bool(field.errors)
        wrapper_class = self.wrapper_class
        if self.css_class:
            wrapper_class = f"{wrapper_class} {self.css_class}"

        # Accessibility: aria-label, aria-invalid, aria-describedby
        aria_label = str(field.label.text) if field.label else field.name
        describedby_parts = []
        if self.description:
            describedby_parts.append(f"{field.id}_help")
        if has_errors:
            describedby_parts.append(f"{field.id}_error")
        aria_attrs = f' aria-label="{html.escape(aria_label)}"'
        if describedby_parts:
            aria_attrs += f' aria-describedby="{" ".join(describedby_parts)}"'
        if has_errors:
            aria_attrs += ' aria-invalid="true"'

        template = self.data_template
        rendered_html = template % {
            "field_id": field.id,
            "hidden": self.html_params(name=field.name, **kwargs),
            "wrapper_class": wrapper_class,
        }

        # Help text
        help_html = ""
        if self.description:
            help_html = (
                f'<small class="form-text text-muted" id="{field.id}_help">'
                f'{html.escape(str(self.description))}</small>'
            )

        # Error feedback
        error_html = ""
        if has_errors:
            error_items = "".join(
                f"<span>{html.escape(str(e))}</span>" for e in field.errors
            )
            error_html = (
                f'<div class="invalid-feedback d-block" id="{field.id}_error">'
                f'{error_items}</div>'
            )

        return Markup(rendered_html + help_html + error_html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generates and returns the JavaScript code block for the CodeEditorWidget, including Monaco Editor initialization."""
        # Use json.dumps() for all Python values injected into JS to prevent XSS
        field_id_js = json.dumps(field.id)
        language_js = json.dumps(self.language)
        theme_js = json.dumps(self.theme)
        word_wrap_js = json.dumps(self.word_wrap)
        font_family_js = json.dumps(self.font_family)
        snippets_js = '"snippets"' if self.snippets else "null"
        return f"""
        <style>
            .code-editor-wrapper {{ border: 1px solid #dee2e6; border-radius: 4px; overflow: hidden; }}
            .editor-container {{ height: 500px; width: 100%; }}
            .editor-statusbar {{ padding: 2px 8px; background: #f8f9fa; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; }}
        </style>
        <script>
            (function() {{
                require.config({{ paths: {{ 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.33.0/min/vs' }}}});

                require(['vs/editor/editor.main'], function() {{
                    $(document).ready(function() {{
                        var fieldId = {field_id_js};
                        var container = document.getElementById(fieldId + '-container');
                        if (!container) return;
                        var statusBar = container.parentElement.querySelector('.editor-statusbar');
                        var editor;

                        // Editor configuration
                        var config = {{
                            value: {_js_json(field.data or '')},
                            language: {language_js},
                            theme: {theme_js},
                            automaticLayout: true,
                            lineNumbers: {str(self.line_numbers).lower()},
                            minimap: {{ enabled: {str(self.minimap).lower()} }},
                            folding: {str(self.folding).lower()},
                            wordWrap: {word_wrap_js},
                            tabSize: {self.tab_size},
                            insertSpaces: {str(self.insert_spaces).lower()},
                            quickSuggestions: {str(self.quick_suggestions).lower()},
                            hover: {{ enabled: {str(self.hover).lower()} }},
                            fontSize: {self.font_size},
                            fontFamily: {font_family_js},
                            rulers: {json.dumps(self.rulers)},
                            scrollBeyondLastLine: {str(self.scroll_beyond_last_line).lower()},
                            formatOnPaste: true,
                            formatOnType: true,
                            suggestOnTriggerCharacters: true,
                            snippetSuggestions: {snippets_js},
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
                        var keyboardShortcuts = {json.dumps(self.keyboard_shortcuts)};
                        Object.keys(keyboardShortcuts).forEach(function(key) {{
                            editor.addCommand(monaco.KeyMod[key], keyboardShortcuts[key]);
                        }});

                        // Update status bar
                        function updateStatusBar() {{
                            var position = editor.getPosition();
                            var model = editor.getModel();
                            if (position && model && statusBar) {{
                                var lines = model.getLineCount();
                                var chars = model.getValueLength();
                                statusBar.textContent = 'Ln ' + position.lineNumber + ', Col ' + position.column + ' | ' + lines + ' lines, ' + chars + ' characters';
                            }}
                        }}

                        editor.onDidChangeModelContent(updateStatusBar);
                        editor.onDidChangeCursorPosition(updateStatusBar);
                        updateStatusBar();

                        // Value update and form submission
                        var inputEl = document.getElementById(fieldId);
                        var form = container.closest('form');
                        if (form) {{
                            form.addEventListener('submit', function(e) {{
                                var value = editor.getValue();
                                if (value.length > {self.max_file_size}) {{
                                    e.preventDefault();
                                    alert('Code content exceeds maximum size limit.');
                                    return false;
                                }}
                                if (inputEl) inputEl.value = value;
                                var stateEl = document.getElementById(fieldId + '-state');
                                if (stateEl) {{
                                    stateEl.value = JSON.stringify({{
                                        scrollTop: editor.getScrollTop(),
                                        scrollLeft: editor.getScrollLeft(),
                                        viewState: editor.saveViewState()
                                    }});
                                }}
                            }});
                        }}

                        // Error markers
                        var errorWidget = null;
                        monaco.editor.onDidChangeMarkers(function() {{
                            var markers = monaco.editor.getModelMarkers({{ resource: editor.getModel().uri }});
                            var errors = markers.filter(function(m) {{ return m.severity === monaco.MarkerSeverity.Error; }});
                            if (errors.length) {{
                                if (!errorWidget) {{
                                    errorWidget = document.createElement('div');
                                    errorWidget.className = 'alert alert-danger mt-2';
                                    container.parentElement.appendChild(errorWidget);
                                }}
                                errorWidget.textContent = errors.length + ' error(s) found';
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

                        // Invalidate layout on Bootstrap tab/modal show
                        $(document).on('shown.bs.tab shown.bs.modal', function() {{
                            if (editor) editor.layout();
                        }});
                    }});
                }});
            }})();
        </script>
        """

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
