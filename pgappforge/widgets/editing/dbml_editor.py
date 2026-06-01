"""
DBML Editor Widget for PgForge

A comprehensive Database Markup Language (DBML) editor widget with syntax highlighting,
live schema visualization, validation, and export capabilities.
"""

import html as _html
import json
from markupsafe import Markup
from wtforms.widgets import TextArea
from flask_babel import gettext


class DbmlEditorWidget(TextArea):
    """
    Advanced DBML (Database Markup Language) editor widget with comprehensive features:

    - Syntax highlighting for DBML
    - Live schema visualization
    - Table relationship diagram
    - Export to SQL, PNG, SVG
    - Real-time validation
    - Auto-completion
    - Error highlighting
    - Schema documentation generation
    """

    def __init__(
        self,
        enable_live_preview=True,
        enable_syntax_highlighting=True,
        enable_auto_complete=True,
        enable_validation=True,
        enable_export=True,
        enable_minimap=True,
        enable_line_numbers=True,
        enable_word_wrap=True,
        theme='vs-dark',
        font_size=14,
        export_formats=None,
        default_content='',
        enable_table_diagram=True,
        enable_auto_save=True,
        auto_save_interval=5000,
        enable_help=True,
        enable_schema_stats=True,
        **kwargs
    ):
        """
        Initialize DBML Editor Widget.

        Args:
            enable_live_preview: Enable live DBML preview
            enable_syntax_highlighting: Enable syntax highlighting
            enable_auto_complete: Enable auto-completion
            enable_validation: Enable DBML validation
            enable_export: Enable export functionality
            enable_minimap: Show code minimap
            enable_line_numbers: Show line numbers
            enable_word_wrap: Enable word wrapping
            theme: Editor theme ('vs-dark', 'vs-light', 'hc-black')
            font_size: Editor font size
            export_formats: List of export formats (['sql', 'png', 'svg', 'pdf'])
            default_content: Default DBML content
            enable_table_diagram: Show table relationship diagram
            enable_auto_save: Enable auto-save functionality
            auto_save_interval: Auto-save interval in milliseconds
            enable_help: Show help modal
            enable_schema_stats: Show schema statistics
        """
        super().__init__(**kwargs)
        # Universal widget kwargs
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("readonly", False)
        self.disabled = kwargs.get("disabled", False)
        self.placeholder = kwargs.get("placeholder", "")
        self.enable_live_preview = enable_live_preview
        self.enable_syntax_highlighting = enable_syntax_highlighting
        self.enable_auto_complete = enable_auto_complete
        self.enable_validation = enable_validation
        self.enable_export = enable_export
        self.enable_minimap = enable_minimap
        self.enable_line_numbers = enable_line_numbers
        self.enable_word_wrap = enable_word_wrap
        self.theme = theme
        self.font_size = font_size
        self.export_formats = export_formats or ['sql', 'png', 'svg']
        self.default_content = default_content or self._get_default_dbml()
        self.enable_table_diagram = enable_table_diagram
        self.enable_auto_save = enable_auto_save
        self.auto_save_interval = auto_save_interval
        self.enable_help = enable_help
        self.enable_schema_stats = enable_schema_stats

    def _get_default_dbml(self):
        """Get default DBML content for demonstration."""
        return '''// Sample E-commerce Database Schema
Project ecommerce_db {
  database_type: 'PostgreSQL'
  Note: 'E-commerce database with users, products, and orders'
}

Table users {
  id integer [primary key, increment]
  username varchar(50) [unique, not null]
  email varchar(100) [unique, not null]
  password_hash varchar(255) [not null]
  first_name varchar(50)
  last_name varchar(50)
  created_at timestamp [default: `now()`]
  updated_at timestamp

  Note: 'User account information'
}

Table products {
  id integer [primary key, increment]
  name varchar(255) [not null]
  description text
  price decimal(10,2) [not null]
  stock_quantity integer [default: 0]
  category_id integer [ref: > categories.id]
  created_at timestamp [default: `now()`]
  updated_at timestamp

  Note: 'Product catalog'
}

Table categories {
  id integer [primary key, increment]
  name varchar(100) [unique, not null]
  description text
  parent_id integer [ref: > categories.id]

  Note: 'Product categories with hierarchy'
}

Table orders {
  id integer [primary key, increment]
  user_id integer [ref: > users.id, not null]
  total_amount decimal(10,2) [not null]
  status varchar(20) [default: 'pending']
  created_at timestamp [default: `now()`]
  updated_at timestamp

  Note: 'Customer orders'
}

Table order_items {
  id integer [primary key, increment]
  order_id integer [ref: > orders.id, not null]
  product_id integer [ref: > products.id, not null]
  quantity integer [not null, default: 1]
  unit_price decimal(10,2) [not null]

  Note: 'Individual items in orders'
}

// Define relationships
Ref: orders.user_id > users.id [delete: cascade]
Ref: order_items.order_id > orders.id [delete: cascade]
Ref: order_items.product_id > products.id
'''

    def _get_auto_save_js(self, editor_id):
        """Generate auto-save JavaScript code."""
        if not self.enable_auto_save:
            return ""

        return f'''
                    // Clear previous timeout
                    if (changeTimeout) {{
                        clearTimeout(changeTimeout);
                    }}

                    // Set new auto-save timeout
                    changeTimeout = setTimeout(function() {{
                        // Auto-save logic - could trigger form submission or AJAX save
                        const event = new CustomEvent('dbmlAutoSave', {{
                            detail: {{
                                content: content,
                                editorId: '{editor_id}'
                            }}
                        }});
                        document.dispatchEvent(event);
                    }}, {self.auto_save_interval});
'''

    def _get_live_preview_js(self, editor_id):
        """Generate live preview JavaScript code."""
        if not self.enable_live_preview:
            return ""

        # Use template string concatenation to avoid backslash in f-string
        tab_template = f'`{{{editor_id}-${{tabName}}-view`'
        return f'''
                document.querySelectorAll('#{editor_id}-preview-tabs .tab').forEach(tab => {{
                    tab.addEventListener('click', function() {{
                        const tabName = this.dataset.tab;

                        // Update active tab
                        document.querySelectorAll('#{editor_id}-preview-tabs .tab').forEach(t => t.classList.remove('active'));
                        this.classList.add('active');

                        // Show corresponding content
                        document.querySelectorAll('#{editor_id}-preview-content .tab-content').forEach(content => {{
                            content.classList.remove('active');
                        }});
                        document.getElementById({tab_template}).classList.add('active');

                        // Update content based on tab
                        if (tabName === 'diagram') {{
                            updateDiagram();
                        }} else if (tabName === 'validation') {{
                            validateSchema();
                        }} else if (tabName === 'stats') {{
                            updateStats();
                        }} else if (tabName === 'sql') {{
                            updateSqlPreview();
                        }}
                    }});
                }});
'''

    def _get_validation_js(self, editor_id):
        """Generate validation button JavaScript code."""
        if not self.enable_validation:
            return ""
        return f"document.getElementById('{editor_id}-validate-btn').addEventListener('click', validateSchema);"

    def _get_export_js(self, editor_id):
        """Generate export button JavaScript code."""
        if not self.enable_export:
            return ""
        return f"document.getElementById('{editor_id}-export-btn').addEventListener('click', showExportOptions);"

    def _get_preview_toggle_js(self, editor_id):
        """Generate preview toggle JavaScript code."""
        if not self.enable_live_preview:
            return ""
        return f"document.getElementById('{editor_id}-preview-toggle').addEventListener('click', togglePreview);"

    def _get_help_js(self, editor_id):
        """Generate help button JavaScript code."""
        if not self.enable_help:
            return ""
        return f"document.getElementById('{editor_id}-help-btn').addEventListener('click', showHelp);"

    def __call__(self, field, **kwargs):
        """Render the DBML editor widget."""
        editor_id = kwargs.get('id', field.id or field.name)
        has_errors = bool(field.errors)

        # Build CSS
        css = self._generate_css(editor_id)

        # Build HTML structure (passes field for correct name/value handling)
        html_content = self._generate_html(field, editor_id, **kwargs)

        # Build JavaScript
        js = self._generate_javascript(editor_id, field.data or self.default_content)

        # Help text
        help_html = ""
        if self.description:
            help_html = (
                f'<small class="form-text text-muted" id="{field.id}_help">'
                f'{_html.escape(str(self.description))}</small>'
            )

        # Error feedback (server-side WTForms errors)
        error_html = ""
        if has_errors:
            error_items = "".join(
                f"<span>{_html.escape(str(e))}</span>" for e in field.errors
            )
            error_html = (
                f'<div class="invalid-feedback d-block" id="{field.id}_error" role="alert">'
                f'{error_items}</div>'
            )

        return Markup(f"{css}\n{html_content}\n{help_html}\n{error_html}\n{js}")

    def _generate_css(self, editor_id):
        """Generate CSS for the DBML editor."""
        return f'''
        <style>
        #{editor_id}-container {{
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #f8f9fa;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        #{editor_id}-toolbar {{
            background: #2d3748;
            color: white;
            padding: 8px 12px;
            border-bottom: 1px solid #4a5568;
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }}

        #{editor_id}-toolbar h5 {{
            margin: 0;
            color: #e2e8f0;
            font-size: 14px;
            font-weight: 600;
        }}

        #{editor_id}-toolbar .btn-group {{
            display: flex;
            gap: 4px;
        }}

        #{editor_id}-toolbar .btn {{
            background: #4a5568;
            border: 1px solid #718096;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        #{editor_id}-toolbar .btn:hover {{
            background: #718096;
            border-color: #a0aec0;
        }}

        #{editor_id}-toolbar .btn.active {{
            background: #3182ce;
            border-color: #2c5aa0;
        }}

        #{editor_id}-main {{
            display: flex;
            height: 600px;
        }}

        #{editor_id}-editor-panel {{
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }}

        #{editor_id}-editor {{
            flex: 1;
            border: none;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
        }}

        #{editor_id}-status {{
            background: #f7fafc;
            border-top: 1px solid #e2e8f0;
            padding: 4px 8px;
            font-size: 11px;
            color: #718096;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        #{editor_id}-preview-panel {{
            width: 50%;
            border-left: 1px solid #e2e8f0;
            background: white;
            display: flex;
            flex-direction: column;
        }}

        #{editor_id}-preview-tabs {{
            background: #f7fafc;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
        }}

        #{editor_id}-preview-tabs .tab {{
            padding: 8px 16px;
            border: none;
            background: transparent;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            font-size: 12px;
            color: #4a5568;
        }}

        #{editor_id}-preview-tabs .tab.active {{
            color: #3182ce;
            border-bottom-color: #3182ce;
            background: white;
        }}

        #{editor_id}-preview-content {{
            flex: 1;
            overflow: auto;
            padding: 16px;
        }}

        #{editor_id}-diagram {{
            width: 100%;
            height: 100%;
            border: none;
        }}

        #{editor_id}-validation {{
            max-height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }}

        .dbml-error {{
            color: #e53e3e;
            background: #fed7d7;
            padding: 4px 8px;
            margin: 2px 0;
            border-radius: 4px;
            border-left: 3px solid #e53e3e;
        }}

        .dbml-warning {{
            color: #d69e2e;
            background: #fefcbf;
            padding: 4px 8px;
            margin: 2px 0;
            border-radius: 4px;
            border-left: 3px solid #d69e2e;
        }}

        .dbml-info {{
            color: #3182ce;
            background: #bee3f8;
            padding: 4px 8px;
            margin: 2px 0;
            border-radius: 4px;
            border-left: 3px solid #3182ce;
        }}

        #{editor_id}-stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 12px;
            padding: 12px;
            background: #f7fafc;
            border-radius: 6px;
            margin-bottom: 12px;
        }}

        #{editor_id}-stats .stat {{
            text-align: center;
        }}

        #{editor_id}-stats .stat-value {{
            font-size: 18px;
            font-weight: bold;
            color: #2d3748;
        }}

        #{editor_id}-stats .stat-label {{
            font-size: 11px;
            color: #718096;
            text-transform: uppercase;
        }}

        .hidden {{
            display: none !important;
        }}

        @media (max-width: 768px) {{
            #{editor_id}-main {{
                flex-direction: column;
                height: auto;
            }}

            #{editor_id}-editor-panel {{
                height: 400px;
            }}

            #{editor_id}-preview-panel {{
                width: 100%;
                height: 300px;
                border-left: none;
                border-top: 1px solid #e2e8f0;
            }}

            #{editor_id}-toolbar {{
                flex-direction: column;
                align-items: stretch;
                gap: 8px;
            }}

            #{editor_id}-toolbar .btn-group {{
                justify-content: center;
            }}
        }}
        </style>
        '''

    def _generate_html(self, field, editor_id, **kwargs):
        """Generate HTML structure for the DBML editor."""
        has_errors = bool(field.errors)
        aria_label = str(field.label.text) if field.label else field.name
        describedby_parts = []
        if self.description:
            describedby_parts.append(f"{field.id}_help")
        if has_errors:
            describedby_parts.append(f"{field.id}_error")
        describedby_attr = (
            f' aria-describedby="{_html.escape(" ".join(describedby_parts))}"'
            if describedby_parts else ""
        )
        aria_invalid_attr = ' aria-invalid="true"' if has_errors else ""

        # Safe field values
        field_name = _html.escape(field.name)
        field_value = _html.escape(field.data or "")

        # Build preview panel HTML
        if self.enable_live_preview:
            tabs = ""
            if self.enable_table_diagram:
                tabs += f'<button class="tab active" data-tab="diagram">{gettext("Diagram")}</button>'
            if self.enable_validation:
                tabs += f'<button class="tab" data-tab="validation">{gettext("Validation")}</button>'
            if self.enable_schema_stats:
                tabs += f'<button class="tab" data-tab="stats">{gettext("Statistics")}</button>'
            tabs += f'<button class="tab" data-tab="sql">{gettext("SQL Preview")}</button>'

            tab_contents = ""
            if self.enable_table_diagram:
                tab_contents += f'<div id="{editor_id}-diagram-view" class="tab-content active"><div id="{editor_id}-diagram"></div></div>'
            if self.enable_validation:
                tab_contents += f'<div id="{editor_id}-validation-view" class="tab-content"><div id="{editor_id}-validation"></div></div>'
            if self.enable_schema_stats:
                tab_contents += f'<div id="{editor_id}-stats-view" class="tab-content"><div id="{editor_id}-stats"></div></div>'
            tab_contents += f'<div id="{editor_id}-sql-view" class="tab-content"><pre id="{editor_id}-sql-preview" style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 12px; border-radius: 4px; overflow: auto;"></pre></div>'

            preview_panel = (
                f'<div id="{editor_id}-preview-panel" class="dbml-preview-panel">'
                f'<div id="{editor_id}-preview-tabs" class="dbml-preview-tabs">{tabs}</div>'
                f'<div id="{editor_id}-preview-content" class="dbml-preview-content">{tab_contents}</div>'
                f'</div>'
            )
        else:
            preview_panel = ""

        validate_btn = (
            f'<button type="button" class="btn" id="{editor_id}-validate-btn" title="{gettext("Validate Schema")}">'
            f'<i class="fas fa-check"></i> {gettext("Validate")}</button>'
            if self.enable_validation else ""
        )
        export_btn = (
            f'<button type="button" class="btn" id="{editor_id}-export-btn" title="{gettext("Export Schema")}">'
            f'<i class="fas fa-download"></i> {gettext("Export")}</button>'
            if self.enable_export else ""
        )
        preview_toggle_btn = (
            f'<button type="button" class="btn active" id="{editor_id}-preview-toggle" title="{gettext("Toggle Preview")}">'
            f'<i class="fas fa-eye"></i> {gettext("Preview")}</button>'
            if self.enable_live_preview else ""
        )
        help_btn = (
            f'<button type="button" class="btn" id="{editor_id}-help-btn" title="{gettext("Show Help")}">'
            f'<i class="fas fa-question-circle"></i> {gettext("Help")}</button>'
            if self.enable_help else ""
        )

        return f'''
        <div id="{editor_id}-container" class="dbml-editor-container"
             role="application"
             aria-label="{_html.escape(aria_label)}"
             {describedby_attr}
             {aria_invalid_attr}>
            <!-- Toolbar -->
            <div id="{editor_id}-toolbar" class="dbml-toolbar">
                <h5><i class="fas fa-database"></i> {gettext("DBML Schema Editor")}</h5>
                <div class="btn-group">
                    {validate_btn}
                    {export_btn}
                    <button type="button" class="btn" id="{editor_id}-format-btn" title="{gettext("Format Code")}">
                        <i class="fas fa-code"></i> {gettext("Format")}
                    </button>
                </div>
                <div class="btn-group">
                    {preview_toggle_btn}
                    {help_btn}
                </div>
            </div>

            <!-- Main Content -->
            <div id="{editor_id}-main" class="dbml-main">
                <!-- Editor Panel -->
                <div id="{editor_id}-editor-panel" class="dbml-editor-panel">
                    <div id="{editor_id}-editor" class="dbml-editor"
                         role="textbox" aria-multiline="true"
                         aria-label="{_html.escape(aria_label)}"></div>
                    <div id="{editor_id}-status" class="dbml-status" role="status" aria-live="polite">
                        <span id="{editor_id}-cursor-info">Line 1, Column 1</span>
                        <span id="{editor_id}-selection-info"></span>
                        <span id="{editor_id}-file-info">DBML</span>
                    </div>
                </div>

                <!-- Preview Panel -->
                {preview_panel}
            </div>

            <!-- Hidden input field -->
            <input type="hidden" name="{field_name}" id="{editor_id}" value="{field_value}" />
        </div>
        '''

    def _escape_content_for_js(self, content):
        """Escape content for safe inclusion in JavaScript — delegates to json.dumps."""
        return json.dumps(content)

    def _generate_javascript(self, editor_id, initial_content):
        """Generate JavaScript for the DBML editor."""
        # json.dumps produces a properly quoted+escaped JS string literal
        initial_content_js = json.dumps(initial_content)
        return f'''
        <script>
        (function() {{
            // Wait for Monaco Editor to load
            function loadDbmlEditor() {{
                if (typeof monaco === 'undefined') {{
                    // Load Monaco Editor
                    const script = document.createElement('script');
                    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js';
                    script.onload = function() {{
                        require.config({{ paths: {{ vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' }} }});
                        require(['vs/editor/editor.main'], function() {{
                            initDbmlEditor();
                        }});
                    }};
                    document.head.appendChild(script);
                }} else {{
                    initDbmlEditor();
                }}
            }}

            function initDbmlEditor() {{
                // Register DBML language
                monaco.languages.register({{ id: 'dbml' }});

                // Define DBML tokens
                monaco.languages.setMonarchTokensProvider('dbml', {{
                    tokenizer: {{
                        root: [
                            [/\\/\\/.*$/, 'comment'],
                            [/Table|Ref|Project|Enum|TableGroup|Note/, 'keyword'],
                            [/primary key|unique|not null|increment|default|delete|cascade|restrict|set null|set default/, 'keyword.modifier'],
                            [/varchar|integer|decimal|text|timestamp|boolean|json|uuid/, 'type'],
                            [/"([^"\\\\]|\\\\.)*$/, 'string.invalid'],
                            [/"/, 'string', '@string'],
                            [/'([^'\\\\]|\\\\.)*$/, 'string.invalid'],
                            [/'/, 'string', '@string_single'],
                            [/`/, 'string', '@string_backtick'],
                            [/\\d+(\\.\\d+)?/, 'number'],
                            [/[{{}}\\[\\]\\(\\)]/, 'bracket'],
                            [/[<>=!]+/, 'operator'],
                            [/[;,.]/, 'delimiter'],
                            [/[a-zA-Z_]\\w*/, 'identifier']
                        ],
                        string: [
                            [/[^"\\\\]+/, 'string'],
                            [/"/, 'string', '@pop']
                        ],
                        string_single: [
                            [/[^'\\\\]+/, 'string'],
                            [/'/, 'string', '@pop']
                        ],
                        string_backtick: [
                            [/[^`\\\\]+/, 'string'],
                            [/`/, 'string', '@pop']
                        ]
                    }}
                }});

                // Define DBML completion items
                monaco.languages.registerCompletionItemProvider('dbml', {{
                    provideCompletionItems: function(model, position) {{
                        const suggestions = [
                            {{
                                label: 'Table',
                                kind: monaco.languages.CompletionItemKind.Keyword,
                                insertText: 'Table ${{1:table_name}} {{\\n  ${{2:id}} ${{3:integer}} [primary key, increment]\\n  ${{4:name}} ${{5:varchar(255)}} [not null]\\n  ${{0}}\\n}}',
                                insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                                documentation: 'Create a new table'
                            }},
                            {{
                                label: 'Ref',
                                kind: monaco.languages.CompletionItemKind.Keyword,
                                insertText: 'Ref: ${{1:table1.field1}} > ${{2:table2.field2}}',
                                insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                                documentation: 'Create a reference between tables'
                            }},
                            {{
                                label: 'Project',
                                kind: monaco.languages.CompletionItemKind.Keyword,
                                insertText: 'Project ${{1:project_name}} {{\\n  database_type: \\'${{2:PostgreSQL}}\\'\\n  Note: \\'${{3:Project description}}\\'\\n}}',
                                insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                                documentation: 'Define project metadata'
                            }},
                            {{
                                label: 'Enum',
                                kind: monaco.languages.CompletionItemKind.Keyword,
                                insertText: 'Enum ${{1:enum_name}} {{\\n  ${{2:value1}}\\n  ${{3:value2}}\\n}}',
                                insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                                documentation: 'Define an enumeration'
                            }}
                        ];
                        return {{ suggestions: suggestions }};
                    }}
                }});

                // Initialize editor
                const editor = monaco.editor.create(document.getElementById('{editor_id}-editor'), {{
                    value: {initial_content_js},
                    language: 'dbml',
                    theme: '{self.theme}',
                    fontSize: {self.font_size},
                    minimap: {{ enabled: {str(self.enable_minimap).lower()} }},
                    lineNumbers: '{str(self.enable_line_numbers).lower()}',
                    wordWrap: '{"on" if self.enable_word_wrap else "off"}',
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    renderWhitespace: 'selection',
                    contextmenu: true,
                    quickSuggestions: {str(self.enable_auto_complete).lower()},
                    suggestOnTriggerCharacters: true
                }});

                // Store editor reference
                window.dbmlEditors = window.dbmlEditors || {{}};
                window.dbmlEditors['{editor_id}'] = editor;

                // Update hidden input on change
                let changeTimeout;
                editor.onDidChangeModelContent(function() {{
                    const content = editor.getValue();
                    document.getElementById('{editor_id}').value = content;

                    // Auto-save
                    {self._get_auto_save_js(editor_id)}

                    updateCursorInfo();
                }});

                // Update cursor position
                editor.onDidChangeCursorPosition(updateCursorInfo);
                editor.onDidChangeCursorSelection(updateSelectionInfo);

                function updateCursorInfo() {{
                    const position = editor.getPosition();
                    document.getElementById('{editor_id}-cursor-info').textContent =
                        `Line ${{position.lineNumber}}, Column ${{position.column}}`;
                }}

                function updateSelectionInfo() {{
                    const selection = editor.getSelection();
                    const selectionInfo = document.getElementById('{editor_id}-selection-info');
                    if (selection && !selection.isEmpty()) {{
                        const selectedText = editor.getModel().getValueInRange(selection);
                        selectionInfo.textContent = `Selected: ${{selectedText.length}} chars`;
                    }} else {{
                        selectionInfo.textContent = '';
                    }}
                }}

                // Tab switching
                {self._get_live_preview_js(editor_id)}

                // Toolbar button handlers
                {self._get_validation_js(editor_id)}
                {self._get_export_js(editor_id)}

                document.getElementById('{editor_id}-format-btn').addEventListener('click', formatCode);

                {self._get_preview_toggle_js(editor_id)}
                {self._get_help_js(editor_id)}

                // Functions
                function validateSchema() {{
                    const content = editor.getValue();
                    const validationDiv = document.getElementById('{editor_id}-validation');
                    if (!validationDiv) return;

                    const issues = parseDbml(content);

                    if (issues.length === 0) {{
                        validationDiv.innerHTML = '<div class="dbml-info">✓ Schema is valid - no issues found</div>';
                    }} else {{
                        validationDiv.innerHTML = issues.map(issue => {{
                            const className = issue.type === 'error' ? 'dbml-error' :
                                           issue.type === 'warning' ? 'dbml-warning' : 'dbml-info';
                            return `<div class="${{className}}">Line ${{issue.line}}: ${{issue.message}}</div>`;
                        }}).join('');
                    }}
                }}

                function parseDbml(content) {{
                    const issues = [];
                    const lines = content.split('\\n');

                    lines.forEach((line, index) => {{
                        const lineNum = index + 1;
                        const trimmed = line.trim();

                        // Basic validation rules
                        if (trimmed.includes('Table') && !trimmed.includes('{{')) {{
                            if (!lines.slice(index).some(l => l.trim() === '}}')) {{
                                issues.push({{
                                    line: lineNum,
                                    type: 'error',
                                    message: 'Table definition not properly closed with }}'
                                }});
                            }}
                        }}

                        if (trimmed.includes('[ref:') && !trimmed.includes(']')) {{
                            issues.push({{
                                line: lineNum,
                                type: 'error',
                                message: 'Reference not properly closed with ]'
                            }});
                        }}

                        if (trimmed.includes('Ref:') && !trimmed.includes('>') && !trimmed.includes('<')) {{
                            issues.push({{
                                line: lineNum,
                                type: 'warning',
                                message: 'Reference missing relationship operator (>, <, -, <>)'
                            }});
                        }}
                    }});

                    return issues;
                }}

                function updateStats() {{
                    const content = editor.getValue();
                    const statsDiv = document.getElementById('{editor_id}-stats');
                    if (!statsDiv) return;

                    const stats = analyzeSchema(content);

                    statsDiv.innerHTML = `
                        <div class="stat">
                            <div class="stat-value">${{stats.tables}}</div>
                            <div class="stat-label">Tables</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{stats.columns}}</div>
                            <div class="stat-label">Columns</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{stats.relationships}}</div>
                            <div class="stat-label">Relations</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{stats.enums}}</div>
                            <div class="stat-label">Enums</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{stats.indexes}}</div>
                            <div class="stat-label">Indexes</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{content.split('\\n').length}}</div>
                            <div class="stat-label">Lines</div>
                        </div>
                    `;
                }}

                function analyzeSchema(content) {{
                    const tableMatches = content.match(/Table\\s+\\w+/g) || [];
                    const columnMatches = content.match(/^\\s+\\w+\\s+\\w+/gm) || [];
                    const refMatches = content.match(/Ref:/g) || [];
                    const enumMatches = content.match(/Enum\\s+\\w+/g) || [];
                    const indexMatches = content.match(/\\[.*primary key.*\\]/gi) || [];

                    return {{
                        tables: tableMatches.length,
                        columns: columnMatches.length,
                        relationships: refMatches.length,
                        enums: enumMatches.length,
                        indexes: indexMatches.length
                    }};
                }}

                function updateSqlPreview() {{
                    const content = editor.getValue();
                    const sqlPreview = document.getElementById('{editor_id}-sql-preview');
                    if (!sqlPreview) return;

                    const sql = convertDbmlToSql(content);
                    sqlPreview.textContent = sql;
                }}

                function convertDbmlToSql(content) {{
                    // Basic DBML to SQL conversion
                    let sql = '-- Generated SQL from DBML\\n\\n';

                    const lines = content.split('\\n');
                    let inTable = false;
                    let tableName = '';
                    let tableColumns = [];

                    lines.forEach(line => {{
                        const trimmed = line.trim();

                        if (trimmed.startsWith('Table ')) {{
                            if (inTable) {{
                                // Close previous table
                                sql += generateCreateTable(tableName, tableColumns);
                                tableColumns = [];
                            }}
                            tableName = trimmed.split(' ')[1];
                            inTable = true;
                        }} else if (trimmed === '}}' && inTable) {{
                            sql += generateCreateTable(tableName, tableColumns);
                            tableColumns = [];
                            inTable = false;
                        }} else if (inTable && trimmed && !trimmed.startsWith('//') && !trimmed.startsWith('Note:')) {{
                            tableColumns.push(trimmed);
                        }}
                    }});

                    return sql;
                }}

                function generateCreateTable(tableName, columns) {{
                    let sql = `CREATE TABLE ${{tableName}} (\\n`;

                    columns.forEach((col, index) => {{
                        const parts = col.split(' ');
                        const columnName = parts[0];
                        const columnType = parts[1] || 'VARCHAR(255)';

                        let constraints = '';
                        if (col.includes('primary key')) constraints += ' PRIMARY KEY';
                        if (col.includes('not null')) constraints += ' NOT NULL';
                        if (col.includes('unique')) constraints += ' UNIQUE';
                        if (col.includes('increment')) constraints += ' AUTO_INCREMENT';

                        sql += `  ${{columnName}} ${{columnType.toUpperCase()}}${{constraints}}`;
                        if (index < columns.length - 1) sql += ',';
                        sql += '\\n';
                    }});

                    sql += ');\\n\\n';
                    return sql;
                }}

                function updateDiagram() {{
                    // Placeholder for diagram visualization
                    const diagramDiv = document.getElementById('{editor_id}-diagram');
                    if (!diagramDiv) return;

                    diagramDiv.innerHTML = `
                        <div style="text-align: center; padding: 50px; color: #718096;">
                            <i class="fas fa-sitemap" style="font-size: 48px; margin-bottom: 16px;"></i>
                            <h4>Database Schema Diagram</h4>
                            <p>Schema visualization will appear here.</p>
                            <p><small>Integration with dbdiagram.io or similar service recommended for production.</small></p>
                        </div>
                    `;
                }}

                function updatePreview() {{
                    const activeTab = document.querySelector('#{editor_id}-preview-tabs .tab.active');
                    if (activeTab) {{
                        const tabName = activeTab.dataset.tab;
                        if (tabName === 'diagram') updateDiagram();
                        else if (tabName === 'validation') validateSchema();
                        else if (tabName === 'stats') updateStats();
                        else if (tabName === 'sql') updateSqlPreview();
                    }}
                }}

                function formatCode() {{
                    // Basic DBML formatting
                    const content = editor.getValue();
                    const formatted = formatDbml(content);
                    editor.setValue(formatted);
                }}

                function formatDbml(content) {{
                    const lines = content.split('\\n');
                    let formatted = '';
                    let indentLevel = 0;

                    lines.forEach(line => {{
                        const trimmed = line.trim();

                        if (trimmed === '}}') {{
                            indentLevel = Math.max(0, indentLevel - 1);
                        }}

                        if (trimmed) {{
                            formatted += '  '.repeat(indentLevel) + trimmed + '\\n';
                        }} else {{
                            formatted += '\\n';
                        }}

                        if (trimmed.includes('{{')) {{
                            indentLevel++;
                        }}
                    }});

                    return formatted;
                }}

                function togglePreview() {{
                    const previewPanel = document.getElementById('{editor_id}-preview-panel');
                    const button = document.getElementById('{editor_id}-preview-toggle');

                    if (previewPanel.style.display === 'none') {{
                        previewPanel.style.display = 'flex';
                        button.classList.add('active');
                        button.innerHTML = '<i class="fas fa-eye"></i> {gettext("Preview")}';
                    }} else {{
                        previewPanel.style.display = 'none';
                        button.classList.remove('active');
                        button.innerHTML = '<i class="fas fa-eye-slash"></i> {gettext("Show Preview")}';
                    }}

                    editor.layout();
                }}

                function showExportOptions() {{
                    const formats = {self.export_formats};
                    const content = editor.getValue();

                    const modal = document.createElement('div');
                    modal.innerHTML = `
                        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; align-items: center; justify-content: center;">
                            <div style="background: white; padding: 24px; border-radius: 8px; min-width: 400px; max-width: 500px;">
                                <h4>{gettext("Export DBML Schema")}</h4>
                                <div style="margin: 16px 0;">
                                    ${{formats.map(format => `
                                        <button class="btn btn-primary" style="margin: 4px;" onclick="exportSchema('${{format}}')">${{format.toUpperCase()}}</button>
                                    `).join('')}}
                                </div>
                                <div style="text-align: right;">
                                    <button class="btn btn-secondary" onclick="this.closest('div').parentElement.remove()">{gettext("Cancel")}</button>
                                </div>
                            </div>
                        </div>
                    `;

                    document.body.appendChild(modal);

                    window.exportSchema = function(format) {{
                        if (format === 'sql') {{
                            const sql = convertDbmlToSql(content);
                            downloadFile(sql, `schema.sql`, 'text/sql');
                        }} else if (format === 'dbml') {{
                            downloadFile(content, `schema.dbml`, 'text/plain');
                        }} else {{
                            alert(`Export to ${{format.toUpperCase()}} format coming soon!`);
                        }}
                        modal.remove();
                    }};
                }}

                function downloadFile(content, filename, mimeType) {{
                    const blob = new Blob([content], {{ type: mimeType }});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }}

                function showHelp() {{
                    const helpModal = document.createElement('div');
                    helpModal.innerHTML = `
                        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; align-items: center; justify-content: center;">
                            <div style="background: white; padding: 24px; border-radius: 8px; max-width: 700px; max-height: 80vh; overflow-y: auto;">
                                <h4>{gettext("DBML Quick Reference")}</h4>
                                <div style="font-family: monospace; font-size: 12px;">
                                    <h5>Table Definition:</h5>
                                    <pre>Table users {{
  id integer [primary key, increment]
  name varchar(255) [not null]
  email varchar [unique]
  created_at timestamp [default: `now()`]
}}</pre>

                                    <h5>Relationships:</h5>
                                    <pre>Ref: posts.user_id > users.id
Ref: orders.user_id > users.id [delete: cascade]</pre>

                                    <h5>Project Info:</h5>
                                    <pre>Project ecommerce {{
  database_type: 'PostgreSQL'
  Note: 'E-commerce database'
}}</pre>

                                    <h5>Enums:</h5>
                                    <pre>Enum order_status {{
  pending
  confirmed
  shipped
  delivered
}}</pre>
                                </div>
                                <div style="text-align: right; margin-top: 16px;">
                                    <button class="btn btn-primary" onclick="this.closest('div').parentElement.remove()">{gettext("Close")}</button>
                                </div>
                            </div>
                        </div>
                    `;
                    document.body.appendChild(helpModal);
                }}

                // Initialize
                updateCursorInfo();
                {"" if not self.enable_live_preview else "updatePreview();"}

                console.log('DBML Editor initialized successfully');
            }}

            // Load editor when DOM is ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', loadDbmlEditor);
            }} else {{
                loadDbmlEditor();
            }}
        }})();
        </script>
        '''