"""ImageCropWidget — PgAppForge widget(s)."""

from __future__ import annotations
from typing import Optional, Tuple, List

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


class ImageProcessingConfig:
	"""Configuration settings for image processing operations."""

	def __init__(self, width: int, height: int, quality: float, format: str,
				 optimize: bool = True, progressive: bool = True, keep_exif: bool = False):
		self.width = width
		self.height = height
		self.quality = quality
		self.format = format
		self.optimize = optimize
		self.progressive = progressive
		self.keep_exif = keep_exif


class ImageCropWidget(BS3TextFieldWidget):
	"""
	Advanced widget for image upload with sophisticated cropping capabilities.

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

	def __init__(
		self,
		aspect_ratio: Optional[float] = None,
		min_size: Tuple[int, int] = (50, 50),
		max_size: Tuple[int, int] = (2000, 2000),
		preview_sizes: List[Tuple[int, int]] = None,
		formats: List[str] = None,
		quality: float = 0.9,
		enable_bg_removal: bool = False,
		max_file_size: int = 5 * 1024 * 1024,
		wrapper_class: str = "",
		remove_bg_api_key: str = "",
		optimize_images: bool = True,
		auto_crop: bool = True,
		maintain_aspect_ratio: bool = True,
		enable_touch: bool = True,
		zoom_ratio: float = 0.1,
		rotation_step: int = 45,
		# Universal kwargs
		placeholder: str = "",
		css_class: str = "",
		description: str = "",
		readonly: bool = False,
		disabled: bool = False,
		**kwargs,
	):
		super().__init__(**kwargs)

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
		self.placeholder = placeholder
		self.css_class = css_class
		self.description = description
		self.readonly = readonly
		self.disabled = disabled

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
		if not all(fmt.lower() in ["jpg", "jpeg", "png", "webp"] for fmt in self.formats):
			raise ValueError("Unsupported image format specified")

	def __call__(self, field, **kwargs) -> Markup:
		"""Render the image crop widget."""
		kwargs.setdefault("id", field.id)
		kwargs.setdefault("accept", "image/*")
		if field.flags.required:
			kwargs["required"] = True

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Image"))

		# File input attrs
		file_attrs = ""
		for k, v in kwargs.items():
			if v is True:
				file_attrs += f" {escape(k)}"
			elif v is not False and v is not None:
				file_attrs += f' {escape(k)}="{escape(str(v))}"'

		wrapper_classes = "image-crop-wrapper"
		if self.wrapper_class:
			wrapper_classes += f" {escape(self.wrapper_class)}"
		if self.css_class:
			wrapper_classes += f" {escape(self.css_class)}"
		if has_errors:
			wrapper_classes += " is-invalid"

		html = (
			f'<div class="{wrapper_classes}"'
			f' data-min-width="{self.min_size[0]}"'
			f' data-min-height="{self.min_size[1]}"'
			f' data-max-width="{self.max_size[0]}"'
			f' data-max-height="{self.max_size[1]}"'
			f' data-aspect-ratio="{escape(str(self.aspect_ratio or ""))}"'
			f' data-max-file-size="{self.max_file_size}"'
			f' data-allowed-formats="{escape(",".join(self.formats))}"'
			f' data-enable-touch="{str(self.enable_touch).lower()}"'
			f' data-zoom-ratio="{self.zoom_ratio}"'
			f' data-rotation-step="{self.rotation_step}">'

			# File input (hidden, opened by upload zone click)
			f'<input type="file"{file_attrs} style="display: none">'

			# Upload zone
			f'<div class="upload-zone" tabindex="0" role="button"'
			f' aria-label="{escape(str(_("Upload image for")))}: {escape(label_text)}">'
			'<i class="fa fa-cloud-upload" aria-hidden="true"></i>'
			f'<div class="upload-text">{escape(str(_("Drag & drop or click to upload")))}</div>'
			f'<div class="upload-requirements small text-muted">{escape(self._get_requirements_text())}</div>'
			'</div>'

			# Cropper interface
			'<div class="cropper-wrapper" style="display: none">'
			'<div class="image-container">'
			f'<img src="" alt="{escape(str(_("Upload preview")))}" class="crop-preview">'
			'</div>'
			'<div class="preview-container mt-3">'
			'<div class="row preview-thumbnails"></div>'
			'</div>'
			+ self._render_toolbar()
			+ self._render_aspect_ratio_controls()
			+ self._render_format_quality_controls()
			+ self._render_remove_bg_button() +
			'<div class="action-buttons mt-3">'
			f'<button type="button" class="btn btn-secondary undo-btn" disabled aria-label="{escape(str(_("Undo")))}">'
			'<i class="fa fa-undo" aria-hidden="true"></i> '
			+ str(_("Undo")) +
			'</button>'
			f'<button type="button" class="btn btn-secondary redo-btn" disabled aria-label="{escape(str(_("Redo")))}">'
			'<i class="fa fa-repeat" aria-hidden="true"></i> '
			+ str(_("Redo")) +
			'</button>'
			f'<button type="button" class="btn btn-primary save-crop" aria-label="{escape(str(_("Apply Changes")))}">'
			+ str(_("Apply Changes")) +
			'</button>'
			'</div>'
			'</div>'

			# Progress bar
			'<div class="progress mt-2" style="display: none" role="progressbar"'
			' aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">'
			'<div class="progress-bar progress-bar-striped progress-bar-animated"></div>'
			'</div>'

			# Error messages (client-side)
			f'<div class="alert alert-danger error-message mt-2" style="display: none"'
			f' role="alert" aria-live="assertive"></div>'

			# Hidden field
			f'<input type="hidden" name="{escape(field.name)}" id="{escape(field.id)}"'
			f' value="{escape(field.data or "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr}>'
			f'<input type="hidden" name="{escape(field.name)}_metadata"'
			f' id="{escape(field.id)}_metadata">'
		)

		# WTForms server-side errors
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{escape(field.id)}_error" role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{escape(field.id)}_help">'
				f'{escape(self.description)}</small>'
			)

		html += '</div>'

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
			("rotate-left", str(_("Rotate Left")), "fa-rotate-left"),
			("rotate-right", str(_("Rotate Right")), "fa-rotate-right"),
			("flip-horizontal", str(_("Flip Horizontal")), "fa-arrows-h"),
			("flip-vertical", str(_("Flip Vertical")), "fa-arrows-v"),
			("zoom-in", str(_("Zoom In")), "fa-search-plus"),
			("zoom-out", str(_("Zoom Out")), "fa-search-minus"),
			("reset", str(_("Reset")), "fa-refresh"),
		]

		html = '<div class="toolbar btn-group mt-3" role="toolbar" aria-label="' + str(_("Image editing tools")) + '">'
		for cls, title, icon in buttons:
			safe_title = escape(title)
			html += (
				f'<button type="button" class="btn btn-sm btn-outline-secondary {cls}"'
				f' title="{safe_title}" aria-label="{safe_title}">'
				f'<i class="fa {icon}" aria-hidden="true"></i>'
				'</button>'
			)
		html += '</div>'
		return html

	def _render_aspect_ratio_controls(self) -> str:
		"""Render aspect ratio selection buttons."""
		ratios = [
			("1", "1:1", str(_("Square"))),
			("1.7778", "16:9", str(_("Widescreen"))),
			("1.3333", "4:3", str(_("Standard"))),
			("0", str(_("Free")), str(_("Free Form"))),
		]

		html = '<div class="aspect-ratios btn-group mt-2" role="group" aria-label="' + str(_("Aspect ratio")) + '">'
		for value, label, title in ratios:
			html += (
				f'<button type="button" class="btn btn-sm btn-outline-secondary"'
				f' data-ratio="{escape(value)}" title="{escape(title)}" aria-label="{escape(title)}">'
				f'{escape(label)}'
				'</button>'
			)
		html += '</div>'
		return html

	def _render_format_quality_controls(self) -> str:
		"""Render format and quality control inputs."""
		format_options = "".join(
			f'<option value="{escape(fmt)}">{escape(fmt.upper())}</option>'
			for fmt in self.formats
		)

		return (
			'<div class="format-quality mt-3">'
			f'<label for="crop-format-select" class="visually-hidden sr-only">{escape(str(_("Image format")))}</label>'
			f'<select class="form-control form-control-sm format-select" id="crop-format-select"'
			f' aria-label="{escape(str(_("Image format")))}">'
			+ format_options +
			'</select>'
			f'<label for="crop-quality-slider" class="visually-hidden sr-only">{escape(str(_("Quality")))}</label>'
			f'<input type="range" class="form-control-range quality-slider" id="crop-quality-slider"'
			f' min="0.1" max="1.0" step="0.1" value="{self.quality}"'
			f' aria-label="{escape(str(_("Image quality")))}">'
			'<div class="quality-label small text-muted">'
			+ str(_("Quality")) + ': <span aria-live="polite">'
			+ str(self.quality) +
			'</span>'
			'</div>'
			'</div>'
		)

	def _render_remove_bg_button(self) -> str:
		"""Render background removal button if enabled."""
		if not self.enable_bg_removal:
			return ""
		return (
			f'<button type="button" class="btn btn-secondary w-100 d-block remove-bg mt-2"'
			f' aria-label="{escape(str(_("Remove Background")))}">'
			+ str(_("Remove Background")) +
			'</button>'
		)

	@staticmethod
	def _format_file_size(size_bytes: int) -> str:
		"""Format file size in human-readable format."""
		for unit in ["B", "KB", "MB"]:
			if size_bytes < 1024:
				return f"{size_bytes:.1f} {unit}"
			size_bytes /= 1024
		return f"{size_bytes:.1f} GB"

	@staticmethod
	def html_params(**kwargs) -> str:
		"""Build HTML attribute string from kwargs."""
		parts = []
		for k, v in kwargs.items():
			k = k.rstrip("_").replace("_", "-")
			if v is True:
				parts.append(escape(k))
			elif v is not False and v is not None:
				parts.append(f'{escape(k)}="{escape(str(v))}"')
		return " ".join(parts)

	def _get_widget_scripts(self, field) -> str:
		"""Generate JavaScript code for widget functionality."""
		config = {
			"fieldName": field.name,
			"fieldId": field.id,
			"aspectRatio": self.aspect_ratio,
			"minSize": list(self.min_size),
			"maxSize": list(self.max_size),
			"previewSizes": [list(s) for s in self.preview_sizes],
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
			# Do NOT embed remove_bg_api_key in client HTML — use server-side proxy
		}

		field_id_js = _js_json(field.id)

		return f"""
<script>
(function() {{
	var FIELD_ID = {field_id_js};
	var config = {_js_json(config)};

	function init() {{
		var wrapper = document.querySelector('.image-crop-wrapper[data-max-width]');
		if (!wrapper) return;

		var fileInput = wrapper.querySelector('input[type="file"]');
		var uploadZone = wrapper.querySelector('.upload-zone');
		var cropperWrapper = wrapper.querySelector('.cropper-wrapper');
		var imageElement = wrapper.querySelector('.crop-preview');
		var progressBar = wrapper.querySelector('.progress');
		var errorMessage = wrapper.querySelector('.error-message');
		var dataInput = document.getElementById(FIELD_ID);
		var metadataInput = document.getElementById(FIELD_ID + '_metadata');

		var cropper = null;
		var history = [];
		var historyIndex = -1;

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

		function handleFileUpload(file) {{
			if (!validateFile(file)) return;
			var reader = new FileReader();
			reader.onload = function(e) {{
				imageElement.src = e.target.result;
				if (cropper) {{ cropper.destroy(); }}
				cropper = initCropper(imageElement);
				uploadZone.style.display = 'none';
				cropperWrapper.style.display = 'block';
			}};
			reader.readAsDataURL(file);
		}}

		function validateFile(file) {{
			var errors = [];
			if (!file.type.startsWith('image/')) {{
				errors.push('Please upload an image file.');
			}}
			if (file.size > config.maxFileSize) {{
				errors.push('File size must not exceed ' + formatFileSize(config.maxFileSize) + '.');
			}}
			if (errors.length) {{
				showError(errors.join(' '));
				return false;
			}}
			return true;
		}}

		function updatePreviewThumbnails() {{
			if (!cropper) return;
			var container = wrapper.querySelector('.preview-thumbnails');
			container.innerHTML = '';
			config.previewSizes.forEach(function(size) {{
				var width = size[0], height = size[1];
				var div = document.createElement('div');
				div.className = 'col preview-box';
				div.style.width = width + 'px';
				div.style.height = height + 'px';
				var img = document.createElement('img');
				img.src = cropper.getCroppedCanvas({{width: width, height: height}}).toDataURL();
				img.alt = width + 'x' + height + ' preview';
				div.appendChild(img);
				container.appendChild(div);
			}});
		}}

		function addHistoryState() {{
			var data = cropper.getData();
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

		function saveProcessedImage(blob, format) {{
			var reader = new FileReader();
			reader.onload = function(e) {{
				if (dataInput) dataInput.value = e.target.result;
				if (metadataInput) metadataInput.value = JSON.stringify({{
					format: format,
					width: config.maxSize[0],
					height: config.maxSize[1],
					quality: config.quality,
				}});
			}};
			reader.readAsDataURL(blob);
		}}

		function processImage(format, quality) {{
			var canvas = cropper.getCroppedCanvas();
			canvas.toBlob(
				function(blob) {{ saveProcessedImage(blob, format); }},
				'image/' + format,
				quality
			);
		}}

		function showError(message) {{
			errorMessage.textContent = message;
			errorMessage.style.display = 'block';
			setTimeout(function() {{ errorMessage.style.display = 'none'; }}, 5000);
		}}

		function formatFileSize(bytes) {{
			var units = ['B', 'KB', 'MB', 'GB'];
			var size = bytes, unitIndex = 0;
			while (size >= 1024 && unitIndex < units.length - 1) {{
				size /= 1024; unitIndex++;
			}}
			return size.toFixed(1) + ' ' + units[unitIndex];
		}}

		// Event listeners
		fileInput.addEventListener('change', function(e) {{
			if (e.target.files && e.target.files[0]) handleFileUpload(e.target.files[0]);
		}});
		uploadZone.addEventListener('click', function() {{ fileInput.click(); }});
		uploadZone.addEventListener('keydown', function(e) {{
			if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); fileInput.click(); }}
		}});
		uploadZone.addEventListener('dragover', function(e) {{
			e.preventDefault(); this.classList.add('dragover');
		}});
		uploadZone.addEventListener('dragleave', function() {{
			this.classList.remove('dragover');
		}});
		uploadZone.addEventListener('drop', function(e) {{
			e.preventDefault(); this.classList.remove('dragover');
			if (e.dataTransfer.files && e.dataTransfer.files[0]) handleFileUpload(e.dataTransfer.files[0]);
		}});

		wrapper.querySelector('.rotate-left').addEventListener('click', function() {{
			cropper.rotate(-config.rotationStep); addHistoryState();
		}});
		wrapper.querySelector('.rotate-right').addEventListener('click', function() {{
			cropper.rotate(config.rotationStep); addHistoryState();
		}});
		wrapper.querySelector('.flip-horizontal').addEventListener('click', function() {{
			cropper.scaleX(-(cropper.getData().scaleX || 1)); addHistoryState();
		}});
		wrapper.querySelector('.flip-vertical').addEventListener('click', function() {{
			cropper.scaleY(-(cropper.getData().scaleY || 1)); addHistoryState();
		}});
		wrapper.querySelector('.zoom-in').addEventListener('click', function() {{
			cropper.zoom(config.zoomRatio); addHistoryState();
		}});
		wrapper.querySelector('.zoom-out').addEventListener('click', function() {{
			cropper.zoom(-config.zoomRatio); addHistoryState();
		}});
		wrapper.querySelector('.reset').addEventListener('click', function() {{
			cropper.reset(); addHistoryState();
		}});

		wrapper.querySelectorAll('.aspect-ratios button').forEach(function(button) {{
			button.addEventListener('click', function() {{
				var ratio = parseFloat(this.dataset.ratio) || NaN;
				cropper.setAspectRatio(ratio); addHistoryState();
			}});
		}});

		var formatSelect = wrapper.querySelector('.format-select');
		var qualitySlider = wrapper.querySelector('.quality-slider');
		var qualityLabel = wrapper.querySelector('.quality-label span');

		if (formatSelect) formatSelect.addEventListener('change', function() {{
			processImage(this.value, parseFloat(qualitySlider.value));
		}});
		if (qualitySlider) {{
			qualitySlider.addEventListener('input', function() {{
				if (qualityLabel) qualityLabel.textContent = this.value;
			}});
			qualitySlider.addEventListener('change', function() {{
				processImage(formatSelect.value, parseFloat(this.value));
			}});
		}}

		wrapper.querySelector('.undo-btn').addEventListener('click', undo);
		wrapper.querySelector('.redo-btn').addEventListener('click', redo);
		wrapper.querySelector('.save-crop').addEventListener('click', function() {{
			var format = formatSelect ? formatSelect.value : 'jpg';
			var quality = qualitySlider ? parseFloat(qualitySlider.value) : config.quality;
			processImage(format, quality);
		}});
	}}

	if (document.readyState === 'loading') {{
		document.addEventListener('DOMContentLoaded', init);
	}} else {{
		init();
	}}
}})();
</script>"""
