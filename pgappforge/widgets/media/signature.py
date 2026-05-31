"""SignaturePadWidget — PgAppForge widget(s)."""

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

class SignaturePadWidget(BS3TextFieldWidget):
    """
    Widget for capturing digital signatures with drawing capabilities.

    Features:
    - Pressure sensitivity with multi-touch support
    - Multiple pen colors, sizes and styles
    - Clear/redo/undo functionality with history
    - Vector-based SVG storage for crisp scaling
    - PNG/SVG/JSON export options
    - Enhanced Signature validation (min points, speed, rhythm analysis)
    - Signature replay for verification and forensic analysis
    - Name attestation with optional field
    - Customizable pen styles and canvas backgrounds
    - Timestamp embedding and Audit trail logging
    - Improved error handling and user feedback
    - Accessibility enhancements for users with motor impairments

    Required Dependencies:
    - SignaturePad.js 2.3+ (for signature capture)
    - bezier.js (for signature smoothing)

    Database Type:
        PostgreSQL: jsonb (stores signature data, metadata, audit trail, and verification data)
        SQLAlchemy: JSON

    Example Usage:
        signature = db.Column(db.JSON, nullable=False,
            info={'widget': SignaturePadWidget(
                pen_color='#000000',
                pen_size=2,
                min_points=100, # Increased min_points for better security
                require_name=True,
                background_grid=True,
                allow_undo=True,
                store_audit_trail=True,
                enable_replay_verification=True # Enable replay verification
            )})
    """

    data_template = (
        '<div class="signature-pad-wrapper %(wrapper_class)s">'
        '<div class="signature-pad" style="background: %(background_color)s;">'  # Set background color from widget config
        '<canvas class="signature-pad-canvas"></canvas>'
        "</div>"
        '<div class="signature-controls mt-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary clear-signature" title="Clear" aria-label="Clear Signature">'  # Added ARIA labels for accessibility
        '<i class="fa fa-eraser"></i> Clear'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary undo-signature" title="Undo" aria-label="Undo Last Stroke" %(undo_disabled)s>'  # ARIA and disabled state for undo button
        '<i class="fa fa-undo"></i> Undo'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo-signature" title="Redo" aria-label="Redo Last Stroke" %(redo_disabled)s style="display:none;">'  # ARIA and hidden state for redo button
        '<i class="fa fa-redo"></i> Redo'
        "</button>"
        "</div>"
        '<div class="pen-controls btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle" data-toggle="dropdown" title="Pen Options" aria-haspopup="true" aria-expanded="false" aria-label="Pen Options">'  # ARIA labels for accessibility
        '<i class="fa fa-paint-brush"></i> Pen Options'
        "</button>"
        '<div class="dropdown-menu dropdown-menu-right">'  # Right align dropdown menu
        '<div class="px-3 py-2">'
        '<div class="form-group">'
        "<label for='%(field_id)s-pen-color'>Color</label>"  # Added labels for accessibility
        '<input type="color" class="form-control pen-color" id="%(field_id)s-pen-color" value="%(pen_color)s" aria-label="Pen Color">'
        "</div>"
        '<div class="form-group">'
        "<label for='%(field_id)s-pen-size'>Size</label>"  # Added labels for accessibility
        '<input type="range" class="form-control-range pen-size" id="%(field_id)s-pen-size" min="1" max="10" value="%(pen_size)s" aria-label="Pen Size">'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        "%(name_field)s"
        '<div class="signature-status mt-2" aria-live="polite" aria-atomic="true">'  # ARIA live region for status updates
        '<small class="text-muted status-text">Ready to sign</small>'
        '<div class="signature-error text-danger" style="display: none;"></div>'
        '<div class="signature-verification text-success" style="display: none;">Signature Verified</div>'  # Added verification message
        '<div class="signature-score text-info" style="display: none;"></div>'  # Added signature score display
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js",  # Updated SignaturePad.js CDN
        "https://cdn.jsdelivr.net/npm/bezier-js@3.1.0/bezier.min.js",  # Ensure bezier.js is included if used for smoothing
    ]

    CSS_DEPENDENCIES = [
        "/static/css/signature-pad-widget.css",  # Ensure custom CSS is included
    ]

    def __init__(self, **kwargs):
        """Initialize signature widget with extensive configuration options"""
        super().__init__(**kwargs)
        self.pen_color = kwargs.get("pen_color", "#000000")
        self.pen_size = kwargs.get("pen_size", 2)
        self.min_points = kwargs.get(
            "min_points", 100
        )  # Increased default for better security
        self.require_name = kwargs.get("require_name", False)
        self.background_grid = kwargs.get("background_grid", False)
        self.allow_undo = kwargs.get("allow_undo", True)
        self.allow_redo = kwargs.get("allow_redo", True)  # Enable redo functionality
        self.store_audit_trail = kwargs.get("store_audit_trail", True)
        self.enable_replay_verification = kwargs.get(
            "enable_replay_verification", False
        )  # Enable signature replay verification feature
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.canvas_width = kwargs.get("canvas_width", 500)
        self.canvas_height = kwargs.get("canvas_height", 200)
        self.max_points = kwargs.get("max_points", 10000)  # Increased max points
        self.throttle = kwargs.get("throttle", 16)  # ms between points
        self.min_speed = kwargs.get(
            "min_speed", 0.8
        )  # Increased min speed for stricter validation
        self.max_idle_time = kwargs.get(
            "max_idle_time", 5000
        )  # Max idle time in ms before validation fails
        self.pressure_support = kwargs.get("pressure_support", True)
        self.background_color = kwargs.get(
            "background_color", "#f8f9fa"
        )  # Customizable background color
        self.locale = kwargs.get("locale", "en")
        self.custom_validators = kwargs.get(
            "custom_validators", []
        )  # Accept custom validators

    def __call__(self, field, **kwargs):
        """Render the signature pad widget"""
        kwargs.setdefault("id", field.id)

        name_field = ""
        if self.require_name:
            name_field = """
                <div class="form-group mt-2">
                    <label for="%(field_id)s-signer-name">Signer Name (Optional)</label>
                    <input type="text" class="form-control signer-name" id="%(field_id)s-signer-name"
                           placeholder="Type your name (Optional)">
                </div>
            """ % {"field_id": field.id}  # Added label for screen readers

        html = (
            self.data_template
            % {
                "name": field.name,
                "field_id": field.id,
                "wrapper_class": self.wrapper_class,
                "pen_color": self.pen_color,
                "pen_size": self.pen_size,
                "name_field": name_field,
                "background_color": self.background_color,  # Pass background color to template
                "undo_disabled": ""
                if self.allow_undo
                else "disabled",  # Control disabled state of undo button
                "redo_disabled": ""
                if self.allow_redo
                else "disabled",  # Control disabled state of redo button
            }
        )

        return Markup(html + self._get_widget_scripts(field))

    # _get_widget_scripts = _get_widget_scripts


# {{REWRITTEN_CODE}}
