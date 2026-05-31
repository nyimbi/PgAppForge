"""
QR Code Widget for PgForge

A comprehensive QR Code widget with generation, scanning, customization, and bulk operations.
"""

from markupsafe import Markup, escape
from wtforms.widgets import Input
from flask_babel import gettext
from pgappforge.widgets_postgresql._cdn import QRCODE_CDN_URL, JSQR_CDN_URL
from pgappforge.widgets.media._utils import js_json as _js_json


class QrCodeWidget(Input):
    """
    Advanced QR Code widget with comprehensive features:

    - QR code generation with customization
    - QR code scanning via camera
    - Batch QR code generation
    - Multiple formats (URL, text, email, phone, SMS, WiFi, vCard)
    - Customizable styling (colors, logos, patterns)
    - Export capabilities (PNG, SVG, PDF)
    - History and management
    - Error correction levels
    """

    def __init__(
        self,
        enable_generation=True,
        enable_scanning=True,
        enable_customization=True,
        enable_batch_generation=False,
        enable_export=True,
        enable_history=True,
        default_size=256,
        default_error_correction='M',
        supported_formats=None,
        enable_logo_upload=True,
        enable_color_customization=True,
        enable_pattern_selection=True,
        max_history_items=50,
        enable_bulk_download=True,
        enable_analytics=False,
        **kwargs
    ):
        """
        Initialize QR Code Widget.

        Args:
            enable_generation: Enable QR code generation
            enable_scanning: Enable QR code scanning via camera
            enable_customization: Enable visual customization
            enable_batch_generation: Enable bulk QR code generation
            enable_export: Enable export functionality
            enable_history: Enable QR code history
            default_size: Default QR code size in pixels
            default_error_correction: Error correction level ('L', 'M', 'Q', 'H')
            supported_formats: List of supported data formats
            enable_logo_upload: Allow logo overlay
            enable_color_customization: Allow color customization
            enable_pattern_selection: Enable pattern selection
            max_history_items: Maximum items in history
            enable_bulk_download: Enable bulk download as ZIP
            enable_analytics: Enable usage analytics
        """
        super().__init__(**kwargs)
        self.enable_generation = enable_generation
        self.enable_scanning = enable_scanning
        self.enable_customization = enable_customization
        self.enable_batch_generation = enable_batch_generation
        self.enable_export = enable_export
        self.enable_history = enable_history
        self.default_size = default_size
        self.default_error_correction = default_error_correction
        self.supported_formats = supported_formats or [
            'text', 'url', 'email', 'phone', 'sms', 'wifi', 'vcard', 'location'
        ]
        self.enable_logo_upload = enable_logo_upload
        self.enable_color_customization = enable_color_customization
        self.enable_pattern_selection = enable_pattern_selection
        self.max_history_items = max_history_items
        self.enable_bulk_download = enable_bulk_download
        self.enable_analytics = enable_analytics

    def __call__(self, field, **kwargs):
        """Render the QR code widget."""
        widget_id = kwargs.get('id', field.id or field.name)

        # Build CSS
        css = self._generate_css(widget_id)

        # Build HTML structure
        html = self._generate_html(field, widget_id, **kwargs)

        # Build JavaScript
        js = self._generate_javascript(widget_id, field.data or '')

        return Markup(f"{css}\n{html}\n{js}")

    def _get_export_buttons_html(self, widget_id):
        """Generate export buttons HTML."""
        if not self.enable_export:
            return ""
        return f'''
                                <button type="button" id="{widget_id}-download-png" class="btn btn-sm btn-secondary" disabled>
                                    <i class="fas fa-download"></i> PNG
                                </button>
                                <button type="button" id="{widget_id}-download-svg" class="btn btn-sm btn-secondary" disabled>
                                    <i class="fas fa-download"></i> SVG
                                </button>'''

    def _get_color_customization_html(self, widget_id):
        """Generate color customization HTML."""
        if not self.enable_color_customization:
            return ""
        return f'''
                            <div class="form-group">
                                <label>{gettext("Foreground Color")}</label>
                                <div id="{widget_id}-color-picker">
                                    <input type="color" id="{widget_id}-fg-color" value="#000000">
                                    <span>Foreground</span>
                                </div>
                            </div>

                            <div class="form-group">
                                <label>{gettext("Background Color")}</label>
                                <div id="{widget_id}-color-picker">
                                    <input type="color" id="{widget_id}-bg-color" value="#ffffff">
                                    <span>Background</span>
                                </div>
                            </div>'''

    def _get_logo_upload_html(self, widget_id):
        """Generate logo upload HTML."""
        if not self.enable_logo_upload:
            return ""
        return f'''
                            <div class="form-group">
                                <label>{gettext("Logo Overlay")}</label>
                                <input type="file" id="{widget_id}-logo-upload" class="form-control" accept="image/*">
                                <small>{gettext("Optional logo to overlay on QR code")}</small>
                            </div>'''

    def _get_customization_html(self, widget_id):
        """Generate customization section HTML."""
        if not self.enable_customization:
            return ""
        return f'''
                        <div id="{widget_id}-customization">
                            <h6>{gettext("Customization")}</h6>

                            <div class="form-group">
                                <label>{gettext("Size")}</label>
                                <input type="range" id="{widget_id}-size-slider" min="128" max="512" value="{self.default_size}" class="form-control">
                                <small id="{widget_id}-size-display">{self.default_size}px</small>
                            </div>

                            <div class="form-group">
                                <label>{gettext("Error Correction")}</label>
                                <select id="{widget_id}-error-correction" class="form-control">
                                    <option value="L">Low (7%)</option>
                                    <option value="M" selected>Medium (15%)</option>
                                    <option value="Q">Quartile (25%)</option>
                                    <option value="H">High (30%)</option>
                                </select>
                            </div>

                            {self._get_color_customization_html(widget_id)}
                            {self._get_logo_upload_html(widget_id)}
                        </div>'''

    def _get_generation_section_html(self, widget_id):
        """Generate the generation section HTML."""
        if not self.enable_generation:
            return ""
        return f'''
                <!-- Generate Tab -->
                <div id="{widget_id}-generate-tab" class="tab-content active">
                    <div id="{widget_id}-form-section">
                        <h6>{gettext("QR Code Content")}</h6>

                        <div class="form-group">
                            <label>{gettext("Content Type")}</label>
                            <select id="{widget_id}-content-type" class="form-control">
                                <option value="text">{gettext("Plain Text")}</option>
                                <option value="url">{gettext("Website URL")}</option>
                                <option value="email">{gettext("Email Address")}</option>
                                <option value="phone">{gettext("Phone Number")}</option>
                                <option value="sms">{gettext("SMS Message")}</option>
                                <option value="wifi">{gettext("WiFi Network")}</option>
                                <option value="vcard">{gettext("Contact Card")}</option>
                                <option value="location">{gettext("Geographic Location")}</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label>{gettext("Content")}</label>
                            <textarea id="{widget_id}-content-input" class="form-control" rows="3"
                                      placeholder="{gettext("Enter content for QR code...")}"></textarea>
                        </div>

                        <div class="form-group">
                            <button type="button" id="{widget_id}-generate-btn" class="btn">
                                <i class="fas fa-magic"></i> {gettext("Generate QR Code")}
                            </button>
                        </div>
                    </div>

                    <div id="{widget_id}-preview">
                        <div id="{widget_id}-qr-display">
                            <div id="{widget_id}-qr-placeholder" style="width: {self.default_size}px; height: {self.default_size}px; border: 2px dashed #ccc; display: flex; align-items: center; justify-content: center; color: #999; margin: 0 auto;">
                                <i class="fas fa-qrcode" style="font-size: 48px;"></i>
                            </div>
                            <canvas id="{widget_id}-qr-canvas" class="hidden"></canvas>

                            <div style="margin-top: 12px;">
                                {self._get_export_buttons_html(widget_id)}
                            </div>
                        </div>

                        {self._get_customization_html(widget_id)}
                    </div>
                </div>'''

    def _get_scanning_section_html(self, widget_id):
        """Generate the scanning section HTML."""
        if not self.enable_scanning:
            return ""
        return f'''
                <!-- Scan Tab -->
                <div id="{widget_id}-scan-tab" class="tab-content">
                    <div id="{widget_id}-scanner">
                        <h6>{gettext("QR Code Scanner")}</h6>
                        <video id="{widget_id}-camera" class="hidden"></video>
                        <div id="{widget_id}-camera-placeholder" style="width: 400px; height: 300px; margin: 0 auto; border: 2px dashed #ccc; display: flex; align-items: center; justify-content: center; color: #999;">
                            <div style="text-align: center;">
                                <i class="fas fa-camera" style="font-size: 48px; margin-bottom: 12px;"></i>
                                <br>
                                <button type="button" id="{widget_id}-start-camera" class="btn">
                                    <i class="fas fa-camera"></i> {gettext("Start Camera")}
                                </button>
                            </div>
                        </div>
                        <canvas id="{widget_id}-scan-canvas" class="hidden"></canvas>

                        <div style="margin-top: 16px;">
                            <p id="{widget_id}-scan-result" class="alert alert-info hidden"></p>
                        </div>
                    </div>
                </div>'''

    def _get_batch_generation_section_html(self, widget_id):
        """Generate the batch generation section HTML."""
        if not self.enable_batch_generation:
            return ""
        return f'''
                <!-- Batch Tab -->
                <div id="{widget_id}-batch-tab" class="tab-content">
                    <div id="{widget_id}-batch-form">
                        <h6>{gettext("Batch QR Code Generation")}</h6>

                        <div class="form-group">
                            <label>{gettext("Batch Data")}</label>
                            <textarea id="{widget_id}-batch-input" class="form-control" rows="8"
                                      placeholder="{gettext("Enter one item per line...")}"></textarea>
                            <small>{gettext("One QR code will be generated for each line")}</small>
                        </div>

                        <div class="form-group">
                            <button type="button" id="{widget_id}-batch-generate" class="btn">
                                <i class="fas fa-magic"></i> {gettext("Generate All")}
                            </button>
                        </div>

                        <div id="{widget_id}-batch-progress" class="hidden">
                            <div class="progress">
                                <div id="{widget_id}-batch-progress-bar" class="progress-bar" role="progressbar" style="width: 0%"></div>
                            </div>
                        </div>

                        <div id="{widget_id}-batch-download" class="hidden">
                            <button type="button" class="btn" onclick="downloadBatch()">
                                <i class="fas fa-download"></i> {gettext("Download All")}
                            </button>
                        </div>
                    </div>
                </div>'''

    def _get_history_section_html(self, widget_id):
        """Generate the history section HTML."""
        if not self.enable_history:
            return ""
        return f'''
                <!-- History Tab -->
                <div id="{widget_id}-history-tab" class="tab-content">
                    <div id="{widget_id}-history-list">
                        <h6>{gettext("QR Code History")}</h6>

                        <div class="form-group">
                            <button type="button" id="{widget_id}-clear-history" class="btn btn-sm btn-secondary">
                                <i class="fas fa-trash"></i> {gettext("Clear History")}
                            </button>
                        </div>

                        <div id="{widget_id}-history-items">
                            <!-- History items will be populated dynamically -->
                        </div>
                    </div>
                </div>'''

    def _generate_css(self, widget_id):
        """Generate CSS for the QR code widget."""
        return f'''
        <style>
        #{widget_id}-container {{
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #f8f9fa;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        #{widget_id}-header {{
            background: #343a40;
            color: white;
            padding: 12px 16px;
            border-bottom: 1px solid #495057;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}

        #{widget_id}-header h5 {{
            margin: 0;
            color: #f8f9fa;
            font-size: 16px;
            font-weight: 600;
        }}

        #{widget_id}-tabs {{
            display: flex;
            gap: 4px;
        }}

        #{widget_id}-tabs .tab-btn {{
            background: #495057;
            border: none;
            color: white;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
        }}

        #{widget_id}-tabs .tab-btn:hover {{
            background: #6c757d;
        }}

        #{widget_id}-tabs .tab-btn.active {{
            background: #007bff;
        }}

        #{widget_id}-content {{
            padding: 20px;
        }}

        #{widget_id}-form-section {{
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
        }}

        #{widget_id}-form-section h6 {{
            margin: 0 0 12px 0;
            color: #495057;
            font-size: 14px;
            font-weight: 600;
        }}

        #{widget_id} .form-group {{
            margin-bottom: 12px;
        }}

        #{widget_id} .form-group label {{
            display: block;
            margin-bottom: 4px;
            font-size: 12px;
            color: #6c757d;
            font-weight: 500;
        }}

        #{widget_id} .form-control {{
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            font-size: 14px;
            transition: border-color 0.2s;
        }}

        #{widget_id} .form-control:focus {{
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 0 2px rgba(0,123,255,0.25);
        }}

        #{widget_id} .btn {{
            background: #007bff;
            border: 1px solid #007bff;
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
        }}

        #{widget_id} .btn:hover {{
            background: #0056b3;
            border-color: #0056b3;
        }}

        #{widget_id} .btn-secondary {{
            background: #6c757d;
            border-color: #6c757d;
        }}

        #{widget_id} .btn-secondary:hover {{
            background: #545b62;
            border-color: #545b62;
        }}

        #{widget_id} .btn-success {{
            background: #28a745;
            border-color: #28a745;
        }}

        #{widget_id} .btn-success:hover {{
            background: #1e7e34;
            border-color: #1e7e34;
        }}

        #{widget_id} .btn-sm {{
            padding: 4px 8px;
            font-size: 12px;
        }}

        #{widget_id}-preview {{
            display: flex;
            gap: 20px;
            align-items: flex-start;
        }}

        #{widget_id}-qr-display {{
            text-align: center;
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 20px;
            min-width: 300px;
        }}

        #{widget_id}-qr-canvas {{
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-bottom: 12px;
        }}

        #{widget_id}-customization {{
            flex: 1;
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 16px;
        }}

        #{widget_id}-color-picker {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}

        #{widget_id}-color-picker input[type="color"] {{
            width: 40px;
            height: 32px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            cursor: pointer;
        }}

        #{widget_id}-scanner {{
            text-align: center;
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 20px;
        }}

        #{widget_id}-camera {{
            width: 100%;
            max-width: 400px;
            height: 300px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #000;
        }}

        #{widget_id}-scan-result {{
            margin-top: 12px;
            padding: 12px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
            word-break: break-all;
        }}

        #{widget_id}-history {{
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            max-height: 400px;
            overflow-y: auto;
        }}

        #{widget_id}-history-item {{
            padding: 12px 16px;
            border-bottom: 1px solid #f1f3f4;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: background-color 0.2s;
        }}

        #{widget_id}-history-item:hover {{
            background: #f8f9fa;
        }}

        #{widget_id}-history-item:last-child {{
            border-bottom: none;
        }}

        .qr-history-content {{
            flex: 1;
            min-width: 0;
        }}

        .qr-history-text {{
            font-size: 14px;
            color: #495057;
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .qr-history-meta {{
            font-size: 11px;
            color: #6c757d;
        }}

        .qr-history-actions {{
            display: flex;
            gap: 4px;
        }}

        #{widget_id}-batch {{
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 16px;
        }}

        #{widget_id}-batch-list {{
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            margin: 12px 0;
        }}

        .batch-item {{
            padding: 8px 12px;
            border-bottom: 1px solid #f1f3f4;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }}

        .batch-item:last-child {{
            border-bottom: none;
        }}

        .batch-progress {{
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
            margin: 12px 0;
        }}

        .batch-progress-bar {{
            height: 100%;
            background: #007bff;
            transition: width 0.3s;
        }}

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
        }}

        .hidden {{
            display: none !important;
        }}

        @media (max-width: 768px) {{
            #{widget_id}-header {{
                flex-direction: column;
                align-items: stretch;
            }}

            #{widget_id}-tabs {{
                justify-content: center;
            }}

            #{widget_id}-preview {{
                flex-direction: column;
            }}

            #{widget_id}-qr-display {{
                min-width: auto;
            }}
        }}
        </style>
        '''

    def _generate_html(self, field, widget_id, **kwargs):
        """Generate HTML structure for the QR code widget."""
        return f'''
        <div id="{widget_id}-container" class="qr-code-widget">
            <!-- Header -->
            <div id="{widget_id}-header">
                <h5><i class="fas fa-qrcode"></i> {gettext("QR Code Generator & Scanner")}</h5>
                <div id="{widget_id}-tabs">
                    {"" if not self.enable_generation else f'<button class="tab-btn active" data-tab="generate">{gettext("Generate")}</button>'}
                    {"" if not self.enable_scanning else f'<button class="tab-btn" data-tab="scan">{gettext("Scan")}</button>'}
                    {"" if not self.enable_batch_generation else f'<button class="tab-btn" data-tab="batch">{gettext("Batch")}</button>'}
                    {"" if not self.enable_history else f'<button class="tab-btn" data-tab="history">{gettext("History")}</button>'}
                </div>
            </div>

            <!-- Content -->
            <div id="{widget_id}-content">
                {self._get_generation_section_html(widget_id)}

                {self._get_scanning_section_html(widget_id)}

                {self._get_batch_generation_section_html(widget_id)}

                {self._get_history_section_html(widget_id)}
            </div>

            <!-- Hidden input field -->
            <input type="hidden" name="{escape(field.name)}" id="{escape(widget_id)}" value="{escape(field.data or '')}" />
        </div>
        '''

    def _generate_javascript(self, widget_id, initial_value):
        """Generate JavaScript for the QR code widget."""
        safe_initial = _js_json(initial_value)
        return f'''
        <script>
        (function() {{
            let qrCodeLib = null;
            let jsQRLib = null;
            let currentStream = null;
            let scanInterval = null;
            let qrHistory = JSON.parse(localStorage.getItem('{widget_id}-history') || '[]');

            // Load QR code libraries
            function loadQRLibraries() {{
                // Load QR code generation library
                if (!window.QRCode) {{
                    const qrScript = document.createElement('script');
                    qrScript.src = '{QRCODE_CDN_URL}';
                    qrScript.onload = function() {{
                        qrCodeLib = window.QRCode;
                        console.log('QR Code generation library loaded');
                    }};
                    document.head.appendChild(qrScript);
                }} else {{
                    qrCodeLib = window.QRCode;
                }}

                // Load QR code scanning library
                if (!window.jsQR) {{
                    const jsQRScript = document.createElement('script');
                    jsQRScript.src = '{JSQR_CDN_URL}';
                    jsQRScript.onload = function() {{
                        jsQRLib = window.jsQR;
                        console.log('QR Code scanning library loaded');
                    }};
                    document.head.appendChild(jsQRScript);
                }} else {{
                    jsQRLib = window.jsQR;
                }}
            }}

            function initQRWidget() {{
                loadQRLibraries();
                setupTabs();
                setupGeneration();
                setupScanning();
                setupBatch();
                setupHistory();
                loadHistory();

                // Set initial value if provided
                if ({safe_initial}) {{
                    document.getElementById('{widget_id}-content-input').value = {safe_initial};
                    generateQRCode();
                }}
            }}

            function setupTabs() {{
                const tabs = document.querySelectorAll('#{widget_id}-tabs .tab-btn');
                tabs.forEach(tab => {{
                    tab.addEventListener('click', function() {{
                        const tabName = this.dataset.tab;

                        // Update active tab
                        tabs.forEach(t => t.classList.remove('active'));
                        this.classList.add('active');

                        // Show corresponding content
                        document.querySelectorAll('#{widget_id}-content .tab-content').forEach(content => {{
                            content.classList.remove('active');
                        }});
                        const targetContent = document.getElementById(`{widget_id}-${{tabName}}-tab`);
                        if (targetContent) {{
                            targetContent.classList.add('active');
                        }}
                    }});
                }});
            }}

            function setupGeneration() {{
                {"" if not self.enable_generation else f'''
                const generateBtn = document.getElementById('{widget_id}-generate-btn');
                const contentInput = document.getElementById('{widget_id}-content-input');
                const contentType = document.getElementById('{widget_id}-content-type');

                if (generateBtn) {{
                    generateBtn.addEventListener('click', generateQRCode);
                }}

                if (contentInput) {{
                    contentInput.addEventListener('input', function() {{
                        document.getElementById('{widget_id}').value = this.value;
                    }});
                }}

                // Customization controls
                const sizeSlider = document.getElementById('{widget_id}-size-slider');
                if (sizeSlider) {{
                    sizeSlider.addEventListener('input', function() {{
                        document.getElementById('{widget_id}-size-display').textContent = this.value + 'px';
                        if (document.getElementById('{widget_id}-qr-canvas').style.display !== 'none') {{
                            generateQRCode();
                        }}
                    }});
                }}

                const errorCorrection = document.getElementById('{widget_id}-error-correction');
                if (errorCorrection) {{
                    errorCorrection.addEventListener('change', function() {{
                        if (document.getElementById('{widget_id}-qr-canvas').style.display !== 'none') {{
                            generateQRCode();
                        }}
                    }});
                }}

                {"" if not self.enable_color_customization else f'''
                const fgColor = document.getElementById('{widget_id}-fg-color');
                const bgColor = document.getElementById('{widget_id}-bg-color');
                if (fgColor) {{
                    fgColor.addEventListener('change', function() {{
                        if (document.getElementById('{widget_id}-qr-canvas').style.display !== 'none') {{
                            generateQRCode();
                        }}
                    }});
                }}
                if (bgColor) {{
                    bgColor.addEventListener('change', function() {{
                        if (document.getElementById('{widget_id}-qr-canvas').style.display !== 'none') {{
                            generateQRCode();
                        }}
                    }});
                }}
                '''}

                // Download buttons
                {"" if not self.enable_export else f'''
                const downloadPng = document.getElementById('{widget_id}-download-png');
                const downloadSvg = document.getElementById('{widget_id}-download-svg');

                if (downloadPng) {{
                    downloadPng.addEventListener('click', function() {{
                        downloadQRCode('png');
                    }});
                }}

                if (downloadSvg) {{
                    downloadSvg.addEventListener('click', function() {{
                        downloadQRCode('svg');
                    }});
                }}
                '''}
                '''}
            }}

            function setupScanning() {{
                {"" if not self.enable_scanning else f'''
                const startCameraBtn = document.getElementById('{widget_id}-start-camera');
                const stopCameraBtn = document.getElementById('{widget_id}-stop-camera');
                const uploadBtn = document.getElementById('{widget_id}-upload-btn');
                const fileUpload = document.getElementById('{widget_id}-file-upload');

                if (startCameraBtn) {{
                    startCameraBtn.addEventListener('click', startCamera);
                }}

                if (stopCameraBtn) {{
                    stopCameraBtn.addEventListener('click', stopCamera);
                }}

                if (uploadBtn) {{
                    uploadBtn.addEventListener('click', function() {{
                        fileUpload.click();
                    }});
                }}

                if (fileUpload) {{
                    fileUpload.addEventListener('change', function(e) {{
                        const file = e.target.files[0];
                        if (file) {{
                            scanImageFile(file);
                        }}
                    }});
                }}
                '''}
            }}

            function setupBatch() {{
                {"" if not self.enable_batch_generation else f'''
                const batchGenerateBtn = document.getElementById('{widget_id}-batch-generate');
                const batchDownloadBtn = document.getElementById('{widget_id}-batch-download');

                if (batchGenerateBtn) {{
                    batchGenerateBtn.addEventListener('click', generateBatchQRCodes);
                }}

                if (batchDownloadBtn) {{
                    batchDownloadBtn.addEventListener('click', downloadBatchZip);
                }}
                '''}
            }}

            function setupHistory() {{
                {"" if not self.enable_history else f'''
                const clearHistoryBtn = document.getElementById('{widget_id}-clear-history');
                if (clearHistoryBtn) {{
                    clearHistoryBtn.addEventListener('click', function() {{
                        if (confirm('{gettext("Clear all QR code history?")}')) {{
                            qrHistory = [];
                            localStorage.removeItem('{widget_id}-history');
                            loadHistory();
                        }}
                    }});
                }}
                '''}
            }}

            function generateQRCode() {{
                if (!qrCodeLib) {{
                    console.warn('QR Code library not loaded yet');
                    return;
                }}

                const content = document.getElementById('{widget_id}-content-input').value.trim();
                if (!content) {{
                    alert('{gettext("Please enter content for the QR code")}');
                    return;
                }}

                const canvas = document.getElementById('{widget_id}-qr-canvas');
                const placeholder = document.getElementById('{widget_id}-qr-placeholder');
                const size = parseInt(document.getElementById('{widget_id}-size-slider').value) || {self.default_size};
                const errorCorrectionLevel = document.getElementById('{widget_id}-error-correction').value || 'M';

                {"" if not self.enable_color_customization else f'''
                const foregroundColor = document.getElementById('{widget_id}-fg-color').value || '#000000';
                const backgroundColor = document.getElementById('{widget_id}-bg-color').value || '#ffffff';
                '''}

                try {{
                    // Clear canvas
                    canvas.width = size;
                    canvas.height = size;

                    // Generate QR code
                    qrCodeLib.toCanvas(canvas, content, {{
                        width: size,
                        height: size,
                        errorCorrectionLevel: errorCorrectionLevel,
                        {"" if not self.enable_color_customization else "color: { dark: foregroundColor, light: backgroundColor },"}
                        margin: 2
                    }}, function(error) {{
                        if (error) {{
                            console.error('QR Code generation error:', error);
                            alert('{gettext("Error generating QR code")}');
                        }} else {{
                            // Show canvas, hide placeholder
                            canvas.classList.remove('hidden');
                            placeholder.classList.add('hidden');

                            // Enable download buttons
                            {"" if not self.enable_export else f'''
                            document.getElementById('{widget_id}-download-png').disabled = false;
                            document.getElementById('{widget_id}-download-svg').disabled = false;
                            '''}

                            // Add to history
                            {"" if not self.enable_history else f'''
                            addToHistory(content, new Date().toISOString());
                            '''}

                            console.log('QR Code generated successfully');
                        }}
                    }});
                }} catch (error) {{
                    console.error('QR Code generation error:', error);
                    alert('{gettext("Error generating QR code")}');
                }}
            }}

            function downloadQRCode(format) {{
                const canvas = document.getElementById('{widget_id}-qr-canvas');
                const content = document.getElementById('{widget_id}-content-input').value.trim();

                if (format === 'png') {{
                    const link = document.createElement('a');
                    link.download = `qrcode-${{Date.now()}}.png`;
                    link.href = canvas.toDataURL('image/png');
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }} else if (format === 'svg') {{
                    // Generate SVG version
                    qrCodeLib.toString(content, {{
                        type: 'svg',
                        width: 256,
                        height: 256
                    }}, function(err, svg) {{
                        if (!err) {{
                            const blob = new Blob([svg], {{ type: 'image/svg+xml' }});
                            const url = URL.createObjectURL(blob);
                            const link = document.createElement('a');
                            link.download = `qrcode-${{Date.now()}}.svg`;
                            link.href = url;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            URL.revokeObjectURL(url);
                        }}
                    }});
                }}
            }}

            function startCamera() {{
                if (!jsQRLib) {{
                    alert('{gettext("QR scanning library not loaded yet")}');
                    return;
                }}

                const video = document.getElementById('{widget_id}-camera');
                const placeholder = document.getElementById('{widget_id}-camera-placeholder');

                navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: 'environment' }} }})
                    .then(function(stream) {{
                        currentStream = stream;
                        video.srcObject = stream;
                        video.play();

                        video.classList.remove('hidden');
                        placeholder.classList.add('hidden');
                        document.getElementById('{widget_id}-start-camera').classList.add('hidden');
                        document.getElementById('{widget_id}-stop-camera').classList.remove('hidden');

                        // Start scanning
                        scanInterval = setInterval(scanFromVideo, 100);
                    }})
                    .catch(function(err) {{
                        console.error('Camera access error:', err);
                        alert('{gettext("Unable to access camera")}');
                    }});
            }}

            function stopCamera() {{
                if (currentStream) {{
                    currentStream.getTracks().forEach(track => track.stop());
                    currentStream = null;
                }}

                if (scanInterval) {{
                    clearInterval(scanInterval);
                    scanInterval = null;
                }}

                const video = document.getElementById('{widget_id}-camera');
                const placeholder = document.getElementById('{widget_id}-camera-placeholder');

                video.classList.add('hidden');
                placeholder.classList.remove('hidden');
                document.getElementById('{widget_id}-start-camera').classList.remove('hidden');
                document.getElementById('{widget_id}-stop-camera').classList.add('hidden');
            }}

            function scanFromVideo() {{
                const video = document.getElementById('{widget_id}-camera');
                const canvas = document.createElement('canvas');
                const context = canvas.getContext('2d');

                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                context.drawImage(video, 0, 0, canvas.width, canvas.height);

                const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
                const code = jsQRLib(imageData.data, imageData.width, imageData.height);

                if (code) {{
                    displayScanResult(code.data);
                    stopCamera();
                }}
            }}

            function scanImageFile(file) {{
                if (!jsQRLib) {{
                    alert('{gettext("QR scanning library not loaded yet")}');
                    return;
                }}

                const reader = new FileReader();
                reader.onload = function(e) {{
                    const img = new Image();
                    img.onload = function() {{
                        const canvas = document.createElement('canvas');
                        const context = canvas.getContext('2d');

                        canvas.width = img.width;
                        canvas.height = img.height;
                        context.drawImage(img, 0, 0);

                        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
                        const code = jsQRLib(imageData.data, imageData.width, imageData.height);

                        if (code) {{
                            displayScanResult(code.data);
                        }} else {{
                            alert('{gettext("No QR code found in the image")}');
                        }}
                    }};
                    img.src = e.target.result;
                }};
                reader.readAsDataURL(file);
            }}

            function displayScanResult(content) {{
                const resultDiv = document.getElementById('{widget_id}-scan-result');
                const contentDiv = document.getElementById('{widget_id}-scan-content');

                contentDiv.textContent = content;
                resultDiv.classList.remove('hidden');

                // Add to history
                {"" if not self.enable_history else f'''
                addToHistory(content, new Date().toISOString(), 'scanned');
                '''}

                // Update main input
                document.getElementById('{widget_id}').value = content;
            }}

            function generateBatchQRCodes() {{
                const batchInput = document.getElementById('{widget_id}-batch-input');
                const items = batchInput.value.split('\\u000A').filter(item => item.trim());

                if (items.length === 0) {{
                    alert('{gettext("Please enter batch data")}');
                    return;
                }}

                const progressBar = document.getElementById('{widget_id}-batch-progress-bar');
                const progressContainer = document.getElementById('{widget_id}-batch-progress');
                const listContainer = document.getElementById('{widget_id}-batch-list');

                progressContainer.classList.remove('hidden');
                listContainer.classList.remove('hidden');
                listContainer.innerHTML = '';

                let completed = 0;
                const batchData = [];

                items.forEach((item, index) => {{
                    setTimeout(() => {{
                        // Generate QR code for this item
                        generateBatchItem(item.trim(), index, batchData);

                        completed++;
                        const progress = (completed / items.length) * 100;
                        progressBar.style.width = progress + '%';

                        if (completed === items.length) {{
                            {"" if not self.enable_bulk_download else f'''
                            document.getElementById('{widget_id}-batch-download').classList.remove('hidden');
                            '''}
                            window.batchQRData = batchData;
                        }}
                    }}, index * 100); // Stagger generation to prevent blocking
                }});
            }}

            function generateBatchItem(content, index, batchData) {{
                if (!qrCodeLib) return;

                const listContainer = document.getElementById('{widget_id}-batch-list');

                qrCodeLib.toDataURL(content, {{
                    width: 128,
                    height: 128,
                    errorCorrectionLevel: 'M'
                }}, function(err, url) {{
                    if (!err) {{
                        batchData.push({{ content, dataURL: url, index }});

                        const itemDiv = document.createElement('div');
                        itemDiv.className = 'batch-item';
                        itemDiv.innerHTML = `
                            <span>${{content.substring(0, 50)}}${{content.length > 50 ? '...' : ''}}</span>
                            <button class="btn btn-sm" onclick="downloadBatchItem(${{index}})">
                                <i class="fas fa-download"></i>
                            </button>
                        `;
                        listContainer.appendChild(itemDiv);
                    }}
                }});
            }}

            window.downloadBatchItem = function(index) {{
                const item = window.batchQRData[index];
                if (item) {{
                    const link = document.createElement('a');
                    link.download = `qrcode-${{index + 1}}.png`;
                    link.href = item.dataURL;
                    link.click();
                }}
            }};

            function downloadBatchZip() {{
                // For a full implementation, you'd use a library like JSZip
                alert('{gettext("Batch ZIP download requires JSZip library integration")}');
            }}

            function addToHistory(content, timestamp, type = 'generated') {{
                const historyItem = {{
                    content,
                    timestamp,
                    type,
                    id: Date.now() + Math.random()
                }};

                qrHistory.unshift(historyItem);

                // Limit history size
                if (qrHistory.length > {self.max_history_items}) {{
                    qrHistory = qrHistory.slice(0, {self.max_history_items});
                }}

                localStorage.setItem('{widget_id}-history', JSON.stringify(qrHistory));
                loadHistory();
            }}

            function loadHistory() {{
                const historyList = document.getElementById('{widget_id}-history-list');
                if (!historyList) return;

                if (qrHistory.length === 0) {{
                    historyList.innerHTML = `
                        <div style="padding: 40px; text-align: center; color: #999;">
                            <i class="fas fa-history" style="font-size: 48px; margin-bottom: 12px;"></i>
                            <p>{gettext("No QR codes in history yet")}</p>
                        </div>
                    `;
                    return;
                }}

                historyList.innerHTML = qrHistory.map(item => `
                    <div id="{widget_id}-history-item" class="qr-history-item">
                        <div class="qr-history-content">
                            <div class="qr-history-text">${{item.content}}</div>
                            <div class="qr-history-meta">
                                ${{new Date(item.timestamp).toLocaleString()}} • ${{item.type}}
                            </div>
                        </div>
                        <div class="qr-history-actions">
                            <button class="btn btn-sm" onclick="loadFromHistory('${{item.id}}')">
                                <i class="fas fa-redo"></i>
                            </button>
                            <button class="btn btn-sm btn-secondary" onclick="removeFromHistory('${{item.id}}')">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                `).join('');
            }}

            window.loadFromHistory = function(itemId) {{
                const item = qrHistory.find(h => h.id == itemId);
                if (item) {{
                    document.getElementById('{widget_id}-content-input').value = item.content;
                    document.getElementById('{widget_id}').value = item.content;

                    // Switch to generate tab
                    document.querySelector('#{widget_id}-tabs .tab-btn[data-tab="generate"]').click();
                    generateQRCode();
                }}
            }};

            window.removeFromHistory = function(itemId) {{
                qrHistory = qrHistory.filter(h => h.id != itemId);
                localStorage.setItem('{widget_id}-history', JSON.stringify(qrHistory));
                loadHistory();
            }};

            // Initialize when DOM is ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initQRWidget);
            }} else {{
                initQRWidget();
            }}

        }})();
        </script>
        '''