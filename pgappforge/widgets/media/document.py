"""DocumentViewerWidget — PgAppForge widget(s)."""

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

class DocumentViewerWidget(BS3TextFieldWidget):
    """
    Multi-format document viewer widget with annotations, thumbnails and advanced viewing features.
    Stores documents in PostgreSQL BYTEA column with metadata in JSONB.

    Features:
    - Multi-format support: PDF, Word, Excel, PowerPoint, Images
    - Rich annotation tools: highlights, notes, drawings, shapes
    - Page thumbnails with custom size/layout
    - Smooth zoom and pan controls
    - Full text search with highlights
    - Print with annotations
    - Version control
    - Download in multiple formats
    - Page rotation and reordering
    - Bookmark management
    - Mobile-optimized UI
    - Collaborative annotations
    - Signature support
    - Custom watermarks
    - Password protection
    - Accessibility features

    Database Schema:
        document = db.Column(db.LargeBinary, nullable=False)  # Document content
        metadata = db.Column(db.JSON, nullable=False)  # Document metadata
        annotations = db.Column(db.JSON)  # Annotation data
        versions = db.Column(db.JSON)  # Version history

    Required Dependencies:
    - PDF.js 2.0+
    - Mammoth.js (Word)
    - SheetJS (Excel)
    - Fabric.js (Annotations)
    - OpenSeadragon (Deep zoom)

    Example:
        document = db.Column(db.LargeBinary, nullable=False,
            info={'widget': DocumentViewerWidget(
                supported_formats=['pdf', 'docx', 'xlsx', 'pptx', 'png', 'jpg'],
                enable_annotations=True,
                annotation_tools=['highlight', 'note', 'draw', 'shape'],
                show_thumbnails=True,
                thumbnail_size=(120, 160),
                enable_search=True,
                enable_print=True,
                enable_download=True,
                watermark='Confidential',
                max_file_size=20*1024*1024,  # 20MB
                cache_enabled=True,
                mobile_optimization=True
            )})
    """

    data_template = (
        '<div class="document-viewer-wrapper %(wrapper_class)s">'
        '<div class="document-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomIn">'
        '<i class="fa fa-search-plus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomOut">'
        '<i class="fa fa-search-minus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="fitPage">'
        '<i class="fa fa-arrows-alt"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="rotateLeft">'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="rotateRight">'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="print">'
        '<i class="fa fa-print"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="download">'
        '<i class="fa fa-download"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2 annotation-tools" style="display:none">'
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="highlight">'
        '<i class="fa fa-highlighter"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="note">'
        '<i class="fa fa-sticky-note"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="draw">'
        '<i class="fa fa-pencil-alt"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-tool="shape">'
        '<i class="fa fa-shapes"></i>'
        "</button>"
        "</div>"
        "</div>"
        '<div class="document-container">'
        '<div class="thumbnails-panel" style="display:none"></div>'
        '<div id="%(field_id)s_viewer" class="viewer-container"></div>'
        '<div class="search-panel" style="display:none">'
        '<input type="text" class="form-control form-control-sm" placeholder="Search...">'
        '<div class="search-results"></div>'
        "</div>"
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<input type="file" style="display:none" id="%(field_id)s_file">'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize document viewer with configuration"""
        super().__init__(**kwargs)
        self.supported_formats = kwargs.get(
            "supported_formats", ["pdf", "docx", "xlsx", "pptx", "png", "jpg"]
        )
        self.enable_annotations = kwargs.get("enable_annotations", True)
        self.annotation_tools = kwargs.get(
            "annotation_tools", ["highlight", "note", "draw", "shape"]
        )
        self.show_thumbnails = kwargs.get("show_thumbnails", True)
        self.thumbnail_size = kwargs.get("thumbnail_size", (120, 160))
        self.enable_search = kwargs.get("enable_search", True)
        self.enable_print = kwargs.get("enable_print", True)
        self.enable_download = kwargs.get("enable_download", True)
        self.watermark = kwargs.get("watermark", "")
        self.max_file_size = kwargs.get("max_file_size", 20 * 1024 * 1024)
        self.cache_enabled = kwargs.get("cache_enabled", True)
        self.mobile_optimization = kwargs.get("mobile_optimization", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_zoom = kwargs.get("min_zoom", 0.25)
        self.max_zoom = kwargs.get("max_zoom", 4)
        self.rotation_step = kwargs.get("rotation_step", 90)
        self.page_gap = kwargs.get("page_gap", 20)
        self.default_scale = kwargs.get("default_scale", "auto")

    def __call__(self, field, **kwargs):
        """Render the document viewer widget"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("required", field.flags.required)

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        config = {
            "supportedFormats": self.supported_formats,
            "enableAnnotations": self.enable_annotations,
            "annotationTools": self.annotation_tools,
            "showThumbnails": self.show_thumbnails,
            "thumbnailSize": self.thumbnail_size,
            "enableSearch": self.enable_search,
            "enablePrint": self.enable_print,
            "enableDownload": self.enable_download,
            "watermark": self.watermark,
            "maxFileSize": self.max_file_size,
            "cacheEnabled": self.cache_enabled,
            "mobileOptimization": self.mobile_optimization,
            "minZoom": self.min_zoom,
            "maxZoom": self.max_zoom,
            "rotationStep": self.rotation_step,
            "pageGap": self.page_gap,
            "defaultScale": self.default_scale,
        }

        return """
        <script>
            (function() {
                var viewer = new DocumentViewer('#%(field_id)s_viewer', %(config)s);
                var field = document.getElementById('%(field_id)s');
                var fileInput = document.getElementById('%(field_id)s_file');

                // Handle initial document if present
                if (field.value) {
                    viewer.loadDocument(field.value);
                }

                // Handle file selection
                fileInput.addEventListener('change', function(e) {
                    var file = e.target.files[0];
                    if (!file) return;

                    // Validate file
                    if (!validateFile(file)) return;

                    var reader = new FileReader();
                    reader.onload = function(e) {
                        field.value = e.target.result;
                        viewer.loadDocument(e.target.result);
                    };
                    reader.readAsDataURL(file);
                });

                // Toolbar handlers
                document.querySelector('.document-toolbar').addEventListener('click', function(e) {
                    var command = e.target.closest('[data-command]');
                    if (command) {
                        var action = command.dataset.command;
                        switch(action) {
                            case 'zoomIn':
                                viewer.zoomIn();
                                break;
                            case 'zoomOut':
                                viewer.zoomOut();
                                break;
                            case 'fitPage':
                                viewer.fitToPage();
                                break;
                            case 'rotateLeft':
                                viewer.rotate(-%(rotation_step)d);
                                break;
                            case 'rotateRight':
                                viewer.rotate(%(rotation_step)d);
                                break;
                            case 'print':
                                viewer.print();
                                break;
                            case 'download':
                                viewer.download();
                                break;
                        }
                    }

                    var tool = e.target.closest('[data-tool]');
                    if (tool) {
                        viewer.setAnnotationTool(tool.dataset.tool);
                    }
                });

                // Search handler
                if (%(enable_search)s) {
                    var searchInput = document.querySelector('.search-panel input');
                    var searchTimeout;
                    searchInput.addEventListener('input', function() {
                        clearTimeout(searchTimeout);
                        var query = this.value;
                        searchTimeout = setTimeout(function() {
                            viewer.search(query);
                        }, 300);
                    });
                }

                function validateFile(file) {
                    // Check file size
                    if (file.size > %(max_file_size)d) {
                        alert('File size exceeds maximum allowed (' +
                              (%(max_file_size)d / (1024*1024)).toFixed(1) + 'MB)');
                        return false;
                    }

                    // Check file type
                    var ext = file.name.split('.').pop().toLowerCase();
                    if (!%(supported_formats)s.includes(ext)) {
                        alert('Unsupported file type. Allowed: ' +
                              %(supported_formats)s.join(', '));
                        return false;
                    }

                    return true;
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "config": json.dumps(config),
            "rotation_step": self.rotation_step,
            "enable_search": str(self.enable_search).lower(),
            "max_file_size": self.max_file_size,
            "supported_formats": json.dumps(self.supported_formats),
        }

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = valuelist[0]
                self._validate_document(self.data)
            except Exception as e:
                raise ValueError(f"Invalid document data: {str(e)}")
        else:
            self.data = None

    def _validate_document(self, data):
        """Validate document data"""
        if not data:
            return

        # Validate file size
        if len(data) > self.max_file_size:
            raise ValueError(
                f"Document size exceeds maximum allowed ({self.max_file_size/(1024*1024):.1f}MB)"
            )

        # Validate file type
        try:
            header = data[:50]  # Check file signature
            if not any(
                sig in header
                for sig in [
                    b"%PDF",  # PDF
                    b"PK\x03\x04",  # Office documents
                    b"\x89PNG",  # PNG
                    b"\xff\xd8\xff",  # JPEG
                ]
            ):
                raise ValueError("Invalid document format")
        except Exception as e:
            raise ValueError(f"Error validating document format: {str(e)}")

    def pre_validate(self, form):
        """Validate document before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Document is required")
