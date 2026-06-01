"""DocumentViewerWidget — PgAppForge widget(s)."""

from __future__ import annotations

from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup, escape


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
	- Download in multiple formats
	- Page rotation
	- Bookmark management
	- Mobile-optimized UI
	- Accessibility features

	Required Dependencies:
	- PDF.js 2.0+
	- Mammoth.js (Word)
	- SheetJS (Excel)
	- Fabric.js (Annotations)

	Database Schema:
		document = db.Column(db.LargeBinary, nullable=False)
		metadata = db.Column(db.JSON, nullable=False)
		annotations = db.Column(db.JSON)
	"""

	def __init__(self, **kwargs):
		"""Initialize document viewer with configuration."""
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
		# Universal kwargs
		self.placeholder = kwargs.get("placeholder", "")
		self.css_class = kwargs.get("css_class", "")
		self.description = kwargs.get("description", "")
		self.readonly = kwargs.get("readonly", False)
		self.disabled = kwargs.get("disabled", False)

	def __call__(self, field, **kwargs):
		"""Render the document viewer widget."""
		kwargs.setdefault("id", field.id)

		has_errors = bool(field.errors)
		invalid_attr = ' aria-invalid="true"' if has_errors else ''
		label_text = str(field.label.text) if field.label else str(_("Document"))
		field_id = escape(field.id)

		wrapper_classes = "document-viewer-wrapper"
		if self.wrapper_class:
			wrapper_classes += f" {escape(self.wrapper_class)}"
		if self.css_class:
			wrapper_classes += f" {escape(self.css_class)}"
		if has_errors:
			wrapper_classes += " is-invalid"

		html = (
			f'<div class="{wrapper_classes}"'
			f' role="application" aria-label="{escape(label_text)}">'

			# Toolbar
			'<div class="document-toolbar mb-2" role="toolbar"'
			f' aria-label="{escape(str(_("Document Controls")))}">'

			# Zoom group
			f'<div class="btn-group" role="group" aria-label="{escape(str(_("Zoom controls")))}">'
			f'<button type="button" class="btn btn-sm btn-secondary" data-command="zoomIn"'
			f' aria-label="{escape(str(_("Zoom in")))}" title="{escape(str(_("Zoom In")))}">'
			'<i class="fa fa-search-plus" aria-hidden="true"></i>'
			'</button>'
			f'<button type="button" class="btn btn-sm btn-secondary" data-command="zoomOut"'
			f' aria-label="{escape(str(_("Zoom out")))}" title="{escape(str(_("Zoom Out")))}">'
			'<i class="fa fa-search-minus" aria-hidden="true"></i>'
			'</button>'
			f'<button type="button" class="btn btn-sm btn-secondary" data-command="fitPage"'
			f' aria-label="{escape(str(_("Fit page")))}" title="{escape(str(_("Fit Page")))}">'
			'<i class="fa fa-arrows-alt" aria-hidden="true"></i>'
			'</button>'
			'</div>'

			# Rotation group
			f'<div class="btn-group ms-2 ms-lg-2 ml-2" role="group"'
			f' aria-label="{escape(str(_("Rotation controls")))}">'
			f'<button type="button" class="btn btn-sm btn-secondary" data-command="rotateLeft"'
			f' aria-label="{escape(str(_("Rotate left")))}" title="{escape(str(_("Rotate Left")))}">'
			'<i class="fa fa-undo" aria-hidden="true"></i>'
			'</button>'
			f'<button type="button" class="btn btn-sm btn-secondary" data-command="rotateRight"'
			f' aria-label="{escape(str(_("Rotate right")))}" title="{escape(str(_("Rotate Right")))}">'
			'<i class="fa fa-redo" aria-hidden="true"></i>'
			'</button>'
			'</div>'

			# Print/download group
			f'<div class="btn-group ms-2 ms-lg-2 ml-2" role="group"'
			f' aria-label="{escape(str(_("Document actions")))}">'
		)

		if self.enable_print:
			html += (
				f'<button type="button" class="btn btn-sm btn-secondary" data-command="print"'
				f' aria-label="{escape(str(_("Print document")))}" title="{escape(str(_("Print")))}">'
				'<i class="fa fa-print" aria-hidden="true"></i>'
				'</button>'
			)

		if self.enable_download:
			html += (
				f'<button type="button" class="btn btn-sm btn-secondary" data-command="download"'
				f' aria-label="{escape(str(_("Download document")))}" title="{escape(str(_("Download")))}">'
				'<i class="fa fa-download" aria-hidden="true"></i>'
				'</button>'
			)

		html += '</div>'

		# Annotation tools group
		if self.enable_annotations:
			html += (
				f'<div class="btn-group ms-2 ms-lg-2 ml-2 annotation-tools" style="display:none"'
				f' role="group" aria-label="{escape(str(_("Annotation tools")))}">'
			)
			tool_icons = {
				"highlight": ("fa-highlighter", str(_("Highlight"))),
				"note":      ("fa-sticky-note", str(_("Note"))),
				"draw":      ("fa-pencil-alt",  str(_("Draw"))),
				"shape":     ("fa-shapes",       str(_("Shape"))),
			}
			for tool in self.annotation_tools:
				if tool in tool_icons:
					icon, label = tool_icons[tool]
					html += (
						f'<button type="button" class="btn btn-sm btn-secondary" data-tool="{escape(tool)}"'
						f' aria-label="{escape(label)}" title="{escape(label)}">'
						f'<i class="fa {icon}" aria-hidden="true"></i>'
						'</button>'
					)
			html += '</div>'

		html += '</div>'  # end toolbar

		# Document container
		html += (
			'<div class="document-container" style="display: flex; width: 100%;">'
		)

		if self.show_thumbnails:
			html += (
				f'<div class="thumbnails-panel" style="display:none; width: {self.thumbnail_size[0] + 20}px;"'
				f' role="navigation" aria-label="{escape(str(_("Page thumbnails")))}"></div>'
			)

		html += (
			f'<div id="{field_id}_viewer" class="viewer-container" style="flex: 1;"'
			f' role="document" aria-label="{escape(str(_("Document viewer")))}"></div>'
		)

		if self.enable_search:
			html += (
				'<div class="search-panel" style="display:none">'
				f'<label for="{field_id}_search" class="visually-hidden sr-only">'
				f'{escape(str(_("Search document")))}</label>'
				f'<input type="text" class="form-control form-control-sm" id="{field_id}_search"'
				f' placeholder="{escape(str(_("Search...")))}"'
				f' aria-label="{escape(str(_("Search document")))}">'
				'<div class="search-results" role="list"'
				f' aria-label="{escape(str(_("Search results")))}" aria-live="polite"></div>'
				'</div>'
			)

		html += '</div>'  # end document-container

		# Hidden fields
		html += (
			f'<input type="hidden" name="{escape(field.name)}" id="{field_id}"'
			f' value="{escape(str(field.data) if field.data else "")}"'
			f' aria-label="{escape(label_text)}"{invalid_attr}>'
			f'<input type="file" style="display:none" id="{field_id}_file"'
			f' accept="{escape(",".join("." + f for f in self.supported_formats))}"'
			f' aria-label="{escape(str(_("Upload document")))}">'
		)

		html += '</div>'  # end wrapper

		html += self._get_widget_scripts(field)

		# Server-side WTForms errors
		if has_errors:
			html += (
				f'<div class="invalid-feedback d-block" id="{field_id}_error" role="alert">'
			)
			for error in field.errors:
				html += f'<span>{escape(str(error))}</span>'
			html += '</div>'

		# Help text
		if self.description:
			html += (
				f'<small class="form-text text-muted" id="{field_id}_help">'
				f'{escape(self.description)}</small>'
			)

		return Markup(html)

	def _get_widget_scripts(self, field) -> str:
		"""Generate widget initialization JavaScript."""
		config = {
			"supportedFormats": self.supported_formats,
			"enableAnnotations": self.enable_annotations,
			"annotationTools": self.annotation_tools,
			"showThumbnails": self.show_thumbnails,
			"thumbnailSize": list(self.thumbnail_size),
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

		field_id_js = _js_json(field.id)
		size_exceeded_msg = _js_json(
			str(_("File size exceeds maximum allowed")) + f" ({self.max_file_size / (1024 * 1024):.1f}MB)"
		)
		unsupported_type_msg = _js_json(
			str(_("Unsupported file type. Allowed")) + ": " + ", ".join(self.supported_formats)
		)

		return f"""
<script>
(function() {{
	var FIELD_ID = {field_id_js};
	var config = {_js_json(config)};

	function init() {{
		var field = document.getElementById(FIELD_ID);
		var fileInput = document.getElementById(FIELD_ID + '_file');
		var viewerEl = document.getElementById(FIELD_ID + '_viewer');
		var toolbar = document.querySelector('#' + FIELD_ID + '_viewer')
			? document.querySelector('[id="' + FIELD_ID + '_viewer"]').closest('.document-viewer-wrapper').querySelector('.document-toolbar')
			: null;

		if (!viewerEl) return;

		var viewer = null;
		if (typeof DocumentViewer !== 'undefined') {{
			viewer = new DocumentViewer('#' + FIELD_ID + '_viewer', config);
		}}

		// Load existing document value
		if (viewer && field && field.value) {{
			viewer.loadDocument(field.value);
		}}

		// File selection
		if (fileInput) {{
			fileInput.addEventListener('change', function(e) {{
				var file = e.target.files && e.target.files[0];
				if (!file) return;
				if (!validateFile(file)) return;

				var reader = new FileReader();
				reader.onload = function(ev) {{
					if (field) field.value = ev.target.result;
					if (viewer) viewer.loadDocument(ev.target.result);
				}};
				reader.readAsDataURL(file);
			}});
		}}

		// Toolbar command routing
		var toolbarEl = viewerEl.closest('.document-viewer-wrapper')
			? viewerEl.closest('.document-viewer-wrapper').querySelector('.document-toolbar')
			: null;

		if (toolbarEl) {{
			toolbarEl.addEventListener('click', function(e) {{
				var commandEl = e.target.closest('[data-command]');
				if (commandEl && viewer) {{
					switch (commandEl.dataset.command) {{
						case 'zoomIn':     viewer.zoomIn(); break;
						case 'zoomOut':    viewer.zoomOut(); break;
						case 'fitPage':    viewer.fitToPage(); break;
						case 'rotateLeft': viewer.rotate(-config.rotationStep); break;
						case 'rotateRight':viewer.rotate(config.rotationStep); break;
						case 'print':      viewer.print(); break;
						case 'download':   viewer.download(); break;
					}}
				}}
				var toolEl = e.target.closest('[data-tool]');
				if (toolEl && viewer) {{
					viewer.setAnnotationTool(toolEl.dataset.tool);
				}}
			}});
		}}

		// Search
		if (config.enableSearch) {{
			var searchInput = document.getElementById(FIELD_ID + '_search');
			if (searchInput) {{
				var searchTimeout;
				searchInput.addEventListener('input', function() {{
					clearTimeout(searchTimeout);
					var query = this.value;
					searchTimeout = setTimeout(function() {{
						if (viewer) viewer.search(query);
					}}, 300);
				}});
			}}
		}}

		function validateFile(file) {{
			if (file.size > config.maxFileSize) {{
				alert({size_exceeded_msg});
				return false;
			}}
			var ext = file.name.split('.').pop().toLowerCase();
			if (!config.supportedFormats.includes(ext)) {{
				alert({unsupported_type_msg});
				return false;
			}}
			return true;
		}}
	}}

	if (document.readyState === 'loading') {{
		document.addEventListener('DOMContentLoaded', init);
	}} else {{
		init();
	}}
}})();
</script>"""

	def process_formdata(self, valuelist):
		"""Process form data to database format."""
		if valuelist:
			try:
				self.data = valuelist[0]
				self._validate_document(self.data)
			except Exception as e:
				raise ValueError(f"Invalid document data: {e}")
		else:
			self.data = None

	def _validate_document(self, data):
		"""Validate document data."""
		if not data:
			return
		if len(data) > self.max_file_size:
			raise ValueError(
				f"Document size exceeds maximum allowed ({self.max_file_size / (1024 * 1024):.1f}MB)"
			)
		# Validate file signature if raw bytes
		if isinstance(data, (bytes, bytearray)):
			header = data[:50]
			known_sigs = [b"%PDF", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff"]
			if not any(header.startswith(sig) for sig in known_sigs):
				raise ValueError("Invalid document format")

	def pre_validate(self, form):
		"""Validate document before form processing."""
		if form.flags.required and not self.data:
			raise ValueError("Document is required")
