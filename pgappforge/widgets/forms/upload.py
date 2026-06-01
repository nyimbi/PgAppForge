"""FileUploadFieldWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
import markupsafe
from markupsafe import Markup
from wtforms.widgets import html_params


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

	# Template uses %(file)s and %(field_id)s slots.
	# %(file)s is filled via Markup.__mod__ so markupsafe escapes it correctly.
	# %(field_id)s is filled with a pre-escaped Markup value.
	_zone_template = Markup(
		'<div class="file-upload-widget mb-3">'
		'<div class="upload-zone w-100" id="%(field_id)s-zone"'
		' role="button" tabindex="0"'
		' aria-label="File upload area — click or drag files here">'
		'<div class="upload-prompt">'
		'<i class="fa fa-cloud-upload" aria-hidden="true"></i>'
		"<span>Drop files here or click to upload</span>"
		"</div>"
		"<input %(file)s>"
		"</div>"
		'<div class="upload-preview" id="%(field_id)s-preview"></div>'
		'<div class="upload-progress" style="display:none">'
		'<div class="progress">'
		'<div class="progress-bar" role="progressbar"'
		' aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>'
		"</div>"
		"</div>"
		# error slot rendered dynamically below
		"</div>"
	)

	def __init__(self, **kwargs):
		"""Initialize file upload widget with custom settings.

		Accepted kwargs (all optional):
		    max_size: int — max file size in bytes  (default 10 MiB)
		    allowed_types: list[str] — MIME types
		    multiple: bool — allow multiple files  (default False)
		    auto_upload: bool — upload immediately on selection  (default True)
		    compress_images: bool — client-side image compression  (default True)
		    max_width: int — max image width before compression  (default 1920)
		    max_height: int — max image height before compression  (default 1080)
		    upload_url: str — POST endpoint  (default '/api/upload')
		    preview_template: str | None — custom preview HTML
		    storage_provider: str | None — 'aws_s3' | 'google_cloud' | None
		    storage_config: dict — provider-specific config
		    description: str | None — help text rendered below the widget
		    css_class: str | None — extra CSS classes on the <input>
		    readonly: bool — render input as readonly  (default False)
		    disabled: bool — render input as disabled  (default False)
		    size_error: str — custom size-exceeded error message
		    type_error: str — custom type-not-allowed error message
		    upload_error: str — custom upload-failure error message
		    generic_error: str — generic fallback error message
		"""
		super().__init__()
		self.max_size = kwargs.get("max_size", 10 * 1024 * 1024)
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
		self.storage_provider = kwargs.get("storage_provider", None)
		self.storage_config = kwargs.get("storage_config", {})
		self.description = kwargs.get("description", None)
		self.css_class = kwargs.get("css_class", None)
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)
		self.error_messages = {
			"size_error": kwargs.get(
				"size_error",
				f"File size must be less than {self.max_size / 1024 / 1024:.0f} MB",
			),
			"type_error": kwargs.get("type_error", "File type not allowed"),
			"upload_error": kwargs.get("upload_error", "Error uploading file"),
			"generic_error": kwargs.get("generic_error", "An error occurred"),
		}

	def __call__(self, field, **kwargs):
		"""Render the file upload widget."""
		kwargs.setdefault("type", "file")
		kwargs.setdefault("accept", ",".join(self.allowed_types))

		# Use Python True so html_params renders the bare `multiple` attribute.
		if self.multiple:
			kwargs["multiple"] = True

		# Accessibility
		aria_label = field.label.text if field.label else ""
		kwargs["aria-label"] = aria_label
		if field.errors:
			kwargs["aria-invalid"] = "true"
			kwargs["aria-describedby"] = field.id + "_error"
		elif self.description:
			kwargs["aria-describedby"] = field.id + "_help"

		# Build CSS class for the hidden file <input>
		css = "d-none"
		if self.css_class:
			css += " " + self.css_class
		if field.errors:
			css += " is-invalid"
		kwargs["class"] = css

		if self.disabled:
			kwargs["disabled"] = True

		# field.id is developer-controlled but escape it for safe Markup use.
		safe_field_id = markupsafe.escape(field.id)

		widget_html = self._zone_template % {
			"file": Markup(html_params(name=field.name, id=field.id, **kwargs)),
			"field_id": safe_field_id,
		}

		# Error feedback (WTForms validation errors, not upload errors)
		error_html = Markup("")
		if field.errors:
			errors_inner = Markup("").join(
				Markup("<span>{}</span>").format(markupsafe.escape(e))
				for e in field.errors
			)
			error_html = (
				Markup('<div class="invalid-feedback d-block" id="{}_error">').format(field.id)
				+ errors_inner
				+ Markup("</div>")
			)

		# Help text
		help_html = Markup("")
		if self.description:
			help_html = (
				Markup('<small class="form-text text-muted" id="{}_help">{}</small>').format(
					field.id, markupsafe.escape(self.description)
				)
			)

		# All values embedded in JS are developer-controlled config; field.id
		# and field.data still go through _js_json for safety.
		field_id_js = _js_json(field.id)
		initial_data_js = _js_json(field.data) if field.data else "null"
		allowed_types_js = _js_json(self.allowed_types)
		error_messages_js = _js_json(self.error_messages)

		script = Markup("""
<style>
	.file-upload-widget {
		/* mb-3 handled by Bootstrap utility class on the outer div */
	}
	.upload-zone {
		border: 2px dashed #ced4da;
		padding: 1.5rem;
		text-align: center;
		background: #f8f9fa;
		cursor: pointer;
		transition: border-color 0.2s ease, background-color 0.2s ease;
		border-radius: 0.375rem;
	}
	.upload-zone:focus {
		outline: 2px solid #86b7fe;
		outline-offset: 2px;
	}
	.upload-zone.dragover {
		border-color: #0d6efd;
		background: #e7f1ff;
	}
	.upload-prompt i {
		font-size: 3rem;
		color: #6c757d;
	}
	.upload-preview {
		margin-top: 0.625rem;
	}
	.upload-preview img {
		max-width: 100%;
		max-height: 200px;
		margin: 5px;
		border: 1px solid #dee2e6;
		padding: 3px;
		border-radius: 0.25rem;
	}
	.upload-progress {
		margin-top: 0.625rem;
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
		background: #dc3545;
		color: white;
		border-radius: 50%;
		width: 20px;
		height: 20px;
		line-height: 20px;
		text-align: center;
		cursor: pointer;
		border: none;
		padding: 0;
	}
</style>
<script>
(function() {
	var fieldId = """ + Markup(field_id_js) + """;
	var $widget = $('#' + fieldId).closest('.file-upload-widget');
	var $input = $('#' + fieldId);
	var $zone = $('#' + fieldId + '-zone');
	var $preview = $widget.find('.upload-preview');
	var $progress = $widget.find('.upload-progress');
	var $progressBar = $progress.find('.progress-bar');
	var $uploadError = $('<div class="upload-error text-danger mt-1"></div>').appendTo($widget);

	var allowedTypes = """ + Markup(allowed_types_js) + """;
	var maxSize = """ + Markup(json.dumps(self.max_size)) + """;
	var autoUpload = """ + Markup(json.dumps(bool(self.auto_upload))) + """;
	var uploadUrl = """ + Markup(_js_json(self.upload_url)) + """;
	var errorMessages = """ + Markup(error_messages_js) + """;

	function showUploadError(key, customMsg) {
		var msg = customMsg || errorMessages.generic_error;
		if (key && errorMessages[key]) { msg = errorMessages[key]; }
		$uploadError.text(msg).show();
		setTimeout(function() { $uploadError.fadeOut(); }, 5000);
	}

	function validateFile(file) {
		if (file.size > maxSize) {
			showUploadError('size_error');
			return false;
		}
		if (allowedTypes.length && !allowedTypes.includes(file.type)) {
			showUploadError('type_error');
			return false;
		}
		return true;
	}

	function previewFile(file) {
		if (!file || typeof file !== 'object') return;
		var $item = $('<div class="preview-item"></div>');
		var $removeBtn = $('<button type="button" class="remove" aria-label="Remove file">&times;</button>');
		$removeBtn.on('click', function() { $item.remove(); });

		if (file.type && file.type.startsWith('image/')) {
			var reader = new FileReader();
			reader.onload = function(e) {
				$('<img alt="Preview">').attr('src', e.target.result).appendTo($item);
			};
			reader.readAsDataURL(file);
		} else {
			$('<span class="badge bg-secondary"></span>').text(file.name || 'file').appendTo($item);
		}
		$item.append($removeBtn);
		$preview.append($item);
	}

	async function uploadFile(file) {
		$progress.show();
		$progressBar.width('0%').attr('aria-valuenow', 0);

		var formData = new FormData();
		formData.append('file', file);

		try {
			var response = await $.ajax({
				url: uploadUrl,
				type: 'POST',
				data: formData,
				processData: false,
				contentType: false,
				xhr: function() {
					var xhr = new XMLHttpRequest();
					xhr.upload.addEventListener('progress', function(e) {
						if (e.lengthComputable) {
							var pct = Math.round((e.loaded / e.total) * 100);
							$progressBar.width(pct + '%').attr('aria-valuenow', pct);
						}
					});
					return xhr;
				}
			});
			$progress.hide();
			if (response && response.error) {
				showUploadError(null, response.error);
			}
		} catch (err) {
			$progress.hide();
			showUploadError('upload_error', err.statusText || err.message);
		}
	}

	async function handleFiles(files) {
		for (var i = 0; i < files.length; i++) {
			var file = files[i];
			if (!validateFile(file)) continue;
			previewFile(file);
			if (autoUpload) {
				await uploadFile(file);
			}
		}
	}

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
		$input.trigger('click');
	}).on('keydown', function(e) {
		// Keyboard accessibility: Space or Enter activates the file dialog
		if (e.key === ' ' || e.key === 'Enter') {
			e.preventDefault();
			$input.trigger('click');
		}
	});

	$input.on('change', function() {
		handleFiles(this.files);
	});

	// Render any initial server-side value
	var initialData = """ + Markup(initial_data_js) + """;
	if (initialData) {
		previewFile(initialData);
	}
})();
</script>
""")

		return widget_html + error_html + help_html + script

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
		if valuelist:
			self.data = valuelist[0]
		else:
			self.data = None

	def process_data(self, value):
		"""Process data from database format."""
		if value:
			return value
		return None
