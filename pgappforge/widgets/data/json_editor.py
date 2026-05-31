"""JSONEditorWidget — PgAppForge widget(s)."""

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

class JSONEditorWidget(BS3TextFieldWidget):
    """
    Advanced JSON editor widget for PgAppForge using Ace editor.

    Database Type:
        PostgreSQL: JSONB or JSON
        SQLAlchemy: JSONB() or JSON()

    Features:
    - Syntax highlighting (Ace Editor)
    - Code folding (Ace Editor)
    - Search/replace (Ace Editor)
    - Auto-completion (Ace Editor)
    - Error detection (Ace Editor)
    - Customizable themes (Ace Editor themes)
    - Multiple view modes (code, tree, both)
    - Schema validation (AJV)
    - Schema editing UI (basic text editor for schema)
    - JSON Patch/Merge support (future extension)
    """

    data_template = (
        '<div class="json-editor-container">'
        '<div class="json-editor-controls btn-group mb-2">'
        '<button type="button" class="btn btn-sm btn-default" data-action="format"><i class="fa fa-indent"></i> Format</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="minify"><i class="fa fa-compress"></i> Minify</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="toggle-view"><i class="fa fa-eye"></i> View Mode</button>'
        '<button type="button" class="btn btn-sm btn-default" data-action="toggle-schema"><i class="fa fa-list-alt"></i> Edit Schema</button>'
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-editor" class="json-editor"></div>'
        '<div id="%(field_id)s-tree" class="json-tree" style="display:none;"></div>'
        '<div id="%(field_id)s-schema-editor" class="json-schema-editor" style="display:none; height:200px; border:1px solid #ccc; border-radius:4px; margin-bottom: 10px;"></div>'  # Schema editor container
        '<div class="json-editor-error"></div>'
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize JSON editor widget with extended settings"""
        super().__init__(**kwargs)
        self.height = kwargs.get("height", "400px")
        self.theme = kwargs.get("theme", "monokai")  # Ace Editor theme
        self.schema = kwargs.get("schema", None)
        self.readonly = kwargs.get("readonly", False)
        self.show_line_numbers = kwargs.get("show_line_numbers", True)
        self.tab_size = kwargs.get("tab_size", 2)
        self.word_wrap = kwargs.get("word_wrap", True)
        self.auto_complete = kwargs.get("auto_complete", True)
        self.ace_config_options = kwargs.get(
            "ace_config_options", {}
        )  # For Ace editor configuration
        self.json_viewer_options = kwargs.get(
            "json_viewer_options",
            {"collapsed": False, "withQuotes": True, "withLinks": True},
        )  # Options for jsonViewer

    def __call__(self, field, **kwargs):
        """Render the JSON editor widget with Ace Editor and JSON Viewer"""
        kwargs.setdefault("type", "hidden")

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <style>
            .json-editor-container {{
                position: relative;
                margin-bottom: 15px;
            }}
            .json-editor, .json-schema-editor {{ /* Apply same style to schema editor */
                height: {height};
                border: 1px solid #ccc;
                border-radius: 4px;
            }}
            .json-tree {{
                height: {height};
                overflow: auto;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }}
            .json-editor-error {{
                color: #a94442;
                margin-top: 5px;
            }}
            .json-editor-controls {{
                margin-bottom: 10px;
            }}
        </style>
        <script>
            (function() {{
                // Initialize Ace editor for JSON Data
                var editor = ace.edit("{field_id}-editor");
                editor.setTheme("ace/theme/{theme}");
                editor.session.setMode("ace/mode/json");
                editor.setReadOnly({readonly});
                editor.setShowPrintMargin(false);
                editor.setHighlightActiveLine(true);
                editor.setShowInvisibles(false);
                editor.setDisplayIndentGuides(true);
                editor.getSession().setTabSize({tab_size});
                editor.getSession().setUseSoftTabs(true);
                editor.getSession().setUseWrapMode({word_wrap});
                editor.renderer.setShowGutter({show_line_numbers});

                // Apply additional Ace configuration options
                editor.setOptions({ace_config_options});


                if ({auto_complete}) {{
                    editor.setOptions({{
                        enableBasicAutocompletion: true,
                        enableLiveAutocompletion: true,
                        enableSnippets: true
                    }});
                }}


                // Initialize Ace editor for JSON Schema (hidden initially)
                var schemaEditor = ace.edit("{field_id}-schema-editor");
                schemaEditor.setTheme("ace/theme/{theme}");
                schemaEditor.session.setMode("ace/mode/json");
                schemaEditor.setShowPrintMargin(false);
                schemaEditor.getSession().setTabSize({tab_size});
                schemaEditor.getSession().setUseSoftTabs(true);


                // Set initial values
                var initialValue = {json_data};
                editor.setValue(JSON.stringify(initialValue, null, {tab_size}));
                editor.clearSelection();


                var initialSchema = {schema};
                schemaEditor.setValue(JSON.stringify(initialSchema, null, {tab_size})); // Set schema editor value
                schemaEditor.clearSelection();


                // JSON Schema validation function using Ajv
                var schema = {schema}; // Initial schema
                function validateJson(json, currentSchema) {{ // Pass schema dynamically
                    if (!currentSchema) return true;
                    try {{
                        var ajv = new Ajv();
                        var valid = ajv.validate(currentSchema, json);
                        if (!valid) {{
                            $('.json-editor-error').text(ajv.errorsText());
                        }} else {{
                            $('.json-editor-error').text('');
                        }}
                        return valid;
                    }} catch (e) {{
                        $('.json-editor-error').text(e.message);
                        return false;
                    }}
                }}


                // Handle changes in JSON Data Editor and validate
                var $input = $('#{field_id}');
                editor.on('change', function() {{
                    try {{
                        var value = editor.getValue();
                        var json = JSON.parse(value);
                        var currentSchema = JSON.parse(schemaEditor.getValue() || 'null'); // Get current schema from editor
                        if (validateJson(json, currentSchema)) {{ // Pass currentSchema for validation
                            $input.val(value);
                            editor.getSession().clearAnnotations();
                        }}
                    }} catch (e) {{
                        editor.getSession().setAnnotations([{{
                            row: 0,
                            column: 0,
                            text: e.message,
                            type: 'error'
                        }}]);
                    }}
                }});


                // Control button handlers
                $('.json-editor-controls [data-action="format"]').click(function() {{
                    try {{
                        var value = JSON.parse(editor.getValue());
                        editor.setValue(JSON.stringify(value, null, {tab_size}));
                        editor.clearSelection();
                    }} catch (e) {{
                        alert('Invalid JSON: ' + e.message);
                    }}
                }});


                $('.json-editor-controls [data-action="minify"]').click(function() {{
                    try {{
                        var value = JSON.parse(editor.getValue());
                        editor.setValue(JSON.stringify(value));
                        editor.clearSelection();
                    }} catch (e) {{
                        alert('Invalid JSON: ' + e.message);
                    }}
                }});


                // Toggle tree/code view
                var $editor = $('#{field_id}-editor');
                var $tree = $('#{field_id}-tree');
                var viewerOptions = {json_viewer_options}; // Use jsonViewerOptions

                $('.json-editor-controls [data-action="toggle-view"]').click(function() {{
                    if ($editor.is(':visible')) {{
                        try {{
                            var value = JSON.parse(editor.getValue());
                            $tree.jsonViewer(value, viewerOptions);
                            $editor.hide();
                            $tree.show();
                        }} catch (e) {{
                            alert('Invalid JSON: ' + e.message);
                        }}
                    }} else {{
                        $tree.hide();
                        $editor.show();
                        editor.focus();
                    }}
                }});


                // Toggle schema editor
                var $schemaEditorDiv = $('#{field_id}-schema-editor');
                $('.json-editor-controls [data-action="toggle-schema"]').click(function() {{
                    $schemaEditorDiv.toggle();
                    if ($schemaEditorDiv.is(':visible')) {{
                        schemaEditor.focus();
                    }}
                }});


                // Handle changes in Schema Editor
                schemaEditor.on('change', function() {{
                    var currentSchema = null; // Default schema to null if parsing fails
                    try {{
                        currentSchema = JSON.parse(schemaEditor.getValue());
                    }} catch (e) {{
                        $('.json-editor-error').text('Invalid JSON Schema: ' + e.message);
                        return; // Exit validation if schema is invalid
                    }}
                    var value = editor.getValue();
                    var json = JSON.parse(value); // Parse current JSON data for validation
                    validateJson(json, currentSchema); // Validate with the current schema
                }});


            }})();
        </script>
        """.format(
                field_id=field.id,
                height=self.height,
                theme=self.theme,
                readonly=str(self.readonly).lower(),
                show_line_numbers=str(self.show_line_numbers).lower(),
                tab_size=self.tab_size,
                word_wrap=str(self.word_wrap).lower(),
                auto_complete=str(self.auto_complete).lower(),
                json_data=json.dumps(field.data or {}),
                schema=json.dumps(self.schema) if self.schema else "null",
                ace_config_options=json.dumps(self.ace_config_options),
                json_viewer_options=json.dumps(self.json_viewer_options),
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                return json.loads(valuelist[0])
            except ValueError as e:
                raise ValueError(_("Invalid JSON: ") + str(e))
        return None

    def process_data(self, value):
        """Process data from database format"""
        if value is not None:
            return json.dumps(value)
        return None
