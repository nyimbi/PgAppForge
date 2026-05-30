/**
 * Advanced Fields JavaScript for Flask-AppBuilder
 * Provides interactive functionality for 11 advanced field types
 * Includes Chart, Map, Cropper, Slider, TreeSelect, Calendar, Switch, Markdown, MediaPlayer, Badge, DualListBox
 */

(function(window, document, $) {
    'use strict';

    // Namespace for advanced fields
    window.AdvancedFields = window.AdvancedFields || {};

    // =============================================================================
    // UTILITY FUNCTIONS
    // =============================================================================

    const Utils = {
        /**
         * Generate unique ID
         */
        generateId: function(prefix = 'advanced') {
            return prefix + '_' + Math.random().toString(36).substr(2, 9);
        },

        /**
         * Debounce function
         */
        debounce: function(func, wait, immediate) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    timeout = null;
                    if (!immediate) func(...args);
                };
                const callNow = immediate && !timeout;
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
                if (callNow) func(...args);
            };
        },

        /**
         * Format bytes to human readable
         */
        formatBytes: function(bytes, decimals = 2) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const dm = decimals < 0 ? 0 : decimals;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
        },

        /**
         * Format duration to human readable
         */
        formatDuration: function(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            
            if (h > 0) {
                return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
            }
            return `${m}:${s.toString().padStart(2, '0')}`;
        },

        /**
         * Load external script
         */
        loadScript: function(src, callback) {
            if (document.querySelector(`script[src="${src}"]`)) {
                if (callback) callback();
                return;
            }
            
            const script = document.createElement('script');
            script.src = src;
            script.onload = callback;
            document.head.appendChild(script);
        },

        /**
         * Load external CSS
         */
        loadCSS: function(href) {
            if (document.querySelector(`link[href="${href}"]`)) {
                return;
            }
            
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = href;
            document.head.appendChild(link);
        }
    };

    // =============================================================================
    // CHART FIELD
    // =============================================================================

    class ChartField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                type: 'line',
                width: 400,
                height: 300,
                responsive: true,
                ...options
            };
            this.chart = null;
            this.canvas = null;
            this.init();
        }

        init() {
            this.loadChartJS(() => {
                this.createControls();
                this.createCanvas();
                this.bindEvents();
                this.renderChart();
            });
        }

        loadChartJS(callback) {
            if (window.Chart) {
                callback();
                return;
            }
            
            Utils.loadScript('https://cdn.jsdelivr.net/npm/chart.js', callback);
        }

        createControls() {
            const controlsHtml = `
                <div class="chart-controls">
                    <div class="chart-type-selector">
                        <button type="button" class="chart-type-btn" data-type="line">📈 Line</button>
                        <button type="button" class="chart-type-btn" data-type="bar">📊 Bar</button>
                        <button type="button" class="chart-type-btn" data-type="pie">🥧 Pie</button>
                        <button type="button" class="chart-type-btn" data-type="doughnut">🍩 Doughnut</button>
                        <button type="button" class="chart-type-btn" data-type="radar">🕸️ Radar</button>
                        <button type="button" class="chart-type-btn" data-type="polarArea">⚪ Polar</button>
                    </div>
                    <button type="button" class="chart-action-btn" data-action="randomize">🎲 Random Data</button>
                    <button type="button" class="chart-action-btn" data-action="export">💾 Export</button>
                </div>
            `;
            
            this.container.insertAdjacentHTML('afterbegin', controlsHtml);
            this.updateActiveButton();
        }

        createCanvas() {
            const canvasHtml = `
                <div class="chart-canvas-wrapper">
                    <canvas id="${this.options.id || Utils.generateId('chart')}" 
                            width="${this.options.width}" 
                            height="${this.options.height}"></canvas>
                    <div class="chart-loading" style="display: none;">
                        <div class="chart-loading-spinner"></div>
                    </div>
                </div>
            `;
            
            this.container.insertAdjacentHTML('beforeend', canvasHtml);
            this.canvas = this.container.querySelector('canvas');
        }

        bindEvents() {
            // Chart type selection
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('chart-type-btn')) {
                    const type = e.target.dataset.type;
                    this.changeChartType(type);
                    this.updateActiveButton(type);
                }
                
                if (e.target.classList.contains('chart-action-btn')) {
                    const action = e.target.dataset.action;
                    this.handleAction(action);
                }
            });
        }

        updateActiveButton(type = null) {
            const buttons = this.container.querySelectorAll('.chart-type-btn');
            buttons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.type === (type || this.options.type));
            });
        }

        renderChart() {
            if (!window.Chart || !this.canvas) return;

            const data = this.generateSampleData();
            const config = this.getChartConfig(data);

            if (this.chart) {
                this.chart.destroy();
            }

            this.chart = new Chart(this.canvas, config);
        }

        generateSampleData() {
            const labels = ['January', 'February', 'March', 'April', 'May', 'June'];
            const data1 = labels.map(() => Math.floor(Math.random() * 100));
            const data2 = labels.map(() => Math.floor(Math.random() * 100));

            return {
                labels: labels,
                datasets: [
                    {
                        label: 'Dataset 1',
                        data: data1,
                        backgroundColor: 'rgba(37, 99, 235, 0.2)',
                        borderColor: 'rgba(37, 99, 235, 1)',
                        borderWidth: 2,
                        fill: false
                    },
                    {
                        label: 'Dataset 2',
                        data: data2,
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        borderColor: 'rgba(16, 185, 129, 1)',
                        borderWidth: 2,
                        fill: false
                    }
                ]
            };
        }

        getChartConfig(data) {
            const baseConfig = {
                type: this.options.type,
                data: data,
                options: {
                    responsive: this.options.responsive,
                    maintainAspectRatio: false,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Sample Chart Data'
                        },
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    }
                }
            };

            // Type-specific configurations
            if (['pie', 'doughnut', 'polarArea'].includes(this.options.type)) {
                baseConfig.data = {
                    labels: data.labels,
                    datasets: [{
                        data: data.datasets[0].data,
                        backgroundColor: [
                            'rgba(37, 99, 235, 0.8)',
                            'rgba(16, 185, 129, 0.8)',
                            'rgba(245, 158, 11, 0.8)',
                            'rgba(239, 68, 68, 0.8)',
                            'rgba(139, 92, 246, 0.8)',
                            'rgba(6, 182, 212, 0.8)'
                        ]
                    }]
                };
            }

            return baseConfig;
        }

        changeChartType(type) {
            this.options.type = type;
            this.renderChart();
        }

        handleAction(action) {
            switch (action) {
                case 'randomize':
                    this.renderChart();
                    break;
                case 'export':
                    this.exportChart();
                    break;
            }
        }

        exportChart() {
            if (!this.chart) return;
            
            const url = this.chart.toBase64Image();
            const link = document.createElement('a');
            link.download = 'chart.png';
            link.href = url;
            link.click();
        }

        getData() {
            return this.chart ? this.chart.data : null;
        }

        setData(data) {
            if (this.chart) {
                this.chart.data = data;
                this.chart.update();
            }
        }
    }

    // =============================================================================
    // MAP FIELD
    // =============================================================================

    class MapField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                provider: 'leaflet',
                width: 600,
                height: 400,
                center: [51.505, -0.09],
                zoom: 13,
                enableDrawing: true,
                ...options
            };
            this.map = null;
            this.markers = [];
            this.drawings = [];
            this.init();
        }

        init() {
            this.createControls();
            this.createMapContainer();
            this.loadMapLibrary(() => {
                this.initializeMap();
                this.bindEvents();
            });
        }

        createControls() {
            const controlsHtml = `
                <div class="map-controls">
                    <div class="map-provider-selector">
                        <button type="button" class="map-provider-btn" data-provider="leaflet">🍃 Leaflet</button>
                        <button type="button" class="map-provider-btn" data-provider="google">🗺️ Google</button>
                        <button type="button" class="map-provider-btn" data-provider="mapbox">📍 Mapbox</button>
                    </div>
                    <div class="map-drawing-controls">
                        <button type="button" class="map-tool-btn" data-tool="marker" title="Add Marker">📍</button>
                        <button type="button" class="map-tool-btn" data-tool="circle" title="Draw Circle">⭕</button>
                        <button type="button" class="map-tool-btn" data-tool="polygon" title="Draw Polygon">📐</button>
                        <button type="button" class="map-tool-btn" data-tool="clear" title="Clear All">🗑️</button>
                    </div>
                </div>
            `;
            
            this.container.insertAdjacentHTML('afterbegin', controlsHtml);
            this.updateActiveProvider();
        }

        createMapContainer() {
            const mapHtml = `
                <div id="${this.options.id || Utils.generateId('map')}" 
                     class="map-canvas" 
                     style="width: ${this.options.width}px; height: ${this.options.height}px;"></div>
                <div class="map-coordinates">Lat: 0.000, Lng: 0.000</div>
            `;
            
            this.container.insertAdjacentHTML('beforeend', mapHtml);
            this.mapElement = this.container.querySelector('.map-canvas');
            this.coordsElement = this.container.querySelector('.map-coordinates');
        }

        loadMapLibrary(callback) {
            switch (this.options.provider) {
                case 'leaflet':
                    this.loadLeaflet(callback);
                    break;
                case 'google':
                    this.loadGoogleMaps(callback);
                    break;
                case 'mapbox':
                    this.loadMapbox(callback);
                    break;
                default:
                    this.loadLeaflet(callback);
            }
        }

        loadLeaflet(callback) {
            if (window.L) {
                callback();
                return;
            }
            
            Utils.loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
            Utils.loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', callback);
        }

        loadGoogleMaps(callback) {
            if (window.google && window.google.maps) {
                callback();
                return;
            }
            
            // Note: Requires API key in production
            Utils.loadScript('https://maps.googleapis.com/maps/api/js?key=YOUR_API_KEY&libraries=drawing', callback);
        }

        loadMapbox(callback) {
            if (window.mapboxgl) {
                callback();
                return;
            }
            
            Utils.loadCSS('https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.css');
            Utils.loadScript('https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.js', callback);
        }

        initializeMap() {
            switch (this.options.provider) {
                case 'leaflet':
                    this.initLeafletMap();
                    break;
                case 'google':
                    this.initGoogleMap();
                    break;
                case 'mapbox':
                    this.initMapboxMap();
                    break;
            }
        }

        initLeafletMap() {
            if (!window.L) return;

            this.map = L.map(this.mapElement).setView(this.options.center, this.options.zoom);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(this.map);

            // Mouse move coordinates
            this.map.on('mousemove', (e) => {
                this.coordsElement.textContent = `Lat: ${e.latlng.lat.toFixed(6)}, Lng: ${e.latlng.lng.toFixed(6)}`;
            });

            // Click to add marker
            this.map.on('click', (e) => {
                if (this.currentTool === 'marker') {
                    this.addMarker(e.latlng);
                }
            });
        }

        initGoogleMap() {
            if (!window.google) return;

            this.map = new google.maps.Map(this.mapElement, {
                center: { lat: this.options.center[0], lng: this.options.center[1] },
                zoom: this.options.zoom
            });

            // Mouse move coordinates
            this.map.addListener('mousemove', (e) => {
                this.coordsElement.textContent = `Lat: ${e.latLng.lat().toFixed(6)}, Lng: ${e.latLng.lng().toFixed(6)}`;
            });
        }

        initMapboxMap() {
            if (!window.mapboxgl) return;

            // Note: Requires access token in production
            mapboxgl.accessToken = 'YOUR_MAPBOX_TOKEN';
            
            this.map = new mapboxgl.Map({
                container: this.mapElement,
                style: 'mapbox://styles/mapbox/streets-v11',
                center: [this.options.center[1], this.options.center[0]],
                zoom: this.options.zoom
            });
        }

        bindEvents() {
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('map-provider-btn')) {
                    const provider = e.target.dataset.provider;
                    this.changeProvider(provider);
                }
                
                if (e.target.classList.contains('map-tool-btn')) {
                    const tool = e.target.dataset.tool;
                    this.selectTool(tool);
                }
            });
        }

        updateActiveProvider(provider = null) {
            const buttons = this.container.querySelectorAll('.map-provider-btn');
            buttons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.provider === (provider || this.options.provider));
            });
        }

        changeProvider(provider) {
            this.options.provider = provider;
            this.clearMap();
            this.loadMapLibrary(() => {
                this.initializeMap();
            });
            this.updateActiveProvider(provider);
        }

        selectTool(tool) {
            // Update active tool button
            const buttons = this.container.querySelectorAll('.map-tool-btn');
            buttons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tool === tool);
            });
            
            this.currentTool = tool;
            
            if (tool === 'clear') {
                this.clearAllDrawings();
                this.currentTool = null;
            }
        }

        addMarker(latlng) {
            if (this.options.provider === 'leaflet' && window.L) {
                const marker = L.marker(latlng).addTo(this.map);
                this.markers.push(marker);
            }
        }

        clearAllDrawings() {
            this.markers.forEach(marker => {
                if (this.map && marker.remove) {
                    marker.remove();
                }
            });
            this.markers = [];
            this.drawings = [];
        }

        clearMap() {
            if (this.map) {
                if (this.map.remove) {
                    this.map.remove();
                } else if (this.map.destroy) {
                    this.map.destroy();
                }
            }
        }

        getMapData() {
            return {
                provider: this.options.provider,
                center: this.options.center,
                zoom: this.options.zoom,
                markers: this.markers.map(m => ({ lat: m.getLatLng().lat, lng: m.getLatLng().lng })),
                drawings: this.drawings
            };
        }
    }

    // =============================================================================
    // CROPPER FIELD
    // =============================================================================

    class CropperField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                aspectRatio: null,
                minWidth: 100,
                minHeight: 100,
                ...options
            };
            this.cropper = null;
            this.image = null;
            this.init();
        }

        init() {
            this.loadCropperJS(() => {
                this.createControls();
                this.createCanvas();
                this.bindEvents();
            });
        }

        loadCropperJS(callback) {
            if (window.Cropper) {
                callback();
                return;
            }
            
            Utils.loadCSS('https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.12/cropper.min.css');
            Utils.loadScript('https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.12/cropper.min.js', callback);
        }

        createControls() {
            const controlsHtml = `
                <div class="cropper-controls">
                    <label class="cropper-upload-btn">
                        📁 Upload Image
                        <input type="file" class="cropper-upload-input" accept="image/*">
                    </label>
                    <div class="cropper-action-buttons">
                        <button type="button" class="cropper-action-btn" data-action="rotate-left">↺</button>
                        <button type="button" class="cropper-action-btn" data-action="rotate-right">↻</button>
                        <button type="button" class="cropper-action-btn" data-action="flip-h">⟷</button>
                        <button type="button" class="cropper-action-btn" data-action="flip-v">↕</button>
                        <button type="button" class="cropper-action-btn" data-action="reset">🔄</button>
                        <button type="button" class="cropper-action-btn primary" data-action="crop">✂️ Crop</button>
                    </div>
                </div>
            `;
            
            this.container.insertAdjacentHTML('afterbegin', controlsHtml);
        }

        createCanvas() {
            const canvasHtml = `
                <div class="cropper-canvas-wrapper">
                    <div class="cropper-placeholder">
                        📷 Select an image to crop
                    </div>
                </div>
                <div class="cropper-preview" style="display: none;">
                    <div class="cropper-preview-title">Preview:</div>
                    <img class="cropper-preview-image" alt="Cropped preview">
                </div>
            `;
            
            this.container.insertAdjacentHTML('beforeend', canvasHtml);
            this.canvasWrapper = this.container.querySelector('.cropper-canvas-wrapper');
            this.placeholder = this.container.querySelector('.cropper-placeholder');
            this.previewSection = this.container.querySelector('.cropper-preview');
            this.previewImage = this.container.querySelector('.cropper-preview-image');
        }

        bindEvents() {
            // File upload
            const uploadInput = this.container.querySelector('.cropper-upload-input');
            uploadInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (file) {
                    this.loadImage(file);
                }
            });

            // Action buttons
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('cropper-action-btn')) {
                    const action = e.target.dataset.action;
                    this.handleAction(action);
                }
            });
        }

        loadImage(file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                this.placeholder.style.display = 'none';
                
                if (this.image) {
                    this.image.remove();
                }
                
                this.image = document.createElement('img');
                this.image.src = e.target.result;
                this.image.className = 'cropper-canvas';
                this.canvasWrapper.appendChild(this.image);
                
                this.initCropper();
            };
            reader.readAsDataURL(file);
        }

        initCropper() {
            if (!window.Cropper || !this.image) return;

            if (this.cropper) {
                this.cropper.destroy();
            }

            this.cropper = new Cropper(this.image, {
                aspectRatio: this.options.aspectRatio,
                viewMode: 1,
                autoCropArea: 0.8,
                responsive: true,
                background: false,
                minCropBoxWidth: this.options.minWidth,
                minCropBoxHeight: this.options.minHeight,
                crop: (event) => {
                    // Update preview on crop change
                    this.updatePreview();
                }
            });
        }

        handleAction(action) {
            if (!this.cropper) return;

            switch (action) {
                case 'rotate-left':
                    this.cropper.rotate(-90);
                    break;
                case 'rotate-right':
                    this.cropper.rotate(90);
                    break;
                case 'flip-h':
                    this.cropper.scaleX(-this.cropper.getData().scaleX || -1);
                    break;
                case 'flip-v':
                    this.cropper.scaleY(-this.cropper.getData().scaleY || -1);
                    break;
                case 'reset':
                    this.cropper.reset();
                    break;
                case 'crop':
                    this.performCrop();
                    break;
            }
        }

        updatePreview() {
            if (!this.cropper) return;

            const canvas = this.cropper.getCroppedCanvas({
                width: 200,
                height: 200
            });

            if (canvas) {
                this.previewImage.src = canvas.toDataURL();
                this.previewSection.style.display = 'block';
            }
        }

        performCrop() {
            if (!this.cropper) return;

            const canvas = this.cropper.getCroppedCanvas();
            if (canvas) {
                // Convert to blob and trigger download
                canvas.toBlob((blob) => {
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.download = 'cropped-image.png';
                    link.href = url;
                    link.click();
                    URL.revokeObjectURL(url);
                });
                
                this.updatePreview();
            }
        }

        getCroppedData() {
            return this.cropper ? this.cropper.getData() : null;
        }

        getCroppedCanvas() {
            return this.cropper ? this.cropper.getCroppedCanvas() : null;
        }
    }

    // =============================================================================
    // SLIDER FIELD
    // =============================================================================

    class SliderField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                min: 0,
                max: 100,
                step: 1,
                value: 50,
                rangeMode: false,
                showTicks: true,
                ...options
            };
            this.value = this.options.rangeMode ? [25, 75] : this.options.value;
            this.init();
        }

        init() {
            this.createSlider();
            this.bindEvents();
            this.updateDisplay();
        }

        createSlider() {
            const ticksHtml = this.options.showTicks ? this.generateTicks() : '';
            
            const sliderHtml = `
                <div class="slider-header">
                    <div class="slider-label">${this.options.label || 'Slider'}</div>
                    <div class="slider-value-display">
                        ${Array.isArray(this.value) ? `${this.value[0]} - ${this.value[1]}` : this.value}
                    </div>
                </div>
                <div class="slider-track-container">
                    <div class="slider-track">
                        <div class="slider-track-active"></div>
                        <div class="slider-handle" data-handle="0"></div>
                        ${this.options.rangeMode ? '<div class="slider-handle secondary" data-handle="1"></div>' : ''}
                    </div>
                </div>
                ${ticksHtml}
            `;
            
            this.container.innerHTML = sliderHtml;
            
            this.track = this.container.querySelector('.slider-track');
            this.trackActive = this.container.querySelector('.slider-track-active');
            this.handles = this.container.querySelectorAll('.slider-handle');
            this.valueDisplay = this.container.querySelector('.slider-value-display');
        }

        generateTicks() {
            const tickCount = Math.min(11, (this.options.max - this.options.min) / this.options.step + 1);
            const step = (this.options.max - this.options.min) / (tickCount - 1);
            
            let ticksHtml = '<div class="slider-ticks">';
            for (let i = 0; i < tickCount; i++) {
                const value = this.options.min + (step * i);
                ticksHtml += `<div class="slider-tick">${Math.round(value)}</div>`;
            }
            ticksHtml += '</div>';
            
            return ticksHtml;
        }

        bindEvents() {
            let activeHandle = null;
            let startX = 0;
            let startValue = 0;

            const handleMouseDown = (e) => {
                e.preventDefault();
                activeHandle = e.target;
                startX = e.clientX;
                startValue = this.getHandleValue(activeHandle);
                
                document.addEventListener('mousemove', handleMouseMove);
                document.addEventListener('mouseup', handleMouseUp);
                activeHandle.style.cursor = 'grabbing';
            };

            const handleMouseMove = (e) => {
                if (!activeHandle) return;
                
                const rect = this.track.getBoundingClientRect();
                const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                const value = this.options.min + (percent * (this.options.max - this.options.min));
                const steppedValue = Math.round(value / this.options.step) * this.options.step;
                
                this.setHandleValue(activeHandle, steppedValue);
                this.updateDisplay();
            };

            const handleMouseUp = () => {
                if (activeHandle) {
                    activeHandle.style.cursor = 'grab';
                    activeHandle = null;
                }
                document.removeEventListener('mousemove', handleMouseMove);
                document.removeEventListener('mouseup', handleMouseUp);
            };

            // Track click
            this.track.addEventListener('click', (e) => {
                if (e.target.classList.contains('slider-handle')) return;
                
                const rect = this.track.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                const value = this.options.min + (percent * (this.options.max - this.options.min));
                const steppedValue = Math.round(value / this.options.step) * this.options.step;
                
                if (this.options.rangeMode) {
                    // Find closest handle
                    const dist0 = Math.abs(this.value[0] - steppedValue);
                    const dist1 = Math.abs(this.value[1] - steppedValue);
                    const handle = dist0 < dist1 ? this.handles[0] : this.handles[1];
                    this.setHandleValue(handle, steppedValue);
                } else {
                    this.setHandleValue(this.handles[0], steppedValue);
                }
                
                this.updateDisplay();
            });

            // Handle mouse events
            this.handles.forEach(handle => {
                handle.addEventListener('mousedown', handleMouseDown);
            });
        }

        getHandleValue(handle) {
            const index = parseInt(handle.dataset.handle);
            return Array.isArray(this.value) ? this.value[index] : this.value;
        }

        setHandleValue(handle, value) {
            const index = parseInt(handle.dataset.handle);
            
            if (Array.isArray(this.value)) {
                this.value[index] = Math.max(this.options.min, Math.min(this.options.max, value));
                // Ensure proper order
                if (this.value[0] > this.value[1]) {
                    [this.value[0], this.value[1]] = [this.value[1], this.value[0]];
                }
            } else {
                this.value = Math.max(this.options.min, Math.min(this.options.max, value));
            }
        }

        updateDisplay() {
            if (Array.isArray(this.value)) {
                // Range mode
                const percent0 = (this.value[0] - this.options.min) / (this.options.max - this.options.min);
                const percent1 = (this.value[1] - this.options.min) / (this.options.max - this.options.min);
                
                this.handles[0].style.left = `${percent0 * 100}%`;
                this.handles[1].style.left = `${percent1 * 100}%`;
                
                this.trackActive.style.left = `${percent0 * 100}%`;
                this.trackActive.style.width = `${(percent1 - percent0) * 100}%`;
                
                this.valueDisplay.textContent = `${this.value[0]} - ${this.value[1]}`;
            } else {
                // Single value mode
                const percent = (this.value - this.options.min) / (this.options.max - this.options.min);
                
                this.handles[0].style.left = `${percent * 100}%`;
                this.trackActive.style.width = `${percent * 100}%`;
                
                this.valueDisplay.textContent = this.value;
            }
        }

        getValue() {
            return this.value;
        }

        setValue(value) {
            this.value = value;
            this.updateDisplay();
        }
    }

    // =============================================================================
    // TREE SELECT FIELD
    // =============================================================================

    class TreeSelectField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                data: [],
                multiple: false,
                searchable: true,
                lazyLoad: false,
                ...options
            };
            this.selectedItems = [];
            this.expandedNodes = new Set();
            this.filteredData = this.options.data;
            this.init();
        }

        init() {
            this.createTree();
            this.bindEvents();
            this.renderTree();
        }

        createTree() {
            const searchHtml = this.options.searchable ? `
                <div class="tree-select-header">
                    <input type="text" class="tree-search-input" placeholder="Search...">
                    <div class="tree-actions">
                        <button type="button" class="tree-action-btn" data-action="expand-all" title="Expand All">⊞</button>
                        <button type="button" class="tree-action-btn" data-action="collapse-all" title="Collapse All">⊟</button>
                        <button type="button" class="tree-action-btn" data-action="clear" title="Clear Selection">✖</button>
                    </div>
                </div>
            ` : '';
            
            const treeHtml = `
                ${searchHtml}
                <div class="tree-content">
                    <div class="tree-loading" style="display: none;">Loading...</div>
                </div>
            `;
            
            this.container.innerHTML = treeHtml;
            this.treeContent = this.container.querySelector('.tree-content');
            this.searchInput = this.container.querySelector('.tree-search-input');
        }

        bindEvents() {
            // Search functionality
            if (this.searchInput) {
                this.searchInput.addEventListener('input', Utils.debounce((e) => {
                    this.filterTree(e.target.value);
                }, 300));
            }

            // Action buttons
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('tree-action-btn')) {
                    const action = e.target.dataset.action;
                    this.handleAction(action);
                }
                
                if (e.target.classList.contains('tree-node-expander')) {
                    const nodeId = e.target.closest('.tree-node').dataset.nodeId;
                    this.toggleNode(nodeId);
                }
                
                if (e.target.classList.contains('tree-node-checkbox') || 
                    e.target.classList.contains('tree-node-content')) {
                    const nodeId = e.target.closest('.tree-node').dataset.nodeId;
                    this.selectNode(nodeId);
                }
            });
        }

        renderTree(data = this.filteredData, container = this.treeContent) {
            if (!data || data.length === 0) {
                container.innerHTML = '<div class="tree-loading">No items found</div>';
                return;
            }

            const treeHtml = data.map(node => this.renderNode(node)).join('');
            container.innerHTML = treeHtml;
        }

        renderNode(node) {
            const hasChildren = node.children && node.children.length > 0;
            const isExpanded = this.expandedNodes.has(node.id);
            const isSelected = this.selectedItems.includes(node.id);
            
            const expanderHtml = hasChildren ? 
                `<span class="tree-node-expander ${isExpanded ? 'expanded' : ''}">▶</span>` : 
                '<span class="tree-node-expander"></span>';
            
            const checkboxHtml = this.options.multiple ? 
                `<input type="checkbox" class="tree-node-checkbox" ${isSelected ? 'checked' : ''}>` : '';
            
            const iconHtml = node.icon ? 
                `<span class="tree-node-icon">${node.icon}</span>` : '';
            
            const badgeHtml = node.badge ? 
                `<span class="tree-node-badge">${node.badge}</span>` : '';
            
            const childrenHtml = hasChildren && isExpanded ? 
                `<div class="tree-children">
                    ${node.children.map(child => this.renderNode(child)).join('')}
                </div>` : '';
            
            return `
                <div class="tree-node" data-node-id="${node.id}">
                    <div class="tree-node-content ${isSelected ? 'selected' : ''}">
                        ${expanderHtml}
                        ${checkboxHtml}
                        ${iconHtml}
                        <span class="tree-node-label">${node.label}</span>
                        ${badgeHtml}
                    </div>
                    ${childrenHtml}
                </div>
            `;
        }

        toggleNode(nodeId) {
            if (this.expandedNodes.has(nodeId)) {
                this.expandedNodes.delete(nodeId);
            } else {
                this.expandedNodes.add(nodeId);
                
                // Lazy loading
                if (this.options.lazyLoad) {
                    this.loadNodeChildren(nodeId);
                }
            }
            
            this.renderTree();
        }

        selectNode(nodeId) {
            if (this.options.multiple) {
                const index = this.selectedItems.indexOf(nodeId);
                if (index > -1) {
                    this.selectedItems.splice(index, 1);
                } else {
                    this.selectedItems.push(nodeId);
                }
            } else {
                this.selectedItems = [nodeId];
            }
            
            this.renderTree();
            this.onSelectionChange();
        }

        filterTree(searchTerm) {
            if (!searchTerm) {
                this.filteredData = this.options.data;
            } else {
                this.filteredData = this.filterNodes(this.options.data, searchTerm.toLowerCase());
            }
            
            this.renderTree();
        }

        filterNodes(nodes, searchTerm) {
            return nodes.filter(node => {
                const matches = node.label.toLowerCase().includes(searchTerm);
                const hasMatchingChildren = node.children && 
                    this.filterNodes(node.children, searchTerm).length > 0;
                
                if (matches || hasMatchingChildren) {
                    return {
                        ...node,
                        children: hasMatchingChildren ? 
                            this.filterNodes(node.children, searchTerm) : node.children
                    };
                }
                
                return false;
            }).filter(Boolean);
        }

        handleAction(action) {
            switch (action) {
                case 'expand-all':
                    this.expandAll();
                    break;
                case 'collapse-all':
                    this.collapseAll();
                    break;
                case 'clear':
                    this.selectedItems = [];
                    this.renderTree();
                    this.onSelectionChange();
                    break;
            }
        }

        expandAll() {
            const getAllNodeIds = (nodes) => {
                let ids = [];
                nodes.forEach(node => {
                    if (node.children && node.children.length > 0) {
                        ids.push(node.id);
                        ids = ids.concat(getAllNodeIds(node.children));
                    }
                });
                return ids;
            };
            
            getAllNodeIds(this.options.data).forEach(id => {
                this.expandedNodes.add(id);
            });
            
            this.renderTree();
        }

        collapseAll() {
            this.expandedNodes.clear();
            this.renderTree();
        }

        loadNodeChildren(nodeId) {
            // Placeholder for lazy loading implementation
            // In real implementation, this would make an AJAX call
            console.log('Loading children for node:', nodeId);
        }

        onSelectionChange() {
            // Emit custom event
            const event = new CustomEvent('treeSelectionChange', {
                detail: { selectedItems: this.selectedItems }
            });
            this.container.dispatchEvent(event);
        }

        getSelectedItems() {
            return this.selectedItems;
        }

        setSelectedItems(items) {
            this.selectedItems = Array.isArray(items) ? items : [items];
            this.renderTree();
        }
    }

    // =============================================================================
    // CALENDAR FIELD
    // =============================================================================

    class CalendarField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                view: 'month',
                enableEvents: true,
                timeSlots: false,
                events: [],
                ...options
            };
            this.currentDate = new Date();
            this.selectedDate = null;
            this.events = this.options.events || [];
            this.init();
        }

        init() {
            this.createCalendar();
            this.bindEvents();
            this.render();
        }

        createCalendar() {
            const calendarHtml = `
                <div class="calendar-header">
                    <div class="calendar-navigation">
                        <button type="button" class="calendar-nav-btn" data-action="prev">‹</button>
                        <div class="calendar-title"></div>
                        <button type="button" class="calendar-nav-btn" data-action="next">›</button>
                    </div>
                    <div class="calendar-view-selector">
                        <button type="button" class="calendar-view-btn" data-view="month">Month</button>
                        <button type="button" class="calendar-view-btn" data-view="week">Week</button>
                        <button type="button" class="calendar-view-btn" data-view="day">Day</button>
                    </div>
                </div>
                <div class="calendar-grid"></div>
            `;
            
            this.container.innerHTML = calendarHtml;
            
            this.header = this.container.querySelector('.calendar-header');
            this.title = this.container.querySelector('.calendar-title');
            this.grid = this.container.querySelector('.calendar-grid');
            
            this.updateActiveView();
        }

        bindEvents() {
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('calendar-nav-btn')) {
                    const action = e.target.dataset.action;
                    this.navigate(action);
                }
                
                if (e.target.classList.contains('calendar-view-btn')) {
                    const view = e.target.dataset.view;
                    this.changeView(view);
                }
                
                if (e.target.classList.contains('calendar-day')) {
                    const date = new Date(e.target.dataset.date);
                    this.selectDate(date);
                }
            });
        }

        render() {
            this.updateTitle();
            
            switch (this.options.view) {
                case 'month':
                    this.renderMonth();
                    break;
                case 'week':
                    this.renderWeek();
                    break;
                case 'day':
                    this.renderDay();
                    break;
            }
        }

        renderMonth() {
            const year = this.currentDate.getFullYear();
            const month = this.currentDate.getMonth();
            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);
            const startDate = new Date(firstDay);
            startDate.setDate(startDate.getDate() - firstDay.getDay());
            
            const dayHeaders = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            
            let gridHtml = dayHeaders.map(day => 
                `<div class="calendar-day-header">${day}</div>`
            ).join('');
            
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            
            for (let i = 0; i < 42; i++) {
                const date = new Date(startDate);
                date.setDate(startDate.getDate() + i);
                
                const isToday = date.getTime() === today.getTime();
                const isCurrentMonth = date.getMonth() === month;
                const isSelected = this.selectedDate && 
                    date.getTime() === this.selectedDate.getTime();
                
                const dayEvents = this.getEventsForDate(date);
                const eventsHtml = dayEvents.map(event => 
                    `<div class="calendar-event ${event.type || ''}">${event.title}</div>`
                ).join('');
                
                const classes = [
                    'calendar-day',
                    isToday ? 'today' : '',
                    isCurrentMonth ? '' : 'other-month',
                    isSelected ? 'selected' : ''
                ].filter(Boolean).join(' ');
                
                gridHtml += `
                    <div class="${classes}" data-date="${date.toISOString().split('T')[0]}">
                        <div class="calendar-day-number">${date.getDate()}</div>
                        <div class="calendar-events">${eventsHtml}</div>
                    </div>
                `;
            }
            
            this.grid.innerHTML = gridHtml;
        }

        renderWeek() {
            // Week view implementation
            this.grid.innerHTML = '<div>Week view coming soon...</div>';
        }

        renderDay() {
            // Day view implementation
            this.grid.innerHTML = '<div>Day view coming soon...</div>';
        }

        updateTitle() {
            const options = { year: 'numeric', month: 'long' };
            this.title.textContent = this.currentDate.toLocaleDateString('en-US', options);
        }

        updateActiveView() {
            const buttons = this.container.querySelectorAll('.calendar-view-btn');
            buttons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.view === this.options.view);
            });
        }

        navigate(direction) {
            switch (this.options.view) {
                case 'month':
                    const month = direction === 'next' ? 1 : -1;
                    this.currentDate.setMonth(this.currentDate.getMonth() + month);
                    break;
                case 'week':
                    const week = direction === 'next' ? 7 : -7;
                    this.currentDate.setDate(this.currentDate.getDate() + week);
                    break;
                case 'day':
                    const day = direction === 'next' ? 1 : -1;
                    this.currentDate.setDate(this.currentDate.getDate() + day);
                    break;
            }
            
            this.render();
        }

        changeView(view) {
            this.options.view = view;
            this.updateActiveView();
            this.render();
        }

        selectDate(date) {
            this.selectedDate = date;
            this.render();
            
            // Emit event
            const event = new CustomEvent('dateSelect', {
                detail: { date: date }
            });
            this.container.dispatchEvent(event);
        }

        getEventsForDate(date) {
            const dateStr = date.toISOString().split('T')[0];
            return this.events.filter(event => {
                const eventDate = new Date(event.date).toISOString().split('T')[0];
                return eventDate === dateStr;
            });
        }

        addEvent(event) {
            this.events.push(event);
            this.render();
        }

        removeEvent(eventId) {
            this.events = this.events.filter(event => event.id !== eventId);
            this.render();
        }

        getEvents() {
            return this.events;
        }
    }

    // =============================================================================
    // SWITCH FIELD
    // =============================================================================

    class SwitchField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                type: 'default',
                size: 'medium',
                checked: false,
                disabled: false,
                ...options
            };
            this.checked = this.options.checked;
            this.init();
        }

        init() {
            this.createSwitch();
            this.bindEvents();
        }

        createSwitch() {
            const switchHtml = `
                <div class="switch-wrapper">
                    <div class="switch-container">
                        <input type="checkbox" class="switch-input" 
                               ${this.checked ? 'checked' : ''} 
                               ${this.options.disabled ? 'disabled' : ''}>
                        <label class="switch-track ${this.options.type} ${this.options.size} ${this.checked ? 'checked' : ''}">
                            <span class="switch-thumb"></span>
                        </label>
                    </div>
                    <label class="switch-label">${this.options.label || ''}</label>
                </div>
                ${this.options.description ? `<div class="switch-description">${this.options.description}</div>` : ''}
            `;
            
            this.container.innerHTML = switchHtml;
            
            this.input = this.container.querySelector('.switch-input');
            this.track = this.container.querySelector('.switch-track');
            this.label = this.container.querySelector('.switch-label');
        }

        bindEvents() {
            this.input.addEventListener('change', (e) => {
                this.checked = e.target.checked;
                this.updateAppearance();
                this.onChange();
            });
            
            this.label.addEventListener('click', () => {
                if (!this.options.disabled) {
                    this.toggle();
                }
            });
        }

        updateAppearance() {
            this.track.classList.toggle('checked', this.checked);
            this.input.checked = this.checked;
        }

        toggle() {
            if (!this.options.disabled) {
                this.checked = !this.checked;
                this.updateAppearance();
                this.onChange();
            }
        }

        setChecked(checked) {
            this.checked = checked;
            this.updateAppearance();
        }

        setDisabled(disabled) {
            this.options.disabled = disabled;
            this.input.disabled = disabled;
        }

        onChange() {
            // Emit custom event
            const event = new CustomEvent('switchChange', {
                detail: { checked: this.checked }
            });
            this.container.dispatchEvent(event);
        }

        getValue() {
            return this.checked;
        }

        setValue(value) {
            this.setChecked(!!value);
        }
    }

    // =============================================================================
    // MARKDOWN FIELD
    // =============================================================================

    class MarkdownField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                enablePreview: true,
                toolbar: 'full',
                height: 400,
                ...options
            };
            this.content = '';
            this.init();
        }

        init() {
            this.loadMarkdownLibrary(() => {
                this.createEditor();
                this.bindEvents();
                this.updatePreview();
            });
        }

        loadMarkdownLibrary(callback) {
            if (window.marked) {
                callback();
                return;
            }
            
            Utils.loadScript('https://cdn.jsdelivr.net/npm/marked/marked.min.js', callback);
        }

        createEditor() {
            const toolbarHtml = this.createToolbar();
            const previewHtml = this.options.enablePreview ? 
                '<div class="markdown-preview-pane"><div class="markdown-preview"></div></div>' : '';
            
            const editorHtml = `
                ${toolbarHtml}
                <div class="markdown-content">
                    <div class="markdown-editor-pane">
                        <textarea class="markdown-editor" 
                                  style="height: ${this.options.height}px;"
                                  placeholder="Enter markdown here..."></textarea>
                    </div>
                    ${previewHtml}
                </div>
            `;
            
            this.container.innerHTML = editorHtml;
            
            this.editor = this.container.querySelector('.markdown-editor');
            this.preview = this.container.querySelector('.markdown-preview');
        }

        createToolbar() {
            if (this.options.toolbar === 'none') return '';
            
            const buttons = [
                { group: 'format', icon: 'B', action: 'bold', title: 'Bold' },
                { group: 'format', icon: 'I', action: 'italic', title: 'Italic' },
                { group: 'format', icon: 'S', action: 'strikethrough', title: 'Strikethrough' },
                { group: 'format', icon: '`', action: 'code', title: 'Inline Code' },
                
                { group: 'headers', icon: 'H1', action: 'h1', title: 'Heading 1' },
                { group: 'headers', icon: 'H2', action: 'h2', title: 'Heading 2' },
                { group: 'headers', icon: 'H3', action: 'h3', title: 'Heading 3' },
                
                { group: 'lists', icon: '•', action: 'ul', title: 'Unordered List' },
                { group: 'lists', icon: '1.', action: 'ol', title: 'Ordered List' },
                { group: 'lists', icon: '☑', action: 'task', title: 'Task List' },
                
                { group: 'insert', icon: '🔗', action: 'link', title: 'Link' },
                { group: 'insert', icon: '🖼', action: 'image', title: 'Image' },
                { group: 'insert', icon: '📋', action: 'table', title: 'Table' },
                { group: 'insert', icon: '💬', action: 'quote', title: 'Quote' }
            ];
            
            if (this.options.toolbar === 'minimal') {
                buttons = buttons.filter(btn => 
                    ['bold', 'italic', 'code', 'h1', 'h2', 'ul', 'ol', 'link'].includes(btn.action)
                );
            }
            
            const groups = {};
            buttons.forEach(btn => {
                if (!groups[btn.group]) groups[btn.group] = [];
                groups[btn.group].push(btn);
            });
            
            const groupsHtml = Object.values(groups).map(group => 
                `<div class="markdown-toolbar-group">
                    ${group.map(btn => 
                        `<button type="button" class="markdown-toolbar-btn" 
                                 data-action="${btn.action}" 
                                 title="${btn.title}">${btn.icon}</button>`
                    ).join('')}
                </div>`
            ).join('');
            
            return `<div class="markdown-toolbar">${groupsHtml}</div>`;
        }

        bindEvents() {
            // Toolbar actions
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('markdown-toolbar-btn')) {
                    const action = e.target.dataset.action;
                    this.executeAction(action);
                }
            });

            // Editor input
            this.editor.addEventListener('input', Utils.debounce(() => {
                this.content = this.editor.value;
                this.updatePreview();
            }, 300));

            // Tab handling
            this.editor.addEventListener('keydown', (e) => {
                if (e.key === 'Tab') {
                    e.preventDefault();
                    this.insertText('    ');
                }
            });
        }

        executeAction(action) {
            const selection = this.getSelection();
            
            switch (action) {
                case 'bold':
                    this.wrapSelection('**', '**');
                    break;
                case 'italic':
                    this.wrapSelection('*', '*');
                    break;
                case 'strikethrough':
                    this.wrapSelection('~~', '~~');
                    break;
                case 'code':
                    this.wrapSelection('`', '`');
                    break;
                case 'h1':
                    this.insertLinePrefix('# ');
                    break;
                case 'h2':
                    this.insertLinePrefix('## ');
                    break;
                case 'h3':
                    this.insertLinePrefix('### ');
                    break;
                case 'ul':
                    this.insertLinePrefix('- ');
                    break;
                case 'ol':
                    this.insertLinePrefix('1. ');
                    break;
                case 'task':
                    this.insertLinePrefix('- [ ] ');
                    break;
                case 'quote':
                    this.insertLinePrefix('> ');
                    break;
                case 'link':
                    this.insertText('[Link Text](url)');
                    break;
                case 'image':
                    this.insertText('![Alt Text](image-url)');
                    break;
                case 'table':
                    this.insertTable();
                    break;
            }
            
            this.editor.focus();
        }

        getSelection() {
            return {
                start: this.editor.selectionStart,
                end: this.editor.selectionEnd,
                text: this.editor.value.substring(this.editor.selectionStart, this.editor.selectionEnd)
            };
        }

        wrapSelection(before, after) {
            const selection = this.getSelection();
            const newText = before + selection.text + after;
            this.replaceSelection(newText);
        }

        insertLinePrefix(prefix) {
            const selection = this.getSelection();
            const lines = this.editor.value.split('\n');
            const startLine = this.editor.value.substring(0, selection.start).split('\n').length - 1;
            
            lines[startLine] = prefix + lines[startLine];
            this.editor.value = lines.join('\n');
            this.content = this.editor.value;
            this.updatePreview();
        }

        insertText(text) {
            const selection = this.getSelection();
            this.replaceSelection(text);
        }

        replaceSelection(text) {
            const selection = this.getSelection();
            const before = this.editor.value.substring(0, selection.start);
            const after = this.editor.value.substring(selection.end);
            
            this.editor.value = before + text + after;
            this.editor.selectionStart = selection.start + text.length;
            this.editor.selectionEnd = selection.start + text.length;
            
            this.content = this.editor.value;
            this.updatePreview();
        }

        insertTable() {
            const table = `
| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |
`;
            this.insertText(table.trim());
        }

        updatePreview() {
            if (!this.preview || !window.marked) return;
            
            try {
                const html = marked.parse(this.content);
                this.preview.innerHTML = html;
            } catch (error) {
                console.error('Markdown parsing error:', error);
                this.preview.innerHTML = '<p>Error parsing markdown</p>';
            }
        }

        getValue() {
            return this.content;
        }

        setValue(value) {
            this.content = value;
            this.editor.value = value;
            this.updatePreview();
        }
    }

    // =============================================================================
    // MEDIA PLAYER FIELD
    // =============================================================================

    class MediaPlayerField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                type: 'audio',
                enablePlaylist: true,
                playlist: [],
                ...options
            };
            this.currentTrack = 0;
            this.isPlaying = false;
            this.volume = 1.0;
            this.currentTime = 0;
            this.duration = 0;
            this.init();
        }

        init() {
            this.createPlayer();
            this.bindEvents();
            this.loadTrack();
        }

        createPlayer() {
            const playlistHtml = this.options.enablePlaylist ? this.createPlaylist() : '';
            
            const playerHtml = `
                <div class="media-player-header">
                    <h3 class="media-player-title">Media Player</h3>
                    <div class="media-player-controls-top">
                        <button type="button" class="media-control-btn" data-action="prev">⏮</button>
                        <button type="button" class="media-control-btn" data-action="next">⏭</button>
                        <button type="button" class="media-control-btn" data-action="shuffle">🔀</button>
                        <button type="button" class="media-control-btn" data-action="repeat">🔁</button>
                    </div>
                </div>
                <div class="media-player-content">
                    <div class="media-player-main">
                        ${this.options.type === 'video' ? 
                            '<video class="media-element" controls></video>' : 
                            '<audio class="media-element" controls></audio>'
                        }
                        <div class="media-player-overlay">
                            <div class="media-player-controls">
                                <button type="button" class="media-play-btn">▶</button>
                                <div class="media-progress-container">
                                    <div class="media-progress-track">
                                        <div class="media-progress-fill"></div>
                                    </div>
                                    <div class="media-time-display">0:00 / 0:00</div>
                                </div>
                            </div>
                            <div class="media-volume-controls">
                                <button type="button" class="media-volume-btn">🔊</button>
                                <div class="media-volume-slider">
                                    <div class="media-volume-fill"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    ${playlistHtml}
                </div>
            `;
            
            this.container.innerHTML = playerHtml;
            
            this.mediaElement = this.container.querySelector('.media-element');
            this.playButton = this.container.querySelector('.media-play-btn');
            this.progressTrack = this.container.querySelector('.media-progress-track');
            this.progressFill = this.container.querySelector('.media-progress-fill');
            this.timeDisplay = this.container.querySelector('.media-time-display');
            this.volumeSlider = this.container.querySelector('.media-volume-slider');
            this.volumeFill = this.container.querySelector('.media-volume-fill');
            this.volumeButton = this.container.querySelector('.media-volume-btn');
        }

        createPlaylist() {
            const playlistItems = this.options.playlist.map((track, index) => `
                <div class="media-playlist-item ${index === this.currentTrack ? 'active' : ''}" 
                     data-track="${index}">
                    <div class="media-playlist-thumb">
                        ${this.options.type === 'video' ? '🎬' : '🎵'}
                    </div>
                    <div class="media-playlist-info">
                        <div class="media-playlist-title">${track.title || 'Unknown Title'}</div>
                        <div class="media-playlist-duration">${track.duration || '0:00'}</div>
                    </div>
                </div>
            `).join('');
            
            return `
                <div class="media-playlist">
                    <div class="media-playlist-header">Playlist (${this.options.playlist.length})</div>
                    ${playlistItems}
                </div>
            `;
        }

        bindEvents() {
            // Play/pause button
            this.playButton.addEventListener('click', () => {
                this.togglePlay();
            });

            // Media element events
            this.mediaElement.addEventListener('loadedmetadata', () => {
                this.duration = this.mediaElement.duration;
                this.updateTimeDisplay();
            });

            this.mediaElement.addEventListener('timeupdate', () => {
                this.currentTime = this.mediaElement.currentTime;
                this.updateProgress();
                this.updateTimeDisplay();
            });

            this.mediaElement.addEventListener('ended', () => {
                this.next();
            });

            // Progress track click
            this.progressTrack.addEventListener('click', (e) => {
                const rect = this.progressTrack.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                this.mediaElement.currentTime = percent * this.duration;
            });

            // Volume controls
            this.volumeSlider.addEventListener('click', (e) => {
                const rect = this.volumeSlider.getBoundingClientRect();
                const percent = (e.clientX - rect.left) / rect.width;
                this.setVolume(percent);
            });

            this.volumeButton.addEventListener('click', () => {
                this.toggleMute();
            });

            // Control buttons
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('media-control-btn')) {
                    const action = e.target.dataset.action;
                    this.handleControlAction(action);
                }
                
                if (e.target.closest('.media-playlist-item')) {
                    const trackIndex = parseInt(e.target.closest('.media-playlist-item').dataset.track);
                    this.selectTrack(trackIndex);
                }
            });

            // Keyboard shortcuts
            this.container.addEventListener('keydown', (e) => {
                switch (e.key) {
                    case ' ':
                        e.preventDefault();
                        this.togglePlay();
                        break;
                    case 'ArrowLeft':
                        this.mediaElement.currentTime -= 10;
                        break;
                    case 'ArrowRight':
                        this.mediaElement.currentTime += 10;
                        break;
                    case 'ArrowUp':
                        this.setVolume(Math.min(1, this.volume + 0.1));
                        break;
                    case 'ArrowDown':
                        this.setVolume(Math.max(0, this.volume - 0.1));
                        break;
                }
            });
        }

        loadTrack() {
            if (this.options.playlist.length === 0) return;
            
            const track = this.options.playlist[this.currentTrack];
            if (track && track.src) {
                this.mediaElement.src = track.src;
                this.mediaElement.load();
                this.updatePlaylistSelection();
            }
        }

        togglePlay() {
            if (this.isPlaying) {
                this.mediaElement.pause();
                this.playButton.textContent = '▶';
                this.isPlaying = false;
            } else {
                this.mediaElement.play();
                this.playButton.textContent = '⏸';
                this.isPlaying = true;
            }
        }

        setVolume(volume) {
            this.volume = Math.max(0, Math.min(1, volume));
            this.mediaElement.volume = this.volume;
            this.updateVolumeDisplay();
        }

        toggleMute() {
            if (this.mediaElement.muted) {
                this.mediaElement.muted = false;
                this.volumeButton.textContent = '🔊';
            } else {
                this.mediaElement.muted = true;
                this.volumeButton.textContent = '🔇';
            }
        }

        handleControlAction(action) {
            switch (action) {
                case 'prev':
                    this.previous();
                    break;
                case 'next':
                    this.next();
                    break;
                case 'shuffle':
                    this.shuffle();
                    break;
                case 'repeat':
                    this.toggleRepeat();
                    break;
            }
        }

        previous() {
            if (this.currentTrack > 0) {
                this.currentTrack--;
                this.loadTrack();
            }
        }

        next() {
            if (this.currentTrack < this.options.playlist.length - 1) {
                this.currentTrack++;
                this.loadTrack();
            }
        }

        selectTrack(index) {
            this.currentTrack = index;
            this.loadTrack();
        }

        shuffle() {
            // Implement shuffle functionality
            console.log('Shuffle functionality');
        }

        toggleRepeat() {
            // Implement repeat functionality
            console.log('Repeat functionality');
        }

        updateProgress() {
            if (this.duration > 0) {
                const percent = (this.currentTime / this.duration) * 100;
                this.progressFill.style.width = `${percent}%`;
            }
        }

        updateTimeDisplay() {
            const currentFormatted = Utils.formatDuration(this.currentTime);
            const durationFormatted = Utils.formatDuration(this.duration);
            this.timeDisplay.textContent = `${currentFormatted} / ${durationFormatted}`;
        }

        updateVolumeDisplay() {
            const percent = this.volume * 100;
            this.volumeFill.style.width = `${percent}%`;
        }

        updatePlaylistSelection() {
            const items = this.container.querySelectorAll('.media-playlist-item');
            items.forEach((item, index) => {
                item.classList.toggle('active', index === this.currentTrack);
            });
        }

        addToPlaylist(track) {
            this.options.playlist.push(track);
            // Re-render playlist
            const playlist = this.container.querySelector('.media-playlist');
            if (playlist) {
                playlist.innerHTML = this.createPlaylist();
            }
        }

        removeFromPlaylist(index) {
            this.options.playlist.splice(index, 1);
            if (this.currentTrack >= index && this.currentTrack > 0) {
                this.currentTrack--;
            }
            // Re-render playlist
            const playlist = this.container.querySelector('.media-playlist');
            if (playlist) {
                playlist.innerHTML = this.createPlaylist();
            }
        }
    }

    // =============================================================================
    // BADGE FIELD
    // =============================================================================

    class BadgeField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                style: 'primary',
                maxItems: null,
                suggestions: [],
                allowCustom: true,
                ...options
            };
            this.items = [];
            this.suggestions = this.options.suggestions || [];
            this.init();
        }

        init() {
            this.createBadgeField();
            this.bindEvents();
        }

        createBadgeField() {
            const badgeFieldHtml = `
                <div class="badge-input-container">
                    <input type="text" class="badge-input" placeholder="Type and press Enter to add...">
                    <div class="badge-suggestions" style="display: none;"></div>
                </div>
                <div class="badge-collection"></div>
                <div class="badge-counter">0 / ${this.options.maxItems || '∞'} items</div>
            `;
            
            this.container.innerHTML = badgeFieldHtml;
            
            this.input = this.container.querySelector('.badge-input');
            this.suggestionsContainer = this.container.querySelector('.badge-suggestions');
            this.collection = this.container.querySelector('.badge-collection');
            this.counter = this.container.querySelector('.badge-counter');
        }

        bindEvents() {
            // Input events
            this.input.addEventListener('input', Utils.debounce((e) => {
                this.updateSuggestions(e.target.value);
            }, 200));

            this.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const value = this.input.value.trim();
                    if (value) {
                        this.addItem(value);
                        this.input.value = '';
                        this.hideSuggestions();
                    }
                }
                
                if (e.key === 'Escape') {
                    this.hideSuggestions();
                }
                
                if (e.key === 'Backspace' && this.input.value === '' && this.items.length > 0) {
                    this.removeItem(this.items.length - 1);
                }
            });

            this.input.addEventListener('focus', () => {
                if (this.input.value) {
                    this.updateSuggestions(this.input.value);
                }
            });

            this.input.addEventListener('blur', () => {
                // Delay hiding to allow clicks on suggestions
                setTimeout(() => this.hideSuggestions(), 200);
            });

            // Collection events
            this.collection.addEventListener('click', (e) => {
                if (e.target.classList.contains('badge-remove')) {
                    const badge = e.target.closest('.badge-item');
                    const index = Array.from(this.collection.children).indexOf(badge);
                    this.removeItem(index);
                }
            });

            // Suggestions events
            this.suggestionsContainer.addEventListener('click', (e) => {
                if (e.target.classList.contains('badge-suggestion')) {
                    const value = e.target.textContent.trim();
                    this.addItem(value);
                    this.input.value = '';
                    this.hideSuggestions();
                    this.input.focus();
                }
            });
        }

        addItem(value) {
            // Check if item already exists
            if (this.items.includes(value)) {
                return;
            }
            
            // Check max items limit
            if (this.options.maxItems && this.items.length >= this.options.maxItems) {
                return;
            }
            
            this.items.push(value);
            this.renderItems();
            this.updateCounter();
            this.onChange();
        }

        removeItem(index) {
            if (index >= 0 && index < this.items.length) {
                this.items.splice(index, 1);
                this.renderItems();
                this.updateCounter();
                this.onChange();
            }
        }

        renderItems() {
            const itemsHtml = this.items.map(item => this.createBadgeItem(item)).join('');
            this.collection.innerHTML = itemsHtml;
        }

        createBadgeItem(item) {
            return `
                <div class="badge-item ${this.options.style}">
                    <span class="badge-text">${this.escapeHtml(item)}</span>
                    <button type="button" class="badge-remove">×</button>
                </div>
            `;
        }

        updateSuggestions(query) {
            if (!query || query.length < 1) {
                this.hideSuggestions();
                return;
            }
            
            const filtered = this.suggestions.filter(suggestion => 
                suggestion.toLowerCase().includes(query.toLowerCase()) &&
                !this.items.includes(suggestion)
            );
            
            if (filtered.length === 0) {
                this.hideSuggestions();
                return;
            }
            
            const suggestionsHtml = filtered.slice(0, 5).map(suggestion => 
                `<div class="badge-suggestion">${this.escapeHtml(suggestion)}</div>`
            ).join('');
            
            this.suggestionsContainer.innerHTML = suggestionsHtml;
            this.suggestionsContainer.style.display = 'block';
        }

        hideSuggestions() {
            this.suggestionsContainer.style.display = 'none';
        }

        updateCounter() {
            const max = this.options.maxItems || '∞';
            this.counter.textContent = `${this.items.length} / ${max} items`;
        }

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        onChange() {
            // Emit custom event
            const event = new CustomEvent('badgeChange', {
                detail: { items: this.items }
            });
            this.container.dispatchEvent(event);
        }

        getValue() {
            return this.items;
        }

        setValue(items) {
            this.items = Array.isArray(items) ? [...items] : [];
            this.renderItems();
            this.updateCounter();
        }

        setSuggestions(suggestions) {
            this.suggestions = suggestions;
        }

        clear() {
            this.items = [];
            this.renderItems();
            this.updateCounter();
            this.onChange();
        }
    }

    // =============================================================================
    // DUAL LIST BOX FIELD
    // =============================================================================

    class DualListBoxField {
        constructor(container, options = {}) {
            this.container = container;
            this.options = {
                height: 300,
                searchable: true,
                showMoveAll: true,
                availableItems: [],
                selectedItems: [],
                ...options
            };
            this.availableItems = [...this.options.availableItems];
            this.selectedItems = [...this.options.selectedItems];
            this.filteredAvailable = [...this.availableItems];
            this.filteredSelected = [...this.selectedItems];
            this.init();
        }

        init() {
            this.createDualListBox();
            this.bindEvents();
            this.render();
        }

        createDualListBox() {
            const searchHtml = this.options.searchable ? `
                <div class="dual-list-search">
                    <input type="text" class="dual-list-search-input" 
                           placeholder="Search available..." data-panel="available">
                    <input type="text" class="dual-list-search-input" 
                           placeholder="Search selected..." data-panel="selected">
                </div>
            ` : '';
            
            const moveAllButtons = this.options.showMoveAll ? `
                <button type="button" class="dual-list-move-btn dual-list-move-all" 
                        data-action="move-all-right">≫</button>
                <button type="button" class="dual-list-move-btn dual-list-move-all" 
                        data-action="move-all-left">≪</button>
            ` : '';
            
            const dualListHtml = `
                <div class="dual-list-header">
                    <h3 class="dual-list-title">Select Items</h3>
                    ${searchHtml}
                </div>
                <div class="dual-list-content" style="height: ${this.options.height}px;">
                    <div class="dual-list-panel">
                        <div class="dual-list-panel-header">
                            Available Items
                            <span class="dual-list-panel-counter">0</span>
                        </div>
                        <div class="dual-list-items" data-panel="available"></div>
                    </div>
                    <div class="dual-list-controls">
                        <button type="button" class="dual-list-move-btn" data-action="move-right">›</button>
                        ${moveAllButtons}
                        <button type="button" class="dual-list-move-btn" data-action="move-left">‹</button>
                    </div>
                    <div class="dual-list-panel">
                        <div class="dual-list-panel-header">
                            Selected Items
                            <span class="dual-list-panel-counter">0</span>
                        </div>
                        <div class="dual-list-items" data-panel="selected"></div>
                    </div>
                </div>
            `;
            
            this.container.innerHTML = dualListHtml;
            
            this.availablePanel = this.container.querySelector('[data-panel="available"]');
            this.selectedPanel = this.container.querySelector('[data-panel="selected"]');
            this.availableCounter = this.availablePanel.parentElement.querySelector('.dual-list-panel-counter');
            this.selectedCounter = this.selectedPanel.parentElement.querySelector('.dual-list-panel-counter');
            this.searchInputs = this.container.querySelectorAll('.dual-list-search-input');
        }

        bindEvents() {
            // Search functionality
            this.searchInputs.forEach(input => {
                input.addEventListener('input', Utils.debounce((e) => {
                    const panel = e.target.dataset.panel;
                    this.filterItems(panel, e.target.value);
                }, 300));
            });

            // Move buttons
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('dual-list-move-btn')) {
                    const action = e.target.dataset.action;
                    this.handleMoveAction(action);
                }
            });

            // Item selection
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('dual-list-item')) {
                    this.toggleItemSelection(e.target);
                }
            });

            // Double-click to move
            this.container.addEventListener('dblclick', (e) => {
                if (e.target.classList.contains('dual-list-item')) {
                    const panel = e.target.closest('[data-panel]').dataset.panel;
                    const value = e.target.dataset.value;
                    
                    if (panel === 'available') {
                        this.moveToSelected([value]);
                    } else {
                        this.moveToAvailable([value]);
                    }
                }
            });

            // Keyboard shortcuts
            this.container.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const selectedItems = this.getSelectedInPanel('available');
                    if (selectedItems.length > 0) {
                        this.moveToSelected(selectedItems);
                    }
                }
                
                if (e.key === 'Backspace' || e.key === 'Delete') {
                    const selectedItems = this.getSelectedInPanel('selected');
                    if (selectedItems.length > 0) {
                        this.moveToAvailable(selectedItems);
                    }
                }
            });
        }

        render() {
            this.renderPanel('available');
            this.renderPanel('selected');
            this.updateCounters();
            this.updateButtonStates();
        }

        renderPanel(panelType) {
            const panel = panelType === 'available' ? this.availablePanel : this.selectedPanel;
            const items = panelType === 'available' ? this.filteredAvailable : this.filteredSelected;
            
            const itemsHtml = items.map(item => this.createListItem(item, panelType)).join('');
            panel.innerHTML = itemsHtml;
        }

        createListItem(item, panelType) {
            const value = typeof item === 'object' ? item.value : item;
            const label = typeof item === 'object' ? item.label || item.value : item;
            
            return `
                <div class="dual-list-item" data-value="${this.escapeHtml(value)}">
                    <input type="checkbox" class="dual-list-item-checkbox">
                    <span class="dual-list-item-text">${this.escapeHtml(label)}</span>
                </div>
            `;
        }

        filterItems(panelType, searchTerm) {
            const items = panelType === 'available' ? this.availableItems : this.selectedItems;
            
            if (!searchTerm) {
                if (panelType === 'available') {
                    this.filteredAvailable = [...this.availableItems];
                } else {
                    this.filteredSelected = [...this.selectedItems];
                }
            } else {
                const filtered = items.filter(item => {
                    const label = typeof item === 'object' ? item.label || item.value : item;
                    return label.toLowerCase().includes(searchTerm.toLowerCase());
                });
                
                if (panelType === 'available') {
                    this.filteredAvailable = filtered;
                } else {
                    this.filteredSelected = filtered;
                }
            }
            
            this.renderPanel(panelType);
        }

        toggleItemSelection(itemElement) {
            const checkbox = itemElement.querySelector('.dual-list-item-checkbox');
            checkbox.checked = !checkbox.checked;
            itemElement.classList.toggle('selected', checkbox.checked);
            this.updateButtonStates();
        }

        getSelectedInPanel(panelType) {
            const panel = panelType === 'available' ? this.availablePanel : this.selectedPanel;
            const selectedItems = panel.querySelectorAll('.dual-list-item.selected');
            return Array.from(selectedItems).map(item => item.dataset.value);
        }

        handleMoveAction(action) {
            switch (action) {
                case 'move-right':
                    const selectedAvailable = this.getSelectedInPanel('available');
                    this.moveToSelected(selectedAvailable);
                    break;
                case 'move-left':
                    const selectedSelected = this.getSelectedInPanel('selected');
                    this.moveToAvailable(selectedSelected);
                    break;
                case 'move-all-right':
                    const allAvailable = this.availableItems.map(item => 
                        typeof item === 'object' ? item.value : item
                    );
                    this.moveToSelected(allAvailable);
                    break;
                case 'move-all-left':
                    const allSelected = this.selectedItems.map(item => 
                        typeof item === 'object' ? item.value : item
                    );
                    this.moveToAvailable(allSelected);
                    break;
            }
        }

        moveToSelected(values) {
            values.forEach(value => {
                const index = this.availableItems.findIndex(item => 
                    (typeof item === 'object' ? item.value : item) === value
                );
                
                if (index > -1) {
                    const item = this.availableItems.splice(index, 1)[0];
                    this.selectedItems.push(item);
                }
            });
            
            this.updateFilteredLists();
            this.render();
            this.onChange();
        }

        moveToAvailable(values) {
            values.forEach(value => {
                const index = this.selectedItems.findIndex(item => 
                    (typeof item === 'object' ? item.value : item) === value
                );
                
                if (index > -1) {
                    const item = this.selectedItems.splice(index, 1)[0];
                    this.availableItems.push(item);
                }
            });
            
            this.updateFilteredLists();
            this.render();
            this.onChange();
        }

        updateFilteredLists() {
            this.filteredAvailable = [...this.availableItems];
            this.filteredSelected = [...this.selectedItems];
        }

        updateCounters() {
            this.availableCounter.textContent = this.filteredAvailable.length;
            this.selectedCounter.textContent = this.filteredSelected.length;
        }

        updateButtonStates() {
            const hasSelectedAvailable = this.getSelectedInPanel('available').length > 0;
            const hasSelectedSelected = this.getSelectedInPanel('selected').length > 0;
            const hasAvailable = this.availableItems.length > 0;
            const hasSelected = this.selectedItems.length > 0;
            
            const buttons = this.container.querySelectorAll('.dual-list-move-btn');
            buttons.forEach(btn => {
                const action = btn.dataset.action;
                let disabled = false;
                
                switch (action) {
                    case 'move-right':
                        disabled = !hasSelectedAvailable;
                        break;
                    case 'move-left':
                        disabled = !hasSelectedSelected;
                        break;
                    case 'move-all-right':
                        disabled = !hasAvailable;
                        break;
                    case 'move-all-left':
                        disabled = !hasSelected;
                        break;
                }
                
                btn.disabled = disabled;
            });
        }

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        onChange() {
            // Emit custom event
            const event = new CustomEvent('dualListChange', {
                detail: {
                    available: this.availableItems,
                    selected: this.selectedItems
                }
            });
            this.container.dispatchEvent(event);
        }

        getValue() {
            return this.selectedItems;
        }

        setValue(selected) {
            // Reset items
            const allItems = [...this.options.availableItems, ...this.options.selectedItems];
            this.availableItems = [];
            this.selectedItems = [];
            
            allItems.forEach(item => {
                const value = typeof item === 'object' ? item.value : item;
                if (selected.includes(value)) {
                    this.selectedItems.push(item);
                } else {
                    this.availableItems.push(item);
                }
            });
            
            this.updateFilteredLists();
            this.render();
        }

        setAvailableItems(items) {
            this.options.availableItems = items;
            this.availableItems = [...items];
            this.updateFilteredLists();
            this.render();
        }
    }

    // =============================================================================
    // PUBLIC API
    // =============================================================================

    // Register field classes
    AdvancedFields.ChartField = ChartField;
    AdvancedFields.MapField = MapField;
    AdvancedFields.CropperField = CropperField;
    AdvancedFields.SliderField = SliderField;
    AdvancedFields.TreeSelectField = TreeSelectField;
    AdvancedFields.CalendarField = CalendarField;
    AdvancedFields.SwitchField = SwitchField;
    AdvancedFields.MarkdownField = MarkdownField;
    AdvancedFields.MediaPlayerField = MediaPlayerField;
    AdvancedFields.BadgeField = BadgeField;
    AdvancedFields.DualListBoxField = DualListBoxField;

    // Auto-initialization
    document.addEventListener('DOMContentLoaded', function() {
        // Auto-initialize fields based on CSS classes
        const fieldMappings = [
            { className: 'chart-field-container', FieldClass: ChartField },
            { className: 'map-field-container', FieldClass: MapField },
            { className: 'cropper-field-container', FieldClass: CropperField },
            { className: 'slider-field-container', FieldClass: SliderField },
            { className: 'tree-select-container', FieldClass: TreeSelectField },
            { className: 'calendar-field-container', FieldClass: CalendarField },
            { className: 'switch-field-container', FieldClass: SwitchField },
            { className: 'markdown-field-container', FieldClass: MarkdownField },
            { className: 'media-player-container', FieldClass: MediaPlayerField },
            { className: 'badge-field-container', FieldClass: BadgeField },
            { className: 'dual-list-container', FieldClass: DualListBoxField }
        ];

        fieldMappings.forEach(({ className, FieldClass }) => {
            const containers = document.querySelectorAll(`.${className}`);
            containers.forEach(container => {
                if (!container.dataset.initialized) {
                    const options = container.dataset.options ? 
                        JSON.parse(container.dataset.options) : {};
                    new FieldClass(container, options);
                    container.dataset.initialized = 'true';
                }
            });
        });
    });

    // Utility functions for external use
    AdvancedFields.Utils = Utils;

})(window, document, typeof jQuery !== 'undefined' ? jQuery : null);