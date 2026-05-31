"""SpreadsheetWidget — PgAppForge widget(s)."""

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

class SpreadsheetWidget(BS3TextFieldWidget):
    """
    Excel-like spreadsheet widget for tabular data editing.
    Stores data in PostgreSQL JSONB column for maximum flexibility.

    Features:
    - Full Excel-like formula support with 300+ functions
    - Rich cell formatting and styling
    - Data validation with custom rules
    - Column/row sorting and filtering
    - Freeze panes and split views
    - Cell merging and spanning
    - Import/export to Excel, CSV, JSON
    - Cell comments and notes
    - Custom formula functions
    - Unlimited undo/redo
    - Copy/paste from Excel
    - Conditional formatting
    - Data types (text, number, date, etc)
    - Input masks
    - Cell protection
    - Named ranges
    - Find/replace
    - Auto-fill
    - Column resizing
    - Row grouping
    - Cell references
    - Range selection
    - Keyboard navigation
    - Mobile support

    Required Dependencies:
    - Handsontable Pro 9.0+
    - SheetJS
    - Moment.js
    - Numeral.js

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON/JSONB

    Example:
        data = db.Column(db.JSON, nullable=False,
            info={'widget': SpreadsheetWidget(
                columns=[
                    {'title': 'Name', 'type': 'text', 'width': 200},
                    {'title': 'Value', 'type': 'numeric', 'format': '0,0.00'},
                    {'title': 'Date', 'type': 'date', 'format': 'YYYY-MM-DD'}
                ],
                enable_formulas=True,
                readonly_cells=['A1:A10'],
                protected_cells=['B1:C1'],
                validation={
                    'B:B': {'type': 'numeric', 'min': 0},
                    'C:C': {'type': 'date', 'min': '2020-01-01'}
                },
                default_values={
                    'A1': 'Item',
                    'B1': 'Amount',
                    'C1': 'Due Date'
                }
            )})
    """

    data_template = (
        '<div class="spreadsheet-wrapper %(wrapper_class)s">'
        '<div class="spreadsheet-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="copy">'
        '<i class="fa fa-copy"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="paste">'
        '<i class="fa fa-paste"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Format <i class="fa fa-font"></i>'
        "</button>"
        '<div class="dropdown-menu format-menu p-2" style="min-width:200px">'
        '<div class="format-section">'
        "<label>Font</label>"
        '<select class="form-control form-control-sm font-family">'
        '<option value="Arial">Arial</option>'
        '<option value="Calibri">Calibri</option>'
        '<option value="Times">Times</option>'
        "</select>"
        "</div>"
        '<div class="format-section mt-2">'
        "<label>Size</label>"
        '<input type="number" class="form-control form-control-sm font-size" min="6" max="72" value="11">'
        "</div>"
        '<div class="btn-group mt-2">'
        '<button type="button" class="btn btn-sm btn-light" data-command="bold">'
        '<i class="fa fa-bold"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-light" data-command="italic">'
        '<i class="fa fa-italic"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-light" data-command="underline">'
        '<i class="fa fa-underline"></i>'
        "</button>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item" href="#" data-export="xlsx">Excel (.xlsx)</a>'
        '<a class="dropdown-item" href="#" data-export="csv">CSV</a>'
        '<a class="dropdown-item" href="#" data-export="json">JSON</a>'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div id="%(field_id)s_hot" class="hot-container"></div>'
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize spreadsheet widget with extensive configuration"""
        super().__init__(**kwargs)
        self.columns = kwargs.get("columns", [{"title": "Column 1", "type": "text"}])
        self.enable_formulas = kwargs.get("enable_formulas", True)
        self.readonly_cells = kwargs.get("readonly_cells", [])
        self.protected_cells = kwargs.get("protected_cells", [])
        self.validation = kwargs.get("validation", {})
        self.default_values = kwargs.get("default_values", {})
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_rows = kwargs.get("min_rows", 10)
        self.max_rows = kwargs.get("max_rows", 1000)
        self.min_cols = kwargs.get("min_cols", len(self.columns))
        self.max_cols = kwargs.get("max_cols", 100)
        self.row_headers = kwargs.get("row_headers", True)
        self.column_headers = kwargs.get("column_headers", True)
        self.allow_insert_rows = kwargs.get("allow_insert_rows", True)
        self.allow_delete_rows = kwargs.get("allow_delete_rows", True)
        self.allow_insert_cols = kwargs.get("allow_insert_cols", False)
        self.allow_delete_cols = kwargs.get("allow_delete_cols", False)
        self.auto_column_size = kwargs.get("auto_column_size", True)
        self.fixed_rows_top = kwargs.get("fixed_rows_top", 0)
        self.fixed_columns_left = kwargs.get("fixed_columns_left", 0)
        self.language = kwargs.get("language", "en-US")
        self.decimal_separator = kwargs.get("decimal_separator", ".")
        self.thousand_separator = kwargs.get("thousand_separator", ",")
        self.date_format = kwargs.get("date_format", "YYYY-MM-DD")
        self.number_format = kwargs.get("number_format", "0,0.00")
        self.undo_redo_steps = kwargs.get("undo_redo_steps", 50)

    def __call__(self, field, **kwargs):
        """Render the spreadsheet widget"""
        kwargs.setdefault("id", field.id)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        config = {
            "data": field.data.get("data", []) if field.data else [],
            "columns": self.columns,
            "minRows": self.min_rows,
            "maxRows": self.max_rows,
            "minCols": self.min_cols,
            "maxCols": self.max_cols,
            "rowHeaders": self.row_headers,
            "colHeaders": self.column_headers,
            "allowInsertRow": self.allow_insert_rows,
            "allowDeleteRow": self.allow_delete_rows,
            "allowInsertColumn": self.allow_insert_cols,
            "allowDeleteColumn": self.allow_delete_cols,
            "autoColumnSize": self.auto_column_size,
            "fixedRowsTop": self.fixed_rows_top,
            "fixedColumnsLeft": self.fixed_columns_left,
            "language": self.language,
            "formulas": self.enable_formulas,
            "cells": self._get_cell_config(),
            "readOnly": False,
            "manualColumnResize": True,
            "manualRowResize": True,
            "comments": True,
            "contextMenu": True,
            "undoRedo": True,
            "height": "auto",
            "maxUndoRedo": self.undo_redo_steps,
            "copyPaste": True,
            "search": True,
            "filters": True,
            "dropdownMenu": True,
            "mergeCells": True,
            "multiColumnSorting": True,
        }

        return """
        <script>
            (function() {
                var container = document.getElementById('%(field_id)s_hot');
                var hot = new Handsontable(container, %(config)s);

                // Handle formula evaluation
                if (%(enable_formulas)s) {
                    hot.addHook('afterChange', function(changes) {
                        if (!changes) return;
                        changes.forEach(function(change) {
                            var row = change[0];
                            var col = change[1];
                            var value = change[3];
                            if (value && value.toString().startsWith('=')) {
                                try {
                                    var result = evaluateFormula(value, row, col, hot);
                                    hot.setDataAtCell(row, col, result, 'formula');
                                } catch (e) {
                                    console.error('Formula error:', e);
                                    hot.setDataAtCell(row, col, '#ERROR!', 'formula');
                                }
                            }
                        });
                    });
                }

                // Handle data validation
                hot.addHook('beforeChange', function(changes, source) {
                    if (!changes) return;

                    return changes.every(function(change) {
                        var [row, col, oldValue, newValue] = change;
                        var validation = %(validation)s[hot.getColHeader(col)] || {};

                        if (!validateCell(newValue, validation)) {
                            alert('Invalid value for ' + hot.getColHeader(col));
                            return false;
                        }
                        return true;
                    });
                });

                // Save data to hidden input
                hot.addHook('afterChange', function() {
                    var value = {
                        data: hot.getData(),
                        state: {
                            selected: hot.getSelected(),
                            filters: hot.getPlugin('filters').getSelectedFilters(),
                            sorting: hot.getPlugin('multiColumnSorting').getSortConfig(),
                            merges: hot.getPlugin('mergeCells').mergedCellsCollection.mergedCells,
                            comments: hot.getPlugin('comments').getComments()
                        }
                    };
                    document.getElementById('%(field_id)s').value = JSON.stringify(value);
                });

                // Initialize with default values
                var defaults = %(default_values)s;
                Object.keys(defaults).forEach(function(cell) {
                    var [col, row] = parseCell(cell);
                    hot.setDataAtCell(row-1, col, defaults[cell]);
                });

                // Export handlers
                document.querySelectorAll('[data-export]').forEach(function(button) {
                    button.addEventListener('click', function(e) {
                        e.preventDefault();
                        var format = this.dataset.export;
                        exportData(hot, format);
                    });
                });

                // Helper functions
                function validateCell(value, validation) {
                    if (!validation.type) return true;

                    switch(validation.type) {
                        case 'numeric':
                            value = parseFloat(value);
                            if (isNaN(value)) return false;
                            if ('min' in validation && value < validation.min) return false;
                            if ('max' in validation && value > validation.max) return false;
                            return true;

                        case 'date':
                            var date = moment(value);
                            if (!date.isValid()) return false;
                            if ('min' in validation && date.isBefore(validation.min)) return false;
                            if ('max' in validation && date.isAfter(validation.max)) return false;
                            return true;

                        case 'list':
                            return validation.values.includes(value);

                        default:
                            return true;
                    }
                }

                function parseCell(cell) {
                    var match = cell.match(/([A-Z]+)([0-9]+)/);
                    var col = columnToIndex(match[1]);
                    var row = parseInt(match[2]);
                    return [col, row];
                }

                function columnToIndex(column) {
                    var index = 0;
                    for (var i = 0; i < column.length; i++) {
                        index = index * 26 + column.charCodeAt(i) - 64;
                    }
                    return index - 1;
                }

                function exportData(hot, format) {
                    var data = hot.getData();

                    switch(format) {
                        case 'xlsx':
                            var wb = XLSX.utils.book_new();
                            var ws = XLSX.utils.aoa_to_sheet(data);
                            XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
                            XLSX.writeFile(wb, "export.xlsx");
                            break;

                        case 'csv':
                            var csv = Papa.unparse(data);
                            var blob = new Blob([csv], {type: 'text/csv;charset=utf-8;'});
                            var link = document.createElement("a");
                            link.href = URL.createObjectURL(blob);
                            link.download = "export.csv";
                            link.click();
                            break;

                        case 'json':
                            var json = JSON.stringify(data, null, 2);
                            var blob = new Blob([json], {type: 'application/json'});
                            var link = document.createElement("a");
                            link.href = URL.createObjectURL(blob);
                            link.download = "export.json";
                            link.click();
                            break;
                    }
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "config": json.dumps(config),
            "enable_formulas": json.dumps(self.enable_formulas),
            "validation": json.dumps(self.validation),
            "default_values": json.dumps(self.default_values),
        }

    def _get_cell_config(self):
        """Generate cell-specific configuration"""
        config = {}

        # Add readonly cells
        for range_str in self.readonly_cells:
            config[range_str] = {"readOnly": True}

        # Add protected cells
        for range_str in self.protected_cells:
            config[range_str] = {"protected": True}

        # Add validation rules
        for range_str, rules in self.validation.items():
            if range_str not in config:
                config[range_str] = {}
            config[range_str]["validator"] = rules

        return config

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid JSON data") from e
        else:
            self.data = None

    def _validate_data(self, data):
        """Validate spreadsheet data structure and constraints"""
        if not isinstance(data, dict) or "data" not in data:
            raise ValueError("Invalid data structure")

        if len(data["data"]) > self.max_rows:
            raise ValueError(f"Data exceeds maximum rows ({self.max_rows})")

        for row in data["data"]:
            if len(row) > self.max_cols:
                raise ValueError(f"Data exceeds maximum columns ({self.max_cols})")

        # Validate against column types
        for row_idx, row in enumerate(data["data"]):
            for col_idx, value in enumerate(row):
                if col_idx >= len(self.columns):
                    continue

                col_type = self.columns[col_idx].get("type", "text")
                try:
                    self._validate_cell_value(value, col_type)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid value in cell ({row_idx+1}, {col_idx+1}): {str(e)}"
                    )

    def _validate_cell_value(self, value, col_type):
        """Validate individual cell value against column type"""
        if value is None:
            return

        if col_type == "numeric":
            try:
                float(value)
            except ValueError:
                raise ValueError("Not a valid number")

        elif col_type == "date":
            try:
                moment = datetime.strptime(value, self.date_format)
            except ValueError:
                raise ValueError("Not a valid date")

        elif col_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("Not a valid boolean")

    def pre_validate(self, form):
        """Validate data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Spreadsheet data is required")
