"""ImageCropWidget — PgAppForge widget(s)."""

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

@dataclass
class ImageProcessingConfig:
    """Configuration settings for image processing operations."""

    width: int
    height: int
    quality: float
    format: str
    optimize: bool = True
    progressive: bool = True
    keep_exif: bool = False


class ImageCropWidget(BS3TextFieldWidget):
    """
    Advanced widget for image upload with sophisticated cropping capabilities.

    This widget extends BS3TextFieldWidget to provide a full-featured image upload
    and manipulation interface. It supports various image processing operations,
    responsive design, and accessibility features.

    Features:
    - Interactive image cropping with touch/mouse support
    - Aspect ratio enforcement and presets (square, 16:9, 4:3, etc.)
    - Real-time preview generation with multiple sizes
    - Size constraints and validation
    - Format conversion (jpg, png, webp)
    - Quality/compression control
    - Background removal via AI segmentation
    - Rotation, flipping, zoom
    - Undo/redo history
    - Drag & drop upload
    - Mobile responsive
    - Accessibility support
    - Error handling
    - Image optimization

    Required Dependencies:
    - Cropper.js v1.5.12+
    - canvas-to-blob.js
    - Compressor.js (for optimization)
    - Remove.bg API (for background removal)

    Database Type:
        PostgreSQL: bytea for image data
                   jsonb for crop/edit metadata
        SQLAlchemy: LargeBinary + JSON
    """

    template = """
        <div class="image-crop-wrapper %(wrapper_class)s"
             data-min-width="%(min_width)s"
             data-min-height="%(min_height)s"
             data-max-width="%(max_width)s"
             data-max-height="%(max_height)s"
             data-aspect-ratio="%(aspect_ratio)s"
             data-max-file-size="%(max_file_size)s"
             data-allowed-formats="%(allowed_formats)s"
             data-enable-touch="%(enable_touch)s"
             data-zoom-ratio="%(zoom_ratio)s"
             data-rotation-step="%(rotation_step)s">

            <!-- File Input -->
            <input type="file" %(file_attrs)s style="display: none">

            <!-- Upload Zone -->
            <div class="upload-zone"
                 tabindex="0"
                 role="button"
                 aria-label="Upload image">
                <i class="fa fa-cloud-upload" aria-hidden="true"></i>
                <div class="upload-text">%(upload_text)s</div>
                <div class="upload-requirements small text-muted">%(requirements_text)s</div>
            </div>

            <!-- Cropper Interface -->
            <div class="cropper-wrapper" style="display: none">
                <div class="image-container">
                    <img src="" alt="Upload preview" class="crop-preview">
                </div>

                <!-- Preview Thumbnails -->
                <div class="preview-container mt-3">
                    <div class="row preview-thumbnails"></div>
                </div>

                <!-- Tool Buttons -->
                %(toolbar_buttons)s

                <!-- Aspect Ratio Controls -->
                %(aspect_ratio_controls)s

                <!-- Format and Quality Controls -->
                %(format_quality_controls)s

                <!-- Background Removal -->
                %(remove_bg_button)s

                <!-- Action Buttons -->
                <div class="action-buttons mt-3">
                    <button type="button" class="btn btn-secondary undo-btn" disabled>
                        <i class="fa fa-undo"></i> Undo
                    </button>
                    <button type="button" class="btn btn-secondary redo-btn" disabled>
                        <i class="fa fa-repeat"></i> Redo
                    </button>
                    <button type="button" class="btn btn-primary save-crop">
                        Apply Changes
                    </button>
                </div>
            </div>

            <!-- Progress Bar -->
            <div class="progress mt-2" style="display: none">
                <div class="progress-bar progress-bar-striped progress-bar-animated"
                     role="progressbar"></div>
            </div>

            <!-- Error Messages -->
            <div class="alert alert-danger error-message mt-2"
                 style="display: none"
                 role="alert"></div>

            <!-- Hidden Fields -->
            <input type="hidden" name="%(name)s" id="%(field_id)s">
            <input type="hidden" name="%(name)s_metadata" id="%(field_id)s_metadata">
        </div>
    """

    def __init__(
        self,
        aspect_ratio: Optional[float] = None,
        min_size: Tuple[int, int] = (50, 50),
        max_size: Tuple[int, int] = (2000, 2000),
        preview_sizes: List[Tuple[int, int]] = None,
        formats: List[str] = None,
        quality: float = 0.9,
        enable_bg_removal: bool = False,
        max_file_size: int = 5 * 1024 * 1024,  # 5MB
        wrapper_class: str = "",
        remove_bg_api_key: str = "",
        optimize_images: bool = True,
        auto_crop: bool = True,
        maintain_aspect_ratio: bool = True,
        enable_touch: bool = True,
        zoom_ratio: float = 0.1,
        rotation_step: int = 45,
        **kwargs,
    ):
        """
        Initialize the ImageCropWidget with comprehensive configuration options.

        Args:
            aspect_ratio: Fixed aspect ratio for cropping (e.g., 1.0 for square)
            min_size: Minimum dimensions (width, height) for the cropped image
            max_size: Maximum dimensions (width, height) for the cropped image
            preview_sizes: List of (width, height) tuples for preview thumbnails
            formats: List of allowed image formats (e.g., ['jpg', 'png', 'webp'])
            quality: JPEG/WebP quality setting (0.1 to 1.0)
            enable_bg_removal: Enable background removal feature
            max_file_size: Maximum allowed file size in bytes
            wrapper_class: Additional CSS classes for the widget wrapper
            remove_bg_api_key: API key for background removal service
            optimize_images: Enable automatic image optimization
            auto_crop: Enable automatic cropping suggestions
            maintain_aspect_ratio: Lock aspect ratio during cropping
            enable_touch: Enable touch gestures for mobile devices
            zoom_ratio: Zoom step size for zoom in/out
            rotation_step: Rotation angle step in degrees
        """
        super().__init__(**kwargs)

        # Store configuration
        self.aspect_ratio = aspect_ratio
        self.min_size = min_size
        self.max_size = max_size
        self.preview_sizes = preview_sizes or [(150, 150)]
        self.formats = formats or ["jpg", "png", "webp"]
        self.quality = quality
        self.enable_bg_removal = enable_bg_removal
        self.max_file_size = max_file_size
        self.wrapper_class = wrapper_class
        self.remove_bg_api_key = remove_bg_api_key
        self.optimize_images = optimize_images
        self.auto_crop = auto_crop
        self.maintain_aspect_ratio = maintain_aspect_ratio
        self.enable_touch = enable_touch
        self.zoom_ratio = zoom_ratio
        self.rotation_step = rotation_step

        # Validate configuration
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate widget configuration parameters."""
        if self.aspect_ratio is not None and self.aspect_ratio <= 0:
            raise ValueError("Aspect ratio must be positive")

        if any(dim <= 0 for dim in self.min_size + self.max_size):
            raise ValueError("Image dimensions must be positive")

        if self.min_size[0] > self.max_size[0] or self.min_size[1] > self.max_size[1]:
            raise ValueError("Minimum size cannot exceed maximum size")

        if not 0.1 <= self.quality <= 1.0:
            raise ValueError("Quality must be between 0.1 and 1.0")

        if not self.formats:
            raise ValueError("At least one image format must be specified")

        if not all(
            fmt.lower() in ["jpg", "jpeg", "png", "webp"] for fmt in self.formats
        ):
            raise ValueError("Unsupported image format specified")

    def __call__(self, field, **kwargs) -> str:
        """
        Render the image crop widget with all features and dependencies.

        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes for the file input

        Returns:
            str: Rendered HTML for the widget
        """
        # Set up basic field attributes
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("accept", "image/*")
        if field.flags.required:
            kwargs["required"] = True

        # Prepare template variables
        template_vars = {
            "wrapper_class": self.wrapper_class,
            "min_width": self.min_size[0],
            "min_height": self.min_size[1],
            "max_width": self.max_size[0],
            "max_height": self.max_size[1],
            "aspect_ratio": str(self.aspect_ratio or ""),
            "max_file_size": self.max_file_size,
            "allowed_formats": ",".join(self.formats),
            "enable_touch": str(self.enable_touch).lower(),
            "zoom_ratio": self.zoom_ratio,
            "rotation_step": self.rotation_step,
            "file_attrs": self.html_params(**kwargs),
            "name": field.name,
            "field_id": kwargs["id"],
            "upload_text": "Drag & drop or click to upload",
            "requirements_text": self._get_requirements_text(),
            "toolbar_buttons": self._render_toolbar(),
            "aspect_ratio_controls": self._render_aspect_ratio_controls(),
            "format_quality_controls": self._render_format_quality_controls(),
            "remove_bg_button": self._render_remove_bg_button(),
        }

        # Render template and attach scripts
        html = self.template % template_vars
        return Markup(html + self._get_widget_scripts(field))

    def _get_requirements_text(self) -> str:
        """Generate text describing upload requirements."""
        reqs = [
            f"Formats: {', '.join(self.formats)}",
            f"Max size: {self._format_file_size(self.max_file_size)}",
            f"Min dimensions: {self.min_size[0]}x{self.min_size[1]}px",
        ]
        return " • ".join(reqs)

    def _render_toolbar(self) -> str:
        """Render the image editing toolbar."""
        buttons = [
            ("rotate-left", "Rotate Left", "fa-rotate-left"),
            ("rotate-right", "Rotate Right", "fa-rotate-right"),
            ("flip-horizontal", "Flip Horizontal", "fa-arrows-h"),
            ("flip-vertical", "Flip Vertical", "fa-arrows-v"),
            ("zoom-in", "Zoom In", "fa-search-plus"),
            ("zoom-out", "Zoom Out", "fa-search-minus"),
            ("reset", "Reset", "fa-refresh"),
        ]

        html = ['<div class="toolbar btn-group mt-3">']
        for cls, title, icon in buttons:
            html.append(f"""
                <button type="button"
                        class="btn btn-sm btn-outline-secondary {cls}"
                        title="{title}">
                    <i class="fa {icon}"></i>
                </button>
            """)
        html.append("</div>")
        return "".join(html)

    def _render_aspect_ratio_controls(self) -> str:
        """Render aspect ratio selection buttons."""
        ratios = [
            ("1", "1:1", "Square"),
            ("1.7778", "16:9", "Widescreen"),
            ("1.3333", "4:3", "Standard"),
            ("0", "Free", "Free Form"),
        ]

        html = ['<div class="aspect-ratios btn-group mt-2">']
        for value, label, title in ratios:
            html.append(f"""
                <button type="button"
                        class="btn btn-sm btn-outline-secondary"
                        data-ratio="{value}"
                        title="{title}">
                    {label}
                </button>
            """)
        html.append("</div>")
        return "".join(html)

    def _render_format_quality_controls(self) -> str:
        """Render format and quality control inputs."""
        format_options = "".join(
            f'<option value="{fmt}">{fmt.upper()}</option>' for fmt in self.formats
        )

        return f"""
            <div class="format-quality mt-3">
                <select class="form-control form-control-sm format-select">
                    {format_options}
                </select>
                <input type="range"
                       class="form-control-range quality-slider"
                       min="0.1"
                       max="1.0"
                       step="0.1"
                       value="{self.quality}">
                <div class="quality-label small text-muted">
                    Quality: <span>{self.quality}</span>
                </div>
            </div>
        """

    def _render_remove_bg_button(self) -> str:
        """Render background removal button if enabled."""
        if not self.enable_bg_removal:
            return ""

        return """
            <button type="button"
                    class="btn btn-secondary btn-block remove-bg mt-2">
                Remove Background
            </button>
        """

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ["B", "KB", "MB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} GB"

    def _get_widget_scripts(self, field) -> str:
        """
        Generate JavaScript code for widget functionality.

        Includes initialization of Cropper.js, event handlers, and all interactive features.

        Args:
            field: The form field being rendered

        Returns:
            str: JavaScript code as a string
        """
        # Configuration object for JavaScript
        config = {
            "fieldName": field.name,
            "fieldId": field.id,
            "aspectRatio": self.aspect_ratio,
            "minSize": list(self.min_size),
            "maxSize": list(self.max_size),
            "previewSizes": self.preview_sizes,
            "formats": self.formats,
            "quality": self.quality,
            "enableBgRemoval": self.enable_bg_removal,
            "maxFileSize": self.max_file_size,
            "optimizeImages": self.optimize_images,
            "autoCrop": self.auto_crop,
            "maintainAspectRatio": self.maintain_aspect_ratio,
            "enableTouch": self.enable_touch,
            "zoomRatio": self.zoom_ratio,
            "rotationStep": self.rotation_step,
            "removeBgApiKey": self.remove_bg_api_key,
        }

        return f"""
        <script>
        (function() {{
            // Initialize widget when DOM is ready
            document.addEventListener('DOMContentLoaded', function() {{
                const config = {_js_json(config)};
                const wrapper = document.querySelector('.image-crop-wrapper[data-field-id="{field.id}"]');
                if (!wrapper) return;

                let cropper = null;
                let history = [];
                let historyIndex = -1;

                // Cache DOM elements
                const fileInput = wrapper.querySelector('input[type="file"]');
                const uploadZone = wrapper.querySelector('.upload-zone');
                const cropperWrapper = wrapper.querySelector('.cropper-wrapper');
                const imageElement = wrapper.querySelector('.crop-preview');
                const progressBar = wrapper.querySelector('.progress');
                const errorMessage = wrapper.querySelector('.error-message');
                const dataInput = wrapper.querySelector(`#${field.id}`);
                const metadataInput = wrapper.querySelector(`#${field.id}_metadata`);

                // Initialize Cropper.js with options
                function initCropper(image) {{
                    return new Cropper(image, {{
                        aspectRatio: config.aspectRatio,
                        viewMode: 2,
                        dragMode: 'move',
                        autoCrop: config.autoCrop,
                        responsive: true,
                        restore: true,
                        checkCrossOrigin: true,
                        checkOrientation: true,
                        modal: true,
                        guides: true,
                        center: true,
                        highlight: true,
                        background: true,
                        autoCropArea: 0.8,
                        movable: true,
                        rotatable: true,
                        scalable: true,
                        zoomable: true,
                        zoomOnTouch: config.enableTouch,
                        zoomOnWheel: true,
                        wheelZoomRatio: config.zoomRatio,
                        cropBoxMovable: true,
                        cropBoxResizable: true,
                        toggleDragModeOnDblclick: true,
                        minContainerWidth: 200,
                        minContainerHeight: 100,
                        ready: function() {{
                            updatePreviewThumbnails();
                            addHistoryState();
                        }},
                        crop: function() {{
                            updatePreviewThumbnails();
                        }}
                    }});
                }}

                // File upload handling
                function handleFileUpload(file) {{
                    if (!validateFile(file)) return;

                    const reader = new FileReader();
                    reader.onload = function(e) {{
                        imageElement.src = e.target.result;
                        if (cropper) {{
                            cropper.destroy();
                        }}
                        cropper = initCropper(imageElement);
                        uploadZone.style.display = 'none';
                        cropperWrapper.style.display = 'block';
                    }};
                    reader.readAsDataURL(file);
                }}

                // File validation
                function validateFile(file) {{
                    const errors = [];

                    if (!file.type.startsWith('image/')) {{
                        errors.push('Please upload an image file.');
                    }}

                    if (file.size > config.maxFileSize) {{
                        errors.push(`File size must not exceed ${formatFileSize(config.maxFileSize)}.`);
                    }}

                    if (errors.length) {{
                        showError(errors.join(' '));
                        return false;
                    }}

                    return true;
                }}

                // Preview thumbnails
                function updatePreviewThumbnails() {{
                    if (!cropper) return;

                    const container = wrapper.querySelector('.preview-thumbnails');
                    container.innerHTML = '';

                    config.previewSizes.forEach(([width, height]) => {{
                        const div = document.createElement('div');
                        div.className = 'col preview-box';
                        div.style.width = `${width}px`;
                        div.style.height = `${height}px`;

                        const img = document.createElement('img');
                        img.src = cropper.getCroppedCanvas({{
                            width: width,
                            height: height
                        }}).toDataURL();

                        div.appendChild(img);
                        container.appendChild(div);
                    }});
                }}

                // History management
                function addHistoryState() {{
                    const data = cropper.getData();
                    history = history.slice(0, historyIndex + 1);
                    history.push(data);
                    historyIndex++;
                    updateHistoryButtons();
                }}

                function undo() {{
                    if (historyIndex <= 0) return;
                    historyIndex--;
                    cropper.setData(history[historyIndex]);
                    updateHistoryButtons();
                }}

                function redo() {{
                    if (historyIndex >= history.length - 1) return;
                    historyIndex++;
                    cropper.setData(history[historyIndex]);
                    updateHistoryButtons();
                }}

                function updateHistoryButtons() {{
                    wrapper.querySelector('.undo-btn').disabled = historyIndex <= 0;
                    wrapper.querySelector('.redo-btn').disabled = historyIndex >= history.length - 1;
                }}

                // Image processing
                async function processImage(format, quality) {{
                    const canvas = cropper.getCroppedCanvas();

                    if (config.optimizeImages) {{
                        const compressor = new Compressor(canvas, {{
                            quality: quality,
                            mimeType: `image/${format}`,
                            convertSize: 5000000, // 5MB
                            success(result) {{
                                saveProcessedImage(result, format);
                            }},
                            error(err) {{
                                showError('Error optimizing image: ' + err.message);
                            }}
                        }});
                    }} else {{
                        canvas.toBlob(
                            blob => saveProcessedImage(blob, format),
                            `image/${format}`,
                            quality
                        );
                    }}
                }}

                // Background removal
                async function removeBackground() {{
                    if (!config.enableBgRemoval || !config.removeBgApiKey) return;

                    const canvas = cropper.getCroppedCanvas();
                    const blob = await new Promise(resolve => canvas.toBlob(resolve));

                    showProgress();

                    try {{
                        const formData = new FormData();
                        formData.append('image_file', blob);

                        const response = await fetch('https://api.remove.bg/v1.0/removebg', {{
                            method: 'POST',
                            headers: {{
                                'X-Api-Key': config.removeBgApiKey
                            }},
                            body: formData
                        }});

                        if (!response.ok) throw new Error('Background removal failed');

                        const resultBlob = await response.blob();
                        const url = URL.createObjectURL(resultBlob);

                        imageElement.src = url;
                        cropper.destroy();
                        cropper = initCropper(imageElement);
                    }} catch (error) {{
                        showError('Background removal failed: ' + error.message);
                    }} finally {{
                        hideProgress();
                    }}
                }}

                // Utility functions
                function showError(message) {{
                    errorMessage.textContent = message;
                    errorMessage.style.display = 'block';
                    setTimeout(() => {{
                        errorMessage.style.display = 'none';
                    }}, 5000);
                }}

                function showProgress() {{
                    progressBar.style.display = 'block';
                }}

                function hideProgress() {{
                    progressBar.style.display = 'none';
                }}

                function formatFileSize(bytes) {{
                    const units = ['B', 'KB', 'MB', 'GB'];
                    let size = bytes;
                    let unitIndex = 0;

                    while (size >= 1024 && unitIndex < units.length - 1) {{
                        size /= 1024;
                        unitIndex++;
                    }}

                    return `${{size.toFixed(1)}} ${{units[unitIndex]}}`;
                }}

                // Event Listeners
                fileInput.addEventListener('change', function(e) {{
                    if (e.target.files && e.target.files[0]) {{
                        handleFileUpload(e.target.files[0]);
                    }}
                }});

                uploadZone.addEventListener('click', function() {{
                    fileInput.click();
                }});

                uploadZone.addEventListener('dragover', function(e) {{
                    e.preventDefault();
                    this.classList.add('dragover');
                }});

                uploadZone.addEventListener('dragleave', function() {{
                    this.classList.remove('dragover');
                }});

                uploadZone.addEventListener('drop', function(e) {{
                    e.preventDefault();
                    this.classList.remove('dragover');

                    if (e.dataTransfer.files && e.dataTransfer.files[0]) {{
                        handleFileUpload(e.dataTransfer.files[0]);
                    }}
                }});

                // Toolbar button handlers
                wrapper.querySelector('.rotate-left').addEventListener('click', () => {{
                    cropper.rotate(-config.rotationStep);
                    addHistoryState();
                }});

                wrapper.querySelector('.rotate-right').addEventListener('click', () => {{
                    cropper.rotate(config.rotationStep);
                    addHistoryState();
                }});

                wrapper.querySelector('.flip-horizontal').addEventListener('click', () => {{
                    cropper.scaleX(-cropper.getData().scaleX || -1);
                    addHistoryState();
                }});

                wrapper.querySelector('.flip-vertical').addEventListener('click', () => {{
                    cropper.scaleY(-cropper.getData().scaleY || -1);
                    addHistoryState();
                }});

                wrapper.querySelector('.zoom-in').addEventListener('click', () => {{
                    cropper.zoom(config.zoomRatio);
                    addHistoryState();
                }});

                wrapper.querySelector('.zoom-out').addEventListener('click', () => {{
                    cropper.zoom(-config.zoomRatio);
                    addHistoryState();
                }});

                wrapper.querySelector('.reset').addEventListener('click', () => {{
                    cropper.reset();
                    addHistoryState();
                }});

                // Aspect ratio buttons
                wrapper.querySelectorAll('.aspect-ratios button').forEach(button => {{
                    button.addEventListener('click', function() {{
                        const ratio = parseFloat(this.dataset.ratio) || NaN;
                        cropper.setAspectRatio(ratio);
                        addHistoryState();
                    }});
                }});

                // Format and quality controls
                const formatSelect = wrapper.querySelector('.format-select');
                const qualitySlider = wrapper.querySelector('.quality-slider');
                const qualityLabel = wrapper.querySelector('.quality-label span');

                formatSelect.addEventListener('change', function() {{
                    processImage(this.value, parseFloat(qualitySlider.value));
                }});

                qualitySlider.addEventListener('input', function() {{
                    qualityLabel.textContent = this.value;
                }});

                qualitySlider.addEventListener('change', function() {{
                    processImage(formatSelect.value, parseFloat(this.value));
                }});

                // Background removal button
                if (config.enableBgRemoval) {{
                    wrapper.querySelector('.remove-bg').addEventListener('click', removeBackground);
                }}

                // Undo/Redo buttons
                wrapper.querySelector('.undo-btn').addEventListener('click', undo);
                wrapper.querySelector('.redo-btn').addEventListener('click', redo);

                // Save button
                wrapper.querySelector('.save-crop').addEventListener('click', function() {{
                    const format = formatSelect.value;
                    const quality = parseFloat(qualitySlider.value);
                    processImage(format, quality);
                }});
            }});
        }})();
        </script>
        """
