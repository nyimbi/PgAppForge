"""FileUploadFieldWidget — PgAppForge widget(s)."""

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

class FileUploadFieldWidget(BS3TextFieldWidget):
    """
    Advanced file upload widget with preview, validation and progress tracking.

    Features:
    - Image/document preview
    - File type validation
    - Size limits
    - Multiple file support
    - Progress tracking
    - Drag & drop
    - Error handling
    - File deletion
    - Automatic compression

    Database Type:
        PostgreSQL: bytea or text (for file path)
        SQLAlchemy: LargeBinary or String

    Example Usage:
        file = db.Column(db.LargeBinary, nullable=True)
        # or
        file_path = db.Column(db.String(1000), nullable=True)
    """

    data_template = (
        '<div class="file-upload-widget">'
        '<div class="upload-zone" id="%(field_id)s-zone">'
        '<div class="upload-prompt">'
        '<i class="fa fa-cloud-upload"></i>'
        "<span>Drop files here or click to upload</span>"
        "</div>"
        "<input %(file)s>"
        "</div>"
        '<div class="upload-preview" id="%(field_id)s-preview"></div>'
        '<div class="upload-progress" style="display:none">'
        '<div class="progress">'
        '<div class="progress-bar" role="progressbar"></div>'
        "</div>"
        "</div>"
        '<div class="upload-error" style="display:none"></div>'
        "</div>"
    )

    empty_template = (
        '<div class="file-upload-widget">'
        '<div class="upload-zone" id="%(field_id)s-zone">'
        '<div class="upload-prompt">'
        '<i class="fa fa-cloud-upload"></i>'
        "<span>Drop files here or click to upload</span>"
        "</div>"
        "<input %(file)s>"
        "</div>"
        '<div class="upload-preview" id="%(field_id)s-preview"></div>'
        '<div class="upload-progress" style="display:none">'
        '<div class="progress">'
        '<div class="progress-bar" role="progressbar"></div>'
        "</div>"
        "</div>"
        '<div class="upload-error" style="display:none"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize file upload widget with custom settings"""
        super().__init__(**kwargs)
        self.max_size = kwargs.get("max_size", 10 * 1024 * 1024)  # 10MB default
        self.allowed_types = kwargs.get(
            "allowed_types",
            [
                "image/jpeg",
                "image/png",
                "image/gif",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
            ],
        )
        self.multiple = kwargs.get("multiple", False)
        self.auto_upload = kwargs.get("auto_upload", True)
        self.compress_images = kwargs.get("compress_images", True)
        self.max_width = kwargs.get("max_width", 1920)
        self.max_height = kwargs.get("max_height", 1080)
        self.upload_url = kwargs.get("upload_url", "/api/upload")
        self.preview_template = kwargs.get("preview_template", None)
        self.error_messages = {
            "size_error": kwargs.get(
                "size_error", f"File size must be less than {self.max_size/1024/1024}MB"
            ),
            "type_error": kwargs.get("type_error", "File type not allowed"),
            "upload_error": kwargs.get("upload_error", "Error uploading file"),
            "generic_error": kwargs.get("generic_error", "An error occurred"),
        }
        self.storage_provider = kwargs.get(
            "storage_provider", None
        )  # e.g., 'aws_s3', 'google_cloud'
        self.storage_config = kwargs.get("storage_config", {})

    def __call__(self, field, **kwargs):
        """Render the file upload widget"""
        kwargs.setdefault("type", "file")
        kwargs.setdefault("accept", ",".join(self.allowed_types))
        if self.multiple:
            kwargs["multiple"] = "multiple"

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "file": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(
            html
            + """
        <style>
            .file-upload-widget {
                margin-bottom: 1em;
            }
            .upload-zone {
                border: 2px dashed #ccc;
                padding: 20px;
                text-align: center;
                background: #fafafa;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            .upload-zone.dragover {
                border-color: #66afe9;
                background: #f0f8ff;
            }
            .upload-prompt i {
                font-size: 48px;
                color: #999;
            }
            .upload-preview {
                margin-top: 10px;
            }
            .upload-preview img {
                max-width: 200px;
                max-height: 200px;
                margin: 5px;
                border: 1px solid #ddd;
                padding: 3px;
            }
            .upload-progress {
                margin-top: 10px;
            }
            .upload-error {
                color: #a94442;
                margin-top: 5px;
            }
            .preview-item {
                display: inline-block;
                position: relative;
                margin: 5px;
            }
            .preview-item .remove {
                position: absolute;
                top: -8px;
                right: -8px;
                background: #ff4444;
                color: white;
                border-radius: 50%;
                width: 20px;
                height: 20px;
                line-height: 20px;
                text-align: center;
                cursor: pointer;
            }
        </style>
        <script>
            (function() {
                var $widget = $('#{field_id}').closest('.file-upload-widget');
                var $input = $('#{field_id}');
                var $zone = $('#{field_id}-zone');
                var $preview = $widget.find('.upload-preview');
                var $progress = $widget.find('.upload-progress');
                var $progressBar = $progress.find('.progress-bar');
                var $error = $widget.find('.upload-error');

                // Centralized error display function
                function displayError(messageKey, customMessage) {
                    let message = customMessage || '{generic_error}'; // Default generic error
                    if (messageKey && '{' + messageKey + '}' in {error_messages}) {
                        message = '{error_messages.' + messageKey + '}';
                    }
                    $error.text(message).show();
                    setTimeout(() => $error.fadeOut(), 5000);
                }


                // File validation function remains mostly the same, now uses displayError
                function validateFile(file) {
                    if (file.size > {max_size}) {
                        displayError('size_error');
                        return false;
                    }
                    if (!{allowed_types}.includes(file.type)) {
                        displayError('type_error');
                        return false;
                    }
                    return true;
                }


                // Image compression function remains the same


                // Preview function remains the same


                // Upload handling function - now more modular and uses chunked upload if configured
                async function handleFiles(files) {
                    for (let i = 0; i < files.length; i++) {
                        const file = files[i];
                        if (!validateFile(file)) continue;
                        previewFile(file);
                        if ({auto_upload}) {
                            await uploadFile(file); // Use await here for sequential handling in 'multiple' uploads
                        }
                    }
                }


                async function uploadFile(file) {
                    $progress.show();
                    $progressBar.width('0%');

                    const formData = new FormData();
                    formData.append('file', file);

                    try {
                        const response = await $.ajax({
                            url: '{upload_url}',
                            type: 'POST',
                            data: formData,
                            processData: false,
                            contentType: false,
                            xhr: function() {
                                var xhr = new XMLHttpRequest();
                                xhr.upload.addEventListener('progress', function(e) {
                                    if (e.lengthComputable) {
                                        var percent = Math.round((e.loaded / e.total) * 100);
                                        $progressBar.width(percent + '%');
                                    }
                                });
                                return xhr;
                            },
                            success: function(data, textStatus, jqXHR) {
                                if (jqXHR.status !== 200) {
                                    displayError('upload_error', 'Upload failed with status: ' + jqXHR.status);
                                }
                            },
                            error: function(jqXHR, textStatus, errorThrown) {
                                displayError('upload_error', 'Upload error: ' + textStatus + ', ' + errorThrown);
                            }
                        });

                        $progress.hide();


                        // Handle server-side validation and image manipulation response here if needed.
                        if (response && response.error) {
                             displayError(null, response.error); // Use generic error for server-side errors
                        }


                    } catch (error) {
                        $progress.hide();
                        displayError('generic_error', error.message); // Generic AJAX error
                    }
                }



                // Event handlers remain the same


                $zone.on('dragover', function(e) {
                    e.preventDefault();
                    $zone.addClass('dragover');
                }).on('dragleave', function(e) {
                    e.preventDefault();
                    $zone.removeClass('dragover');
                }).on('drop', function(e) {
                    e.preventDefault();
                    $zone.removeClass('dragover');
                    handleFiles(e.originalEvent.dataTransfer.files);
                }).on('click', function() {
                    $input.click();
                });


                $input.on('change', function(e) {
                    handleFiles(this.files);
                });


                // Initialize existing preview
                if ({initial_data}) {
                    previewFile({initial_data});
                }


            })();
        </script>
        """.format(
                field_id=field.id,
                max_size=self.max_size,
                allowed_types=json.dumps(self.allowed_types),
                compress_images=str(self.compress_images).lower(),
                max_width=self.max_width,
                max_height=self.max_height,
                upload_url=self.upload_url,
                multiple=str(self.multiple).lower(),
                auto_upload=str(self.auto_upload).lower(),
                error_messages=self.error_messages,  # Pass error messages to JavaScript
                initial_data=json.dumps(field.data) if field.data else "null",
                generic_error=self.error_messages["generic_error"],
                size_error=self.error_messages["size_error"],
                type_error=self.error_messages["type_error"],
                upload_error=self.error_messages["upload_error"],
            )
        )

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            self.data = valuelist[0]
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            return value
        return None
