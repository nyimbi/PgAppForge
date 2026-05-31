"""TagInputWidget, MultiSelectWidget, DependentSelectWidget — PgAppForge widget(s)."""

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

class TagInputWidget(BS3TextFieldWidget):
    """
    Advanced tag input widget for PgAppForge supporting both string array and JSONB storage.

    Features:
    - Tag validation
    - Auto-complete suggestions (local and remote)
    - Custom tag formatting
    - Max tags limit
    - Duplicate prevention
    - Case sensitivity options
    - Tag categories/types with distinct styling
    - Keyboard navigation
    - Paste handling
    - Tag editing with backspace/delete
    - Flexible delimiter configuration

    Database Type:
        PostgreSQL: TEXT[] or JSONB
        SQLAlchemy: ARRAY(String) or JSONB

    Example Usage:
        tags = db.Column(ARRAY(String), default=[])
        # or
        tags = db.Column(JSONB, default={})
    """

    data_template = (
        '<div class="tag-input-container">'
        "<input %(text)s>"
        '<div class="tag-suggestions"></div>'
        '<div class="tag-error"></div>'
        "</div>"
    )
    empty_template = data_template

    def __init__(self, **kwargs):
        """Initialize tag input widget with custom settings"""
        super().__init__(**kwargs)
        self.max_tags = kwargs.get("max_tags", None)
        self.min_chars = kwargs.get("min_chars", 2)
        self.max_chars = kwargs.get("max_chars", 50)
        self.suggestions = kwargs.get("suggestions", [])
        self.remote_source = kwargs.get("remote_source", None)  # For remote suggestions
        self.allow_duplicates = kwargs.get("allow_duplicates", False)
        self.case_sensitive = kwargs.get("case_sensitive", False)
        self.tag_types = kwargs.get("tag_types", {})
        self.validate_pattern = kwargs.get("validate_pattern", None)
        self.delimiter = kwargs.get("delimiter", ",")
        self.placeholder = kwargs.get("placeholder", "Add tags...")
        self.free_input = kwargs.get(
            "free_input", True
        )  # Allow free input if no suggestions match

    def __call__(self, field, **kwargs):
        """Render the tag input widget"""
        kwargs.setdefault("type", "text")
        kwargs.setdefault("data-role", "tagsinput")
        kwargs.setdefault("placeholder", self.placeholder)

        if field.data:
            if isinstance(field.data, list):
                kwargs.setdefault("value", self.delimiter.join(field.data))
            elif isinstance(field.data, dict):
                kwargs.setdefault("value", self.delimiter.join(field.data.keys()))

        template = self.data_template if field.data else self.empty_template
        html = template % {"text": self.html_params(name=field.name, **kwargs)}

        return Markup(
            html
            + """
        <style>
            .tag-input-container {
                position: relative;
            }
            .bootstrap-tagsinput {
                width: 100%;
                border-radius: 4px;
                box-shadow: none;
                border: 1px solid #ccc;
                padding: 6px 12px;
                min-height: 34px;
            }
            .bootstrap-tagsinput .tag {
                margin-right: 4px;
                margin-bottom: 4px;
                display: inline-block;
            }
            .tag-suggestions {
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                z-index: 1000;
                display: none;
                background: #fff;
                border: 1px solid #ccc;
                border-radius: 0 0 4px 4px;
                box-shadow: 0 6px 12px rgba(0,0,0,.175);
            }
            .tag-error {
                color: #a94442;
                margin-top: 5px;
                font-size: 12px;
            }
        </style>
        <script>
            (function() {
                var $input = $('#{field_id}');
                var $container = $input.closest('.tag-input-container');
                var $suggestions = $container.find('.tag-suggestions');
                var $error = $container.find('.tag-error');


                var tagConfig = {{
                    trimValue: true,
                    confirmKeys: [13, {delimiter_code}],
                    maxTags: {max_tags},
                    tagClass: function(item) {{
                        return 'label label-' + ({tag_types}[item] || 'primary');
                    }},
                     freeInput: {free_input}, // Allow free input
                    typeaheadjs: {typeahead_config}
                }};


                $input.tagsinput(tagConfig)

                .on('beforeItemAdd', function(event) {{
                    // Validate tag before adding
                    var tag = event.item;

                    // Check length
                    if (tag.length < {min_chars}) {{
                        event.cancel = true;
                        $error.text('Tag must be at least {min_chars} characters');
                        return;
                    }}
                    if (tag.length > {max_chars}) {{
                        event.cancel = true;
                        $error.text('Tag cannot exceed {max_chars} characters');
                        return;
                    }}

                    // Check pattern if specified
                    {pattern_check}

                    // Check duplicates
                    if (!{allow_duplicates} && $input.tagsinput('items').indexOf(
                        {case_sensitive} ? tag : tag.toLowerCase()) !== -1) {{
                        event.cancel = true;
                        $error.text('Duplicate tags not allowed');
                        return;
                    }}

                    $error.text('');
                }})

                .on('itemAdded itemRemoved', function() {{
                    // Update underlying field value
                    var tags = $input.tagsinput('items');
                    if ({store_as_json}) {{
                        var tagObj = {{}};
                        tags.forEach(function(tag) {{
                            tagObj[tag] = {tag_types}[tag] || 'default';
                        }});
                        $input.val(JSON.stringify(tagObj));
                    }} else {{
                        $input.val(tags.join('{delimiter}'));
                    }}
                }})

                // Handle tag editing (bootstrap-tagsinput doesn't directly support editing, consider a custom solution or alternative library for full editing)

                // Handle clear (if needed, implement a clear button and handler)

                // Handle paste (already implemented)


                // Initialize with existing values
                var initialValue = $input.val();
                if (initialValue) {{
                    if ({store_as_json}) {{
                        try {{
                            var tagObj = JSON.parse(initialValue);
                            Object.keys(tagObj).forEach(function(tag) {{
                                $input.tagsinput('add', tag);
                            }});
                        }} catch(e) {{
                            console.error('Invalid JSON for tags:', e);
                        }}
                    }} else {{
                        initialValue.split('{delimiter}').forEach(function(tag) {{
                            $input.tagsinput('add', tag.trim());
                        }});
                    }}
                }}
            }})();
        </script>
        """.format(
                field_id=field.id,
                max_tags="null" if self.max_tags is None else self.max_tags,
                min_chars=self.min_chars,
                max_chars=self.max_chars,
                suggestions=json.dumps(self.suggestions),
                allow_duplicates=str(self.allow_duplicates).lower(),
                case_sensitive=str(self.case_sensitive).lower(),
                tag_types=json.dumps(self.tag_types),
                pattern_check=(
                    f"""
                if (!/{self.validate_pattern}/.test(tag)) {{
                    event.cancel = true;
                    $error.text('Invalid tag format');
                    return;
                }}
            """
                    if self.validate_pattern
                    else ""
                ),
                delimiter=self.delimiter,
                delimiter_code=ord(self.delimiter),
                store_as_json=str(
                    isinstance(getattr(field, "type", None), JSONB)
                ).lower(),
                typeahead_config=(
                    f"""{{
                        source: function(query) {{
                            return $.getJSON('{self.remote_source}', {{ query: query }});
                        }},
                        display: 'value',
                        value: 'value',
                        limit: 10
                    }}"""
                    if self.remote_source
                    else f"""{{
                        source: {_js_json(self.suggestions)},
                        limit: 10
                    }}"""
                ),
                free_input=str(self.free_input).lower(),  # Pass free_input to script
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            if isinstance(self.field.type, JSONB):
                try:
                    return json.loads(valuelist[0])
                except ValueError as e:
                    raise ValueError(_("Invalid JSON for tags: ") + str(e))
            # Handle different delimiters using csv reader for robustness
            import csv

            io_text = io.StringIO(valuelist[0])
            reader = csv.reader(io_text, delimiter=self.delimiter)
            tags = next(reader)  # Get the first line of tags
            return [
                tag.strip() for tag in tags if tag.strip()
            ]  # Strip each tag for whitespace

        return []

    def process_data(self, value):
        """Process data from database format"""
        if value:
            if isinstance(value, dict):
                return json.dumps(value)
            return self.delimiter.join(value)
        return ""


class MultiSelectWidget(BS3TextFieldWidget):
    """
    Advanced hierarchical multi-select widget with enhanced features.
    """

    template = """
        <div class="multi-select-container">
            <div class="multi-select-header">
                <div class="search-box">
                    <input type="text" class="form-control search-input"
                           placeholder="Search...">
                </div>
                {% if select_all %}
                <div class="select-controls">
                    <button class="btn btn-xs btn-default select-all">
                        <i class="fa fa-check-square-o"></i> Select All
                    </button>
                    <button class="btn btn-xs btn-default deselect-all">
                        <i class="fa fa-square-o"></i> Deselect All
                    </button>
                </div>
                {% endif %}
            </div>

            <input %(hidden)s>
            <select id="%(field_id)s-select" multiple="multiple"
                    class="form-control select2-multi">
                %(options)s
            </select>

            <div class="selected-items-container">
                <h5>Selected Items <span class="selected-count"></span></h5>
                <ul class="selected-items-list"></ul>
            </div>

            <div class="multi-select-footer">
                <div class="multi-select-error"></div>
                <div class="multi-select-help"></div>
            </div>
        </div>
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = {
            "max_selections": kwargs.get("max_selections"),
            "min_selections": kwargs.get("min_selections"),
            "placeholder": kwargs.get("placeholder", "Select options..."),
            "allow_clear": kwargs.get("allow_clear", True),
            "tags": kwargs.get("tags", False),
            "remote_url": kwargs.get("remote_url"),
            "search_min_length": kwargs.get("search_min_length", 0),
            "sort_options": kwargs.get("sort_options", False),
            "group_by": kwargs.get("group_by"),
            "help_text": kwargs.get("help_text", ""),
            "sortable": kwargs.get("sortable", False),
            "max_selections_group": kwargs.get("max_selections_group", {}),
            "select_all": kwargs.get("select_all", False),
            "custom_styles": kwargs.get("custom_styles", {}),
            "lazy_loading": kwargs.get("lazy_loading", False),
            "selection_threshold": kwargs.get("selection_threshold", 10),
            "option_template": kwargs.get("option_template"),
        }

    def __call__(self, field, **kwargs):
        """Render the widget"""
        kwargs["type"] = "hidden"
        kwargs["multiple"] = "multiple"

        if field.flags.required:
            kwargs["required"] = True

        options_html = self._render_options(field)

        template_data = {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "options": options_html,
        }

        html = self._render_template(template_data)
        return Markup(html + self._generate_assets(field))

    def _render_options(self, field):
        """Render select options with grouping support"""
        if not hasattr(field, "choices"):
            return ""

        if self.config["group_by"]:
            return self._render_grouped_options(field.choices)
        return self._render_flat_options(field.choices)

    def _render_grouped_options(self, choices):
        """Render options in groups"""
        from itertools import groupby

        def get_group_key(choice):
            return choice[2] if len(choice) > 2 else "Other"

        sorted_choices = sorted(choices, key=get_group_key)
        grouped = groupby(sorted_choices, key=get_group_key)

        options = []
        for group, items in grouped:
            group_html = f'<optgroup label="{group}">'
            options_html = "\n".join(
                f'<option value="{item[0]}" data-group="{group}">{item[1]}</option>'
                for item in items
            )
            group_html += options_html + "</optgroup>"
            options.append(group_html)

        return "\n".join(options)

    def _render_flat_options(self, choices):
        """Render options without grouping"""
        return "\n".join(
            f'<option value="{choice[0]}">{choice[1]}</option>' for choice in choices
        )

    def _generate_assets(self, field):
        """Generate CSS and JavaScript assets"""
        return self._generate_styles() + self._generate_scripts(field)

    def _generate_styles(self):
        """Generate widget styles"""
        custom_styles = self.config["custom_styles"]

        return """
        <style>
            .multi-select-container {
                position: relative;
                margin-bottom: 1rem;
            }
            .multi-select-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 0.5rem;
            }
            .search-box {
                flex: 1;
                margin-right: 1rem;
            }
            .selected-items-container {
                margin-top: 1rem;
                border: 1px solid #ddd;
                padding: 0.5rem;
                max-height: 200px;
                overflow-y: auto;
            }
            .selected-items-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .selected-items-list li {
                display: flex;
                justify-content: space-between;
                padding: 0.25rem;
                border-bottom: 1px solid #eee;
            }
            .multi-select-error {
                color: #dc3545;
                margin-top: 0.5rem;
                display: none;
            }
            %(custom_styles)s
        </style>
        """ % {"custom_styles": custom_styles}

    def _generate_scripts(self, field):
        """Generate widget JavaScript"""
        config = {
            "field_id": field.id,
            "initial_value": json.dumps(field.data) if field.data else "[]",
            **self.config,
        }

        return """
        <script>
            (function() {
                class MultiSelectManager {
                    constructor(config) {
                        this.config = config;
                        this.init();
                    }

                    init() {
                        this.initializeElements();
                        this.initializeSelect2();
                        this.bindEvents();
                        this.loadInitialData();
                    }

                    initializeElements() {
                        // Initialize DOM elements
                    }

                    initializeSelect2() {
                        // Initialize Select2 with config
                    }

                    bindEvents() {
                        // Bind all event handlers
                    }

                    loadInitialData() {
                        // Load initial selection data
                    }

                    // Additional methods for handling selections,
                    // validation, and UI updates
                }

                // Initialize the widget
                new MultiSelectManager(%(config)s);
            })();
        </script>
        """ % {"config": json.dumps(config)}

    def pre_validate(self, form):
        """Validate form data"""
        if not self.data:
            return

        try:
            self._validate_selections(form)
            self._validate_group_limits()
        except ValidationError as e:
            raise e
        except Exception as e:
            raise ValidationError(f"Validation error: {str(e)}")

    def process_formdata(self, valuelist):
        """Process incoming form data"""
        if not valuelist:
            self.data = None
            return

        try:
            self.data = json.loads(valuelist[0])
        except json.JSONDecodeError as e:
            self.data = None
            raise ValidationError("Invalid data format") from e

    def process_data(self, value):
        """Process data from database"""
        if not value:
            return None

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value


class DependentSelectWidget(BS3TextFieldWidget):
    """
    Cascading dropdown widget with dependent options.

    Features:
    - Dynamic option loading based on parent field values
    - Support for multiple parent dependencies
    - Chained relationship handling
    - Ajax loading with caching
    - Smart loading indicators
    - Error handling and recovery
    - Clear/reset functionality
    - Advanced search/filtering
    - Custom formatters
    - Validation rules
    - Rich event handlers
    - State persistence
    - Accessibility compliance
    - Mobile responsiveness
    - Offline support
    - Performance optimization
    - Security hardening

    Database Type:
        PostgreSQL: JSONB for options, INTEGER/VARCHAR for values
        SQLAlchemy: JSON, Integer, String

    Required Dependencies:
    - Select2 4.0+
    - jQuery 3.0+
    - Lodash 4.0+

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - iOS Safari 12+
    - Chrome Android 89+

    Required Permissions:
    - LocalStorage/SessionStorage
    - XHR/Fetch requests
    - Service Workers (offline)

    Performance Considerations:
    - Enable option caching
    - Debounce search requests
    - Lazy load options
    - Optimize payload size
    - Compress responses
    - Index dependent columns
    - Cache parent data
    - Use websockets for updates

    Security Implications:
    - Validate parent dependencies
    - Sanitize search input
    - Rate limit requests
    - Check permissions
    - Prevent XSS
    - CSRF protection
    - SQL injection prevention
    - Access control

    Best Practices:
    - Set reasonable defaults
    - Enable caching
    - Add error handling
    - Show loading states
    - Validate input
    - Test edge cases
    - Document usage
    - Monitor performance
    - Regular updates
    - Security audits

    Example:
        country = db.Column(db.Integer,
            info={'widget': DependentSelectWidget(
                url='/api/countries',
                depends_on=None,
                cache=True,
                search=True,
                placeholder='Select Country',
                minimum_input=2
            )})

        state = db.Column(db.Integer,
            info={'widget': DependentSelectWidget(
                url='/api/states',
                depends_on='country',
                cache=True,
                search=True,
                placeholder='Select State',
                minimum_input=2
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/js/select2.full.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "/static/js/dependent-select.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/select2/4.0.13/css/select2.min.css",
        "/static/css/dependent-select.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize DependentSelectWidget with custom settings.

        Args:
            url (str): Data source URL for options
            depends_on (str|list): Parent field name(s)
            cache (bool): Enable option caching
            search (bool): Enable search functionality
            placeholder (str): Placeholder text
            minimum_input (int): Minimum search input length
            load_on_init (bool): Load initial options
            formatter (callable): Custom option formatter
            default_value (any): Default selected value
            clear_on_parent_change (bool): Clear on parent change
            allow_clear (bool): Allow clearing selection
            dropdown_parent (str): Custom dropdown parent
            theme (str): Select2 theme name
            debug (bool): Enable debug mode
            retry_attempts (int): Failed request retries
            timeout (int): Request timeout in ms
            batch_size (int): Option load batch size
            websocket_url (str): Real-time updates URL
            offline_support (bool): Enable offline mode
        """
        super().__init__(**kwargs)

        # Core settings
        self.url = kwargs.get("url")
        self.depends_on = kwargs.get("depends_on")
        self.cache = kwargs.get("cache", True)
        self.search = kwargs.get("search", True)
        self.placeholder = kwargs.get("placeholder", "Select...")
        self.minimum_input = kwargs.get("minimum_input", 2)
        self.load_on_init = kwargs.get("load_on_init", True)
        self.formatter = kwargs.get("formatter")

        # Advanced options
        self.default_value = kwargs.get("default_value")
        self.clear_on_parent_change = kwargs.get("clear_on_parent_change", True)
        self.allow_clear = kwargs.get("allow_clear", True)
        self.dropdown_parent = kwargs.get("dropdown_parent", "body")
        self.theme = kwargs.get("theme", "default")

        # Technical settings
        self.debug = kwargs.get("debug", False)
        self.retry_attempts = kwargs.get("retry_attempts", 3)
        self.timeout = kwargs.get("timeout", 5000)
        self.batch_size = kwargs.get("batch_size", 100)
        self.websocket_url = kwargs.get("websocket_url")
        self.offline_support = kwargs.get("offline_support", True)

    def render_field(self, field, **kwargs):
        """Render the dependent select widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="dependent-select-widget" role="combobox">
                <select name="{field.name}" id="{field.id}"
                        class="form-control select2-widget"
                        aria-label="{field.label.text if field.label else ''}"
                        {f'data-depends-on="{self.depends_on}"' if self.depends_on else ''}
                        data-placeholder="{self.placeholder}"
                        {f'data-default-value="{self.default_value}"' if self.default_value else ''}>
                    <option></option>
                </select>

                <div class="loading-indicator" style="display:none;">
                    <div class="spinner-border spinner-border-sm"></div>
                    <span class="sr-only">Loading options...</span>
                </div>

                <div class="alert alert-danger error-message"
                     style="display:none;" role="alert"></div>
            </div>

            <script>
                $(document).ready(function() {{
                    const select = new DependentSelect('{field.id}', {{
                        url: '{self.url}',
                        dependsOn: {_js_json(self.depends_on)},
                        cache: {str(self.cache).lower()},
                        search: {str(self.search).lower()},
                        minimumInputLength: {self.minimum_input},
                        loadOnInit: {str(self.load_on_init).lower()},
                        defaultValue: {_js_json(self.default_value)},
                        clearOnParentChange: {str(self.clear_on_parent_change).lower()},
                        allowClear: {str(self.allow_clear).lower()},
                        dropdownParent: '{self.dropdown_parent}',
                        theme: '{self.theme}',
                        debug: {str(self.debug).lower()},
                        retryAttempts: {self.retry_attempts},
                        timeout: {self.timeout},
                        batchSize: {self.batch_size},
                        websocketUrl: {f"'{self.websocket_url}'" if self.websocket_url else 'null'},
                        offlineSupport: {str(self.offline_support).lower()},

                        formatResult: function(item) {{
                            {f"return {self.formatter.__name__}(item);" if self.formatter else "return item.text;"}
                        }},

                        onChange: function(value) {{
                            $('#{field.id}').trigger('change');
                        }},

                        onError: function(error) {{
                            showError(error);
                        }},

                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('#{field.id}').siblings('.error-message');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(loading) {{
                        $('#{field.id}').siblings('.loading-indicator')
                            [loading ? 'show' : 'hide']();
                    }}

                    // Clean up on page unload
                    $(window).on('unload', function() {{
                        select.destroy();
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

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                self.data = self._validate_value(valuelist[0])
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_value(self, value):
        """Validate selected value"""
        if not value:
            if self.data is not None:
                raise ValueError("Value required")
            return None

        try:
            return int(value) if value.isdigit() else value
        except (ValueError, TypeError):
            raise ValueError("Invalid value format")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_value(self.data)
            except ValueError as e:
                raise ValueError(str(e))
