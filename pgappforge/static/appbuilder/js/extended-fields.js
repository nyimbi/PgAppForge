/*
 * Extended Fields JavaScript for Flask-AppBuilder
 * Interactive functionality for advanced field types
 */

(function(window, document) {
    'use strict';

    // ==============================================
    // Utility Functions
    // ==============================================
    
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    function throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
    
    function generateId() {
        return Math.random().toString(36).substr(2, 9);
    }
    
    function hexToRgb(hex) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
        } : null;
    }
    
    function rgbToHex(r, g, b) {
        return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
    }

    // ==============================================
    // Rich Text Editor Field
    // ==============================================
    
    class RichTextEditorField {
        constructor(container) {
            this.container = container;
            this.editorType = container.dataset.editorType;
            this.textarea = container.querySelector('.richtext-editor');
            this.metadataInput = container.querySelector('input[type="hidden"]');
            this.statsElement = container.querySelector('.richtext-stats');
            
            this.init();
        }
        
        async init() {
            await this.loadEditor();
            this.setupEventListeners();
            this.updateStats();
        }
        
        async loadEditor() {
            const editorId = this.textarea.id;
            const height = this.textarea.dataset.height || 300;
            
            switch (this.editorType) {
                case 'tinymce':
                    await this.initTinyMCE(editorId, height);
                    break;
                case 'ckeditor':
                    await this.initCKEditor(editorId, height);
                    break;
                case 'quill':
                    await this.initQuill(editorId, height);
                    break;
                case 'summernote':
                    await this.initSummernote(editorId, height);
                    break;
                default:
                    this.initBasicEditor(editorId, height);
            }
        }
        
        async initTinyMCE(editorId, height) {
            if (typeof tinymce !== 'undefined') {
                tinymce.init({
                    selector: `#${editorId}`,
                    height: height,
                    plugins: 'advlist autolink lists link image charmap print preview anchor searchreplace visualblocks code fullscreen insertdatetime media table paste code help wordcount',
                    toolbar: 'undo redo | formatselect | bold italic backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | removeformat | help',
                    setup: (editor) => {
                        editor.on('input change', () => {
                            this.updateStats();
                            this.updateMetadata();
                        });
                    }
                });
            }
        }
        
        async initCKEditor(editorId, height) {
            if (typeof ClassicEditor !== 'undefined') {
                const editor = await ClassicEditor.create(document.getElementById(editorId), {
                    toolbar: ['heading', '|', 'bold', 'italic', 'link', 'bulletedList', 'numberedList', '|', 'outdent', 'indent', '|', 'imageUpload', 'blockQuote', 'insertTable', 'mediaEmbed', '|', 'undo', 'redo']
                });
                
                editor.model.document.on('change:data', () => {
                    this.updateStats();
                    this.updateMetadata();
                });
            }
        }
        
        async initQuill(editorId, height) {
            if (typeof Quill !== 'undefined') {
                const quill = new Quill(`#${editorId}`, {
                    theme: 'snow',
                    modules: {
                        toolbar: [
                            [{ 'header': [1, 2, false] }],
                            ['bold', 'italic', 'underline'],
                            ['image', 'code-block']
                        ]
                    }
                });
                
                quill.on('text-change', () => {
                    this.updateStats();
                    this.updateMetadata();
                });
            }
        }
        
        async initSummernote(editorId, height) {
            if (typeof $ !== 'undefined' && $.fn.summernote) {
                $(`#${editorId}`).summernote({
                    height: height,
                    callbacks: {
                        onChange: () => {
                            this.updateStats();
                            this.updateMetadata();
                        }
                    }
                });
            }
        }
        
        initBasicEditor(editorId, height) {
            this.textarea.style.height = height + 'px';
            this.textarea.addEventListener('input', () => {
                this.updateStats();
                this.updateMetadata();
            });
        }
        
        setupEventListeners() {
            // Basic textarea fallback
            this.textarea.addEventListener('input', debounce(() => {
                this.updateStats();
                this.updateMetadata();
            }, 300));
        }
        
        updateStats() {
            const content = this.getContent();
            const textOnly = content.replace(/<[^>]*>/g, '');
            const wordCount = textOnly.trim().split(/\s+/).filter(word => word.length > 0).length;
            const charCount = textOnly.length;
            const readingTime = Math.max(1, Math.ceil(wordCount / 200));
            
            const wordCountEl = this.statsElement.querySelector('.word-count');
            const charCountEl = this.statsElement.querySelector('.char-count');
            const readingTimeEl = this.statsElement.querySelector('.reading-time');
            
            if (wordCountEl) wordCountEl.textContent = `${wordCount} words`;
            if (charCountEl) charCountEl.textContent = `${charCount} characters`;
            if (readingTimeEl) readingTimeEl.textContent = `${readingTime} min read`;
        }
        
        updateMetadata() {
            const content = this.getContent();
            const textOnly = content.replace(/<[^>]*>/g, '');
            const wordCount = textOnly.trim().split(/\s+/).filter(word => word.length > 0).length;
            const charCount = textOnly.length;
            const readingTime = Math.max(1, Math.ceil(wordCount / 200));
            
            // Extract images and links
            const images = Array.from(content.matchAll(/<img[^>]+src=["']([^"']+)["'][^>]*>/g)).map(match => match[1]);
            const links = Array.from(content.matchAll(/<a[^>]+href=["']([^"']+)["'][^>]*>/g)).map(match => match[1]);
            
            const metadata = {
                content: content,
                format: 'html',
                word_count: wordCount,
                character_count: charCount,
                reading_time: readingTime,
                images: images,
                links: links,
                created_at: new Date().toISOString()
            };
            
            if (this.metadataInput) {
                this.metadataInput.value = JSON.stringify(metadata);
            }
        }
        
        getContent() {
            if (typeof tinymce !== 'undefined' && tinymce.get(this.textarea.id)) {
                return tinymce.get(this.textarea.id).getContent();
            } else if (typeof ClassicEditor !== 'undefined') {
                // CKEditor content handling would go here
            } else if (typeof Quill !== 'undefined') {
                // Quill content handling would go here
            }
            return this.textarea.value;
        }
    }

    // ==============================================
    // Code Editor Field
    // ==============================================
    
    class CodeEditorField {
        constructor(container) {
            this.container = container;
            this.editorElement = container.querySelector('.code-editor');
            this.dataInput = container.querySelector('input[type="hidden"]');
            this.statsElement = container.querySelector('.code-editor-stats');
            this.toolbar = container.querySelector('.code-editor-toolbar');
            this.editor = null;
            
            this.init();
        }
        
        async init() {
            await this.loadMonacoEditor();
            this.setupToolbar();
            this.updateStats();
        }
        
        async loadMonacoEditor() {
            if (typeof monaco !== 'undefined') {
                const language = this.editorElement.dataset.language || 'javascript';
                const theme = this.editorElement.dataset.theme || 'vs-dark';
                
                this.editor = monaco.editor.create(this.editorElement, {
                    value: this.editorElement.textContent || '',
                    language: language,
                    theme: theme,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                    automaticLayout: true
                });
                
                this.editor.onDidChangeModelContent(() => {
                    this.updateStats();
                    this.updateData();
                });
            } else {
                // Fallback to basic textarea
                this.initBasicEditor();
            }
        }
        
        initBasicEditor() {
            const textarea = document.createElement('textarea');
            textarea.className = 'code-editor-fallback';
            textarea.style.cssText = 'width: 100%; height: 400px; font-family: monospace; padding: 10px;';
            textarea.value = this.editorElement.textContent || '';
            
            this.editorElement.appendChild(textarea);
            
            textarea.addEventListener('input', () => {
                this.updateStats();
                this.updateData();
            });
        }
        
        setupToolbar() {
            const languageSelector = this.toolbar.querySelector('.language-selector');
            const themeSelector = this.toolbar.querySelector('.theme-selector');
            const formatBtn = this.toolbar.querySelector('.format-code-btn');
            const fullscreenBtn = this.toolbar.querySelector('.fullscreen-btn');
            
            if (languageSelector) {
                languageSelector.addEventListener('change', (e) => {
                    if (this.editor) {
                        monaco.editor.setModelLanguage(this.editor.getModel(), e.target.value);
                    }
                });
            }
            
            if (themeSelector) {
                themeSelector.addEventListener('change', (e) => {
                    if (this.editor) {
                        monaco.editor.setTheme(e.target.value);
                    }
                });
            }
            
            if (formatBtn) {
                formatBtn.addEventListener('click', () => {
                    if (this.editor) {
                        this.editor.getAction('editor.action.formatDocument').run();
                    }
                });
            }
            
            if (fullscreenBtn) {
                fullscreenBtn.addEventListener('click', () => {
                    this.toggleFullscreen();
                });
            }
        }
        
        toggleFullscreen() {
            this.container.classList.toggle('fullscreen');
            if (this.editor) {
                this.editor.layout();
            }
        }
        
        updateStats() {
            const content = this.getContent();
            const lines = content.split('\n').length;
            const chars = content.length;
            
            const lineCountEl = this.statsElement.querySelector('.line-count');
            const charCountEl = this.statsElement.querySelector('.char-count');
            const syntaxStatusEl = this.statsElement.querySelector('.syntax-status');
            
            if (lineCountEl) lineCountEl.textContent = `${lines} lines`;
            if (charCountEl) charCountEl.textContent = `${chars} characters`;
            
            // Basic syntax validation
            this.validateSyntax(syntaxStatusEl);
        }
        
        validateSyntax(statusElement) {
            if (!statusElement) return;
            
            const content = this.getContent();
            const language = this.editorElement.dataset.language;
            
            try {
                if (language === 'javascript' || language === 'typescript') {
                    // Basic JS/TS validation (simplified)
                    new Function(content);
                    statusElement.textContent = '✓ No errors';
                    statusElement.className = 'syntax-status success';
                } else if (language === 'json') {
                    JSON.parse(content);
                    statusElement.textContent = '✓ Valid JSON';
                    statusElement.className = 'syntax-status success';
                } else {
                    statusElement.textContent = '✓ No errors detected';
                    statusElement.className = 'syntax-status success';
                }
            } catch (error) {
                statusElement.textContent = `✗ ${error.message}`;
                statusElement.className = 'syntax-status error';
            }
        }
        
        updateData() {
            const data = {
                code: this.getContent(),
                language: this.editorElement.dataset.language || 'text',
                theme: this.editorElement.dataset.theme || 'vs-dark',
                line_numbers: true,
                word_wrap: false,
                font_size: 14,
                tab_size: 4
            };
            
            if (this.dataInput) {
                this.dataInput.value = JSON.stringify(data);
            }
        }
        
        getContent() {
            if (this.editor) {
                return this.editor.getValue();
            } else {
                const textarea = this.editorElement.querySelector('.code-editor-fallback');
                return textarea ? textarea.value : '';
            }
        }
    }

    // ==============================================
    // DateTime Picker Field
    // ==============================================
    
    class DateTimePickerField {
        constructor(container) {
            this.container = container;
            this.input = container.querySelector('.datetime-picker-input');
            this.timezoneSelector = container.querySelector('.timezone-selector');
            this.formatSelector = container.querySelector('.format-selector');
            this.preview = container.querySelector('.formatted-datetime');
            this.dataInput = container.querySelector('input[type="hidden"]');
            
            this.init();
        }
        
        init() {
            this.setupEventListeners();
            this.updatePreview();
        }
        
        setupEventListeners() {
            if (this.input) {
                this.input.addEventListener('change', () => this.updatePreview());
            }
            
            if (this.timezoneSelector) {
                this.timezoneSelector.addEventListener('change', () => this.updatePreview());
            }
            
            if (this.formatSelector) {
                this.formatSelector.addEventListener('change', () => this.updatePreview());
            }
        }
        
        updatePreview() {
            const datetime = this.input ? this.input.value : '';
            const timezone = this.timezoneSelector ? this.timezoneSelector.value : 'UTC';
            const format = this.formatSelector ? this.formatSelector.value : 'YYYY-MM-DD HH:mm:ss';
            
            if (datetime) {
                try {
                    const date = new Date(datetime);
                    const formatted = this.formatDateTime(date, format, timezone);
                    
                    if (this.preview) {
                        this.preview.textContent = formatted;
                    }
                    
                    this.updateData(date, timezone, format);
                } catch (error) {
                    if (this.preview) {
                        this.preview.textContent = 'Invalid date/time';
                    }
                }
            } else {
                if (this.preview) {
                    this.preview.textContent = '';
                }
            }
        }
        
        formatDateTime(date, format, timezone) {
            // Simple formatting - in production, use a library like moment.js or date-fns
            const options = {
                timeZone: timezone,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            };
            
            if (format.includes('YYYY-MM-DD')) {
                return date.toLocaleString('sv-SE', options).replace(' ', ' ');
            } else if (format.includes('MM/DD/YYYY')) {
                return date.toLocaleString('en-US', options);
            } else if (format.includes('DD/MM/YYYY')) {
                return date.toLocaleString('en-GB', options);
            } else if (format === 'YYYY-MM-DD') {
                return date.toLocaleDateString('sv-SE');
            }
            
            return date.toLocaleString('sv-SE', options);
        }
        
        updateData(date, timezone, format) {
            const data = {
                datetime: date.toISOString(),
                timezone: timezone,
                format: format,
                locale: 'en',
                calendar_type: 'gregorian'
            };
            
            if (this.dataInput) {
                this.dataInput.value = JSON.stringify(data);
            }
        }
    }

    // ==============================================
    // Color Picker Field
    // ==============================================
    
    class ColorPickerField {
        constructor(container) {
            this.container = container;
            this.colorInput = container.querySelector('.color-picker-input');
            this.preview = container.querySelector('.color-preview');
            this.hexInput = container.querySelector('.hex-input');
            this.rgbInput = container.querySelector('.rgb-input');
            this.hslInput = container.querySelector('.hsl-input');
            this.alphaSlider = container.querySelector('.alpha-slider');
            this.alphaValue = container.querySelector('.alpha-value');
            this.dataInput = container.querySelector('input[type="hidden"]');
            this.swatches = container.querySelectorAll('.swatch');
            
            this.init();
        }
        
        init() {
            this.setupEventListeners();
            this.updateAllFormats();
        }
        
        setupEventListeners() {
            if (this.colorInput) {
                this.colorInput.addEventListener('input', () => this.updateAllFormats());
            }
            
            if (this.hexInput) {
                this.hexInput.addEventListener('input', debounce(() => this.updateFromHex(), 300));
            }
            
            if (this.rgbInput) {
                this.rgbInput.addEventListener('input', debounce(() => this.updateFromRgb(), 300));
            }
            
            if (this.alphaSlider) {
                this.alphaSlider.addEventListener('input', () => this.updateAlpha());
            }
            
            this.swatches.forEach(swatch => {
                swatch.addEventListener('click', () => {
                    const color = swatch.dataset.color;
                    this.setColor(color);
                });
            });
        }
        
        setColor(hex) {
            if (this.colorInput) {
                this.colorInput.value = hex;
            }
            this.updateAllFormats();
        }
        
        updateAllFormats() {
            const hex = this.colorInput ? this.colorInput.value : '#000000';
            const rgb = hexToRgb(hex);
            
            if (rgb) {
                // Update preview
                if (this.preview) {
                    this.preview.style.backgroundColor = hex;
                }
                
                // Update format inputs
                if (this.hexInput) {
                    this.hexInput.value = hex;
                }
                
                if (this.rgbInput) {
                    this.rgbInput.value = `${rgb.r}, ${rgb.g}, ${rgb.b}`;
                }
                
                if (this.hslInput) {
                    const hsl = this.rgbToHsl(rgb.r, rgb.g, rgb.b);
                    this.hslInput.value = `${hsl.h}, ${hsl.s}%, ${hsl.l}%`;
                }
                
                this.updateData();
            }
        }
        
        updateFromHex() {
            const hex = this.hexInput ? this.hexInput.value : '#000000';
            if (/^#[0-9A-F]{6}$/i.test(hex)) {
                this.setColor(hex);
            }
        }
        
        updateFromRgb() {
            const rgb = this.rgbInput ? this.rgbInput.value : '0, 0, 0';
            const parts = rgb.split(',').map(s => parseInt(s.trim()));
            
            if (parts.length === 3 && parts.every(p => !isNaN(p) && p >= 0 && p <= 255)) {
                const hex = rgbToHex(parts[0], parts[1], parts[2]);
                this.setColor(hex);
            }
        }
        
        updateAlpha() {
            const alpha = this.alphaSlider ? parseFloat(this.alphaSlider.value) : 1.0;
            
            if (this.alphaValue) {
                this.alphaValue.textContent = alpha.toFixed(2);
            }
            
            this.updateData();
        }
        
        rgbToHsl(r, g, b) {
            r /= 255;
            g /= 255;
            b /= 255;
            
            const max = Math.max(r, g, b);
            const min = Math.min(r, g, b);
            let h, s, l = (max + min) / 2;
            
            if (max === min) {
                h = s = 0; // achromatic
            } else {
                const d = max - min;
                s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
                
                switch (max) {
                    case r: h = (g - b) / d + (g < b ? 6 : 0); break;
                    case g: h = (b - r) / d + 2; break;
                    case b: h = (r - g) / d + 4; break;
                }
                h /= 6;
            }
            
            return {
                h: Math.round(h * 360),
                s: Math.round(s * 100),
                l: Math.round(l * 100)
            };
        }
        
        updateData() {
            const hex = this.colorInput ? this.colorInput.value : '#000000';
            const rgb = hexToRgb(hex);
            const alpha = this.alphaSlider ? parseFloat(this.alphaSlider.value) : 1.0;
            
            if (rgb) {
                const hsl = this.rgbToHsl(rgb.r, rgb.g, rgb.b);
                
                const data = {
                    hex: hex,
                    rgb: [rgb.r, rgb.g, rgb.b],
                    hsl: [hsl.h, hsl.s, hsl.l],
                    alpha: alpha
                };
                
                if (this.dataInput) {
                    this.dataInput.value = JSON.stringify(data);
                }
            }
        }
    }

    // ==============================================
    // Signature Field
    // ==============================================
    
    class SignatureField {
        constructor(container) {
            this.container = container;
            this.canvas = container.querySelector('.signature-canvas');
            this.dataInput = container.querySelector('input[type="hidden"]');
            this.clearBtn = container.querySelector('.clear-signature');
            this.undoBtn = container.querySelector('.undo-signature');
            this.penSize = container.querySelector('.pen-size');
            this.penColor = container.querySelector('.pen-color');
            
            this.ctx = null;
            this.isDrawing = false;
            this.lastX = 0;
            this.lastY = 0;
            this.strokes = [];
            this.currentStroke = [];
            
            this.init();
        }
        
        init() {
            if (this.canvas) {
                this.ctx = this.canvas.getContext('2d');
                this.setupCanvas();
                this.setupEventListeners();
                this.loadExistingSignature();
            }
        }
        
        setupCanvas() {
            this.ctx.lineCap = 'round';
            this.ctx.lineJoin = 'round';
            this.updatePenSettings();
        }
        
        setupEventListeners() {
            // Mouse events
            this.canvas.addEventListener('mousedown', (e) => this.startDrawing(e));
            this.canvas.addEventListener('mousemove', (e) => this.draw(e));
            this.canvas.addEventListener('mouseup', () => this.stopDrawing());
            this.canvas.addEventListener('mouseout', () => this.stopDrawing());
            
            // Touch events
            this.canvas.addEventListener('touchstart', (e) => {
                e.preventDefault();
                const touch = e.touches[0];
                const mouseEvent = new MouseEvent('mousedown', {
                    clientX: touch.clientX,
                    clientY: touch.clientY
                });
                this.canvas.dispatchEvent(mouseEvent);
            });
            
            this.canvas.addEventListener('touchmove', (e) => {
                e.preventDefault();
                const touch = e.touches[0];
                const mouseEvent = new MouseEvent('mousemove', {
                    clientX: touch.clientX,
                    clientY: touch.clientY
                });
                this.canvas.dispatchEvent(mouseEvent);
            });
            
            this.canvas.addEventListener('touchend', (e) => {
                e.preventDefault();
                const mouseEvent = new MouseEvent('mouseup', {});
                this.canvas.dispatchEvent(mouseEvent);
            });
            
            // Controls
            if (this.clearBtn) {
                this.clearBtn.addEventListener('click', () => this.clearSignature());
            }
            
            if (this.undoBtn) {
                this.undoBtn.addEventListener('click', () => this.undoStroke());
            }
            
            if (this.penSize) {
                this.penSize.addEventListener('change', () => this.updatePenSettings());
            }
            
            if (this.penColor) {
                this.penColor.addEventListener('change', () => this.updatePenSettings());
            }
        }
        
        updatePenSettings() {
            const size = this.penSize ? parseInt(this.penSize.value) : 2;
            const color = this.penColor ? this.penColor.value : '#000000';
            
            this.ctx.lineWidth = size;
            this.ctx.strokeStyle = color;
        }
        
        startDrawing(e) {
            this.isDrawing = true;
            this.canvas.classList.add('signing');
            
            const rect = this.canvas.getBoundingClientRect();
            this.lastX = e.clientX - rect.left;
            this.lastY = e.clientY - rect.top;
            
            this.currentStroke = [{
                x: this.lastX,
                y: this.lastY,
                size: this.ctx.lineWidth,
                color: this.ctx.strokeStyle
            }];
        }
        
        draw(e) {
            if (!this.isDrawing) return;
            
            const rect = this.canvas.getBoundingClientRect();
            const currentX = e.clientX - rect.left;
            const currentY = e.clientY - rect.top;
            
            this.ctx.beginPath();
            this.ctx.moveTo(this.lastX, this.lastY);
            this.ctx.lineTo(currentX, currentY);
            this.ctx.stroke();
            
            this.currentStroke.push({
                x: currentX,
                y: currentY,
                size: this.ctx.lineWidth,
                color: this.ctx.strokeStyle
            });
            
            this.lastX = currentX;
            this.lastY = currentY;
        }
        
        stopDrawing() {
            if (!this.isDrawing) return;
            
            this.isDrawing = false;
            this.canvas.classList.remove('signing');
            
            if (this.currentStroke.length > 0) {
                this.strokes.push([...this.currentStroke]);
                this.currentStroke = [];
                this.updateData();
            }
        }
        
        clearSignature() {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            this.strokes = [];
            this.updateData();
        }
        
        undoStroke() {
            if (this.strokes.length > 0) {
                this.strokes.pop();
                this.redrawSignature();
                this.updateData();
            }
        }
        
        redrawSignature() {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            
            this.strokes.forEach(stroke => {
                if (stroke.length > 0) {
                    const firstPoint = stroke[0];
                    this.ctx.beginPath();
                    this.ctx.moveTo(firstPoint.x, firstPoint.y);
                    this.ctx.lineWidth = firstPoint.size;
                    this.ctx.strokeStyle = firstPoint.color;
                    
                    stroke.forEach((point, index) => {
                        if (index > 0) {
                            this.ctx.lineTo(point.x, point.y);
                        }
                    });
                    
                    this.ctx.stroke();
                }
            });
        }
        
        loadExistingSignature() {
            const existingData = this.canvas.dataset.signatureData;
            if (existingData) {
                try {
                    const img = new Image();
                    img.onload = () => {
                        this.ctx.drawImage(img, 0, 0);
                    };
                    img.src = 'data:image/png;base64,' + existingData;
                } catch (error) {
                    console.warn('Could not load existing signature:', error);
                }
            }
        }
        
        updateData() {
            const signatureData = this.canvas.toDataURL('image/png').split(',')[1];
            
            const data = {
                signature_data: signatureData,
                format: 'image/png',
                width: this.canvas.width,
                height: this.canvas.height,
                timestamp: new Date().toISOString()
            };
            
            if (this.dataInput) {
                this.dataInput.value = JSON.stringify(data);
            }
        }
    }

    // ==============================================
    // Rating Field
    // ==============================================
    
    class RatingField {
        constructor(container) {
            this.container = container;
            this.stars = container.querySelectorAll('.star');
            this.currentRating = container.querySelector('.current-rating');
            this.reviewText = container.querySelector('.review-text');
            this.dataInput = container.querySelector('input[type="hidden"]');
            this.rating = 0;
            this.maxRating = parseInt(container.querySelector('.star-rating').dataset.max) || 5;
            
            this.init();
        }
        
        init() {
            this.setupEventListeners();
            this.loadExistingRating();
        }
        
        setupEventListeners() {
            this.stars.forEach((star, index) => {
                star.addEventListener('click', () => {
                    this.setRating(index + 1);
                });
                
                star.addEventListener('mouseenter', () => {
                    this.highlightStars(index + 1);
                });
            });
            
            const starRating = this.container.querySelector('.star-rating');
            if (starRating) {
                starRating.addEventListener('mouseleave', () => {
                    this.highlightStars(this.rating);
                });
            }
            
            if (this.reviewText) {
                this.reviewText.addEventListener('input', debounce(() => {
                    this.updateData();
                }, 300));
            }
        }
        
        setRating(rating) {
            this.rating = Math.max(0, Math.min(rating, this.maxRating));
            this.highlightStars(this.rating);
            
            if (this.currentRating) {
                this.currentRating.textContent = this.rating;
            }
            
            this.updateData();
        }
        
        highlightStars(rating) {
            this.stars.forEach((star, index) => {
                star.classList.remove('filled', 'half-filled');
                
                if (index < Math.floor(rating)) {
                    star.classList.add('filled');
                } else if (index < rating && rating % 1 !== 0) {
                    star.classList.add('half-filled');
                }
            });
        }
        
        loadExistingRating() {
            const existingRating = parseFloat(this.container.querySelector('.star-rating').dataset.rating) || 0;
            this.setRating(existingRating);
        }
        
        updateData() {
            const data = {
                rating: this.rating,
                max_rating: this.maxRating,
                review: this.reviewText ? this.reviewText.value : null,
                timestamp: new Date().toISOString()
            };
            
            if (this.dataInput) {
                this.dataInput.value = JSON.stringify(data);
            }
        }
    }

    // ==============================================
    // QR Code Field
    // ==============================================
    
    class QRCodeField {
        constructor(container) {
            this.container = container;
            this.contentTextarea = container.querySelector('.qrcode-content');
            this.generateBtn = container.querySelector('.generate-qr');
            this.preview = container.querySelector('.qrcode-preview');
            this.downloadBtn = container.querySelector('.download-qr');
            this.copyBtn = container.querySelector('.copy-qr');
            this.scanBtn = container.querySelector('.scan-qr');
            this.scanner = container.querySelector('.qr-scanner');
            this.canvas = container.querySelector('.qr-canvas');
            this.dataInput = container.querySelector('input[type="hidden"]');
            
            this.init();
        }
        
        init() {
            this.setupEventListeners();
        }
        
        setupEventListeners() {
            if (this.generateBtn) {
                this.generateBtn.addEventListener('click', () => this.generateQRCode());
            }
            
            if (this.downloadBtn) {
                this.downloadBtn.addEventListener('click', () => this.downloadQRCode());
            }
            
            if (this.copyBtn) {
                this.copyBtn.addEventListener('click', () => this.copyQRCode());
            }
            
            if (this.scanBtn) {
                this.scanBtn.addEventListener('click', () => this.startScanning());
            }
            
            if (this.contentTextarea) {
                this.contentTextarea.addEventListener('input', debounce(() => {
                    if (this.contentTextarea.value.trim()) {
                        this.generateQRCode();
                    }
                }, 500));
            }
        }
        
        async generateQRCode() {
            const content = this.contentTextarea ? this.contentTextarea.value.trim() : '';
            if (!content) return;
            
            try {
                // Using a simple QR code generation approach
                // In production, use a proper QR code library like qrcode.js
                const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(content)}`;
                
                const img = document.createElement('img');
                img.src = qrCodeUrl;
                img.alt = 'QR Code';
                img.style.maxWidth = '100%';
                
                if (this.preview) {
                    this.preview.innerHTML = '';
                    this.preview.appendChild(img);
                }
                
                // Convert to base64 for storage
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 200;
                    canvas.height = 200;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    const base64 = canvas.toDataURL('image/png').split(',')[1];
                    
                    this.updateData(content, base64);
                };
                
            } catch (error) {
                console.error('Error generating QR code:', error);
            }
        }
        
        downloadQRCode() {
            const img = this.preview ? this.preview.querySelector('img') : null;
            if (img) {
                const link = document.createElement('a');
                link.download = 'qrcode.png';
                link.href = img.src;
                link.click();
            }
        }
        
        async copyQRCode() {
            const img = this.preview ? this.preview.querySelector('img') : null;
            if (img) {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = 200;
                    canvas.height = 200;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    
                    canvas.toBlob(async (blob) => {
                        if (navigator.clipboard && window.ClipboardItem) {
                            await navigator.clipboard.write([
                                new ClipboardItem({ 'image/png': blob })
                            ]);
                            alert('QR code copied to clipboard!');
                        }
                    });
                } catch (error) {
                    console.error('Error copying QR code:', error);
                }
            }
        }
        
        async startScanning() {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                alert('Camera access is not supported in this browser');
                return;
            }
            
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
                
                if (this.scanner) {
                    this.scanner.srcObject = stream;
                    this.scanner.style.display = 'block';
                    this.scanner.play();
                    
                    // Start scanning for QR codes
                    this.scanForQRCode(stream);
                }
            } catch (error) {
                console.error('Error accessing camera:', error);
                alert('Could not access camera: ' + error.message);
            }
        }
        
        scanForQRCode(stream) {
            // QR code scanning would require a library like jsQR
            // This is a placeholder for the scanning functionality
            setTimeout(() => {
                if (this.scanner) {
                    this.scanner.style.display = 'none';
                    stream.getTracks().forEach(track => track.stop());
                }
            }, 10000); // Auto-stop after 10 seconds
        }
        
        updateData(content, qrImage) {
            const data = {
                content: content,
                qr_code_image: qrImage,
                error_correction: 'M',
                size: 200,
                border: 4,
                format: 'PNG'
            };
            
            if (this.dataInput) {
                this.dataInput.value = JSON.stringify(data);
            }
        }
    }

    // ==============================================
    // Password Strength Field
    // ==============================================
    
    class PasswordStrengthField {
        constructor(container) {
            this.container = container;
            this.passwordInput = container.querySelector('.password-input');
            this.toggleBtn = container.querySelector('.toggle-password');
            this.generateBtn = container.querySelector('.generate-password');
            this.strengthBar = container.querySelector('.strength-fill');
            this.strengthText = container.querySelector('.strength-text');
            this.requirements = container.querySelectorAll('.requirement');
            this.suggestions = container.querySelector('.suggestion-list');
            
            this.init();
        }
        
        init() {
            this.setupEventListeners();
        }
        
        setupEventListeners() {
            if (this.passwordInput) {
                this.passwordInput.addEventListener('input', () => {
                    this.checkPasswordStrength();
                });
            }
            
            if (this.toggleBtn) {
                this.toggleBtn.addEventListener('click', () => {
                    this.togglePasswordVisibility();
                });
            }
            
            if (this.generateBtn) {
                this.generateBtn.addEventListener('click', () => {
                    this.generatePassword();
                });
            }
        }
        
        checkPasswordStrength() {
            const password = this.passwordInput ? this.passwordInput.value : '';
            const analysis = this.analyzePassword(password);
            
            this.updateStrengthMeter(analysis);
            this.updateRequirements(analysis);
            this.updateSuggestions(analysis);
        }
        
        analyzePassword(password) {
            const length = password.length;
            const hasUpper = /[A-Z]/.test(password);
            const hasLower = /[a-z]/.test(password);
            const hasNumbers = /\d/.test(password);
            const hasSymbols = /[!@#$%^&*(),.?":{}|<>]/.test(password);
            
            let score = 0;
            const suggestions = [];
            
            // Length scoring
            if (length >= 12) {
                score += 25;
            } else if (length >= 8) {
                score += 15;
            } else {
                suggestions.push('Use at least 8 characters');
            }
            
            // Character type scoring
            if (hasUpper) {
                score += 15;
            } else {
                suggestions.push('Include uppercase letters');
            }
            
            if (hasLower) {
                score += 15;
            } else {
                suggestions.push('Include lowercase letters');
            }
            
            if (hasNumbers) {
                score += 15;
            } else {
                suggestions.push('Include numbers');
            }
            
            if (hasSymbols) {
                score += 20;
            } else {
                suggestions.push('Include special characters');
            }
            
            // Common patterns penalty
            const commonPatterns = ['123', 'abc', 'password', 'admin', 'user'];
            for (const pattern of commonPatterns) {
                if (password.toLowerCase().includes(pattern)) {
                    score -= 10;
                    suggestions.push('Avoid common patterns');
                    break;
                }
            }
            
            // Sequential characters penalty
            if (/(.)\1{2,}/.test(password)) {
                score -= 5;
                suggestions.push('Avoid repeating characters');
            }
            
            score = Math.max(0, Math.min(100, score));
            
            let strengthLabel;
            if (score >= 90) {
                strengthLabel = 'Very Strong';
            } else if (score >= 70) {
                strengthLabel = 'Strong';
            } else if (score >= 50) {
                strengthLabel = 'Good';
            } else if (score >= 30) {
                strengthLabel = 'Fair';
            } else {
                strengthLabel = 'Weak';
            }
            
            return {
                score,
                strengthLabel,
                suggestions,
                hasUpper,
                hasLower,
                hasNumbers,
                hasSymbols,
                length
            };
        }
        
        updateStrengthMeter(analysis) {
            if (this.strengthBar) {
                this.strengthBar.style.width = analysis.score + '%';
                this.strengthBar.className = 'strength-fill ' + analysis.strengthLabel.toLowerCase().replace(/\s+/g, '-');
            }
            
            if (this.strengthText) {
                this.strengthText.textContent = analysis.strengthLabel;
            }
        }
        
        updateRequirements(analysis) {
            const requirementData = [
                { element: '[data-check="length"]', met: analysis.length >= 8 },
                { element: '[data-check="uppercase"]', met: analysis.hasUpper },
                { element: '[data-check="lowercase"]', met: analysis.hasLower },
                { element: '[data-check="numbers"]', met: analysis.hasNumbers },
                { element: '[data-check="symbols"]', met: analysis.hasSymbols }
            ];
            
            requirementData.forEach(req => {
                const element = this.container.querySelector(req.element);
                if (element) {
                    const icon = element.querySelector('.check-icon');
                    if (req.met) {
                        element.classList.add('met');
                        if (icon) icon.textContent = '✓';
                    } else {
                        element.classList.remove('met');
                        if (icon) icon.textContent = '○';
                    }
                }
            });
        }
        
        updateSuggestions(analysis) {
            if (this.suggestions && analysis.suggestions.length > 0) {
                this.suggestions.innerHTML = analysis.suggestions
                    .map(suggestion => `<li>${suggestion}</li>`)
                    .join('');
                
                const suggestionsContainer = this.container.querySelector('.password-suggestions');
                if (suggestionsContainer) {
                    suggestionsContainer.style.display = 'block';
                }
            } else {
                const suggestionsContainer = this.container.querySelector('.password-suggestions');
                if (suggestionsContainer) {
                    suggestionsContainer.style.display = 'none';
                }
            }
        }
        
        togglePasswordVisibility() {
            if (this.passwordInput) {
                const isPassword = this.passwordInput.type === 'password';
                this.passwordInput.type = isPassword ? 'text' : 'password';
                
                if (this.toggleBtn) {
                    this.toggleBtn.textContent = isPassword ? '🙈' : '👁';
                }
            }
        }
        
        generatePassword() {
            const charset = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
            const length = 16;
            let password = '';
            
            // Ensure at least one character from each required type
            password += 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)]; // lowercase
            password += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[Math.floor(Math.random() * 26)]; // uppercase
            password += '0123456789'[Math.floor(Math.random() * 10)]; // number
            password += '!@#$%^&*()_+-='[Math.floor(Math.random() * 13)]; // symbol
            
            // Fill the rest randomly
            for (let i = password.length; i < length; i++) {
                password += charset[Math.floor(Math.random() * charset.length)];
            }
            
            // Shuffle the password
            password = password.split('').sort(() => Math.random() - 0.5).join('');
            
            if (this.passwordInput) {
                this.passwordInput.value = password;
                this.checkPasswordStrength();
            }
        }
    }

    // ==============================================
    // Initialization
    // ==============================================
    
    function initExtendedFields() {
        // Initialize all extended fields
        document.querySelectorAll('.richtext-editor-container').forEach(container => {
            new RichTextEditorField(container);
        });
        
        document.querySelectorAll('.code-editor-container').forEach(container => {
            new CodeEditorField(container);
        });
        
        document.querySelectorAll('.datetime-picker-container').forEach(container => {
            new DateTimePickerField(container);
        });
        
        document.querySelectorAll('.color-picker-container').forEach(container => {
            new ColorPickerField(container);
        });
        
        document.querySelectorAll('.signature-container').forEach(container => {
            new SignatureField(container);
        });
        
        document.querySelectorAll('.rating-container').forEach(container => {
            new RatingField(container);
        });
        
        document.querySelectorAll('.qrcode-container').forEach(container => {
            new QRCodeField(container);
        });
        
        document.querySelectorAll('.password-strength-container').forEach(container => {
            new PasswordStrengthField(container);
        });
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExtendedFields);
    } else {
        initExtendedFields();
    }
    
    // Also initialize on dynamic content load
    window.initExtendedFields = initExtendedFields;

})(window, document);