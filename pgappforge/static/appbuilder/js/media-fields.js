/**
 * Flask-AppBuilder Media Fields JavaScript
 * 
 * Provides comprehensive media capture and interaction functionality:
 * - Camera capture with live preview
 * - Audio recording with waveform visualization
 * - GPS location with interactive mapping
 * - Media gallery with drag-and-drop upload
 */

(function(window, document, $) {
    'use strict';

    // Namespace for media field functionality
    window.FABMediaFields = window.FABMediaFields || {};

    // Global configuration
    const CONFIG = {
        debug: false,
        apiEndpoint: '/api/v1/media',
        maxRetries: 3,
        retryDelay: 1000,
        chunkSize: 1024 * 1024, // 1MB chunks for large files
    };

    // Utility functions
    const Utils = {
        /**
         * Generate unique ID
         */
        generateId: function() {
            return 'fab_' + Math.random().toString(36).substr(2, 9);
        },

        /**
         * Debug logging
         */
        log: function(...args) {
            if (CONFIG.debug) {
                console.log('[FAB Media Fields]', ...args);
            }
        },

        /**
         * Error logging
         */
        error: function(...args) {
            console.error('[FAB Media Fields]', ...args);
        },

        /**
         * Get MIME type from data URL
         */
        getMimeFromDataUrl: function(dataUrl) {
            const match = dataUrl.match(/^data:([^;]+);base64,/);
            return match ? match[1] : null;
        },

        /**
         * Get file extension from MIME type
         */
        getExtensionFromMime: function(mimeType) {
            const mimeMap = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'video/mp4': '.mp4',
                'video/webm': '.webm',
                'video/ogg': '.ogv',
                'audio/wav': '.wav',
                'audio/mp3': '.mp3',
                'audio/ogg': '.ogg',
                'audio/webm': '.weba'
            };
            return mimeMap[mimeType] || '.bin';
        },

        /**
         * Format file size
         */
        formatFileSize: function(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },

        /**
         * Format duration
         */
        formatDuration: function(seconds) {
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        },

        /**
         * Create media metadata
         */
        createMediaMetadata: function(file, additionalData = {}) {
            return {
                filename: file.name || `capture_${Date.now()}${this.getExtensionFromMime(file.type)}`,
                size: file.size || 0,
                mime_type: file.type,
                created_at: new Date().toISOString(),
                device_info: {
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    ...additionalData
                }
            };
        }
    };

    // =======================================================================
    // Camera Field Implementation
    // =======================================================================

    class CameraField {
        constructor(element) {
            this.element = $(element);
            this.config = this.element.data('config') || {};
            this.fieldId = this.config.field_id;
            
            this.stream = null;
            this.recording = false;
            this.mediaRecorder = null;
            this.recordedChunks = [];
            this.currentFacingMode = 'environment'; // 'user' or 'environment'
            
            this.initializeElements();
            this.bindEvents();
            this.startCamera();
        }

        initializeElements() {
            this.preview = this.element.find('.camera-preview');
            this.canvas = this.element.find('.camera-canvas');
            this.hiddenInput = this.element.find(`#${this.fieldId}`);
            
            this.capturePhotoBtn = this.element.find('.camera-capture-photo');
            this.captureVideoBtn = this.element.find('.camera-capture-video');
            this.switchBtn = this.element.find('.camera-switch');
            this.gridToggleBtn = this.element.find('.camera-grid-toggle');
            this.settingsBtn = this.element.find('.camera-settings');
            
            this.statusText = this.element.find('.status-text');
            this.recordingIndicator = this.element.find('.recording-indicator');
            this.mediaPreview = this.element.find('.camera-media-preview');
            this.settingsPanel = this.element.find('.camera-settings-panel');
        }

        bindEvents() {
            // Capture buttons
            this.capturePhotoBtn.on('click', () => this.capturePhoto());
            this.captureVideoBtn.on('click', () => this.toggleVideoRecording());
            
            // Control buttons
            this.switchBtn.on('click', () => this.switchCamera());
            this.gridToggleBtn.on('click', () => this.toggleGrid());
            this.settingsBtn.on('click', () => this.toggleSettings());
            
            // Media preview actions
            this.element.find('.media-accept').on('click', () => this.acceptMedia());
            this.element.find('.media-retake').on('click', () => this.retakeMedia());
            
            // Settings
            this.element.find('.resolution-select').on('change', (e) => this.changeResolution(e.target.value));
            this.element.find('.quality-slider').on('input', (e) => this.updateQuality(e.target.value));
        }

        async startCamera() {
            try {
                this.statusText.text('Starting camera...');
                
                const constraints = {
                    video: {
                        facingMode: this.currentFacingMode,
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    },
                    audio: this.config.mode === 'video' || this.config.mode === 'both'
                };

                this.stream = await navigator.mediaDevices.getUserMedia(constraints);
                this.preview[0].srcObject = this.stream;
                
                this.statusText.text('Ready');
                this.enableControls(true);
                
                Utils.log('Camera started successfully');
            } catch (error) {
                Utils.error('Error starting camera:', error);
                this.statusText.text('Camera not available');
                this.showError('Unable to access camera. Please check permissions.');
            }
        }

        async switchCamera() {
            this.currentFacingMode = this.currentFacingMode === 'user' ? 'environment' : 'user';
            
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }
            
            await this.startCamera();
        }

        toggleGrid() {
            const grid = this.element.find('.camera-grid');
            grid.toggle();
            this.gridToggleBtn.toggleClass('active');
        }

        toggleSettings() {
            this.settingsPanel.toggle();
        }

        async capturePhoto() {
            if (!this.stream) return;

            try {
                const video = this.preview[0];
                const canvas = this.canvas[0];
                const ctx = canvas.getContext('2d');

                // Set canvas dimensions to match video
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;

                // Draw current frame
                ctx.drawImage(video, 0, 0);

                // Convert to blob
                canvas.toBlob((blob) => {
                    this.handleCapturedMedia(blob, 'photo');
                }, 'image/jpeg', this.config.quality || 0.8);

                // Show capture feedback
                this.showCaptureFlash();
                
            } catch (error) {
                Utils.error('Error capturing photo:', error);
                this.showError('Failed to capture photo');
            }
        }

        async toggleVideoRecording() {
            if (!this.recording) {
                await this.startVideoRecording();
            } else {
                this.stopVideoRecording();
            }
        }

        async startVideoRecording() {
            try {
                this.recordedChunks = [];
                this.mediaRecorder = new MediaRecorder(this.stream);
                
                this.mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        this.recordedChunks.push(event.data);
                    }
                };

                this.mediaRecorder.onstop = () => {
                    const blob = new Blob(this.recordedChunks, { type: 'video/webm' });
                    this.handleCapturedMedia(blob, 'video');
                };

                this.mediaRecorder.start();
                this.recording = true;
                
                this.captureVideoBtn.removeClass('btn-danger').addClass('btn-success')
                    .find('i').removeClass('fa-video').addClass('fa-stop');
                this.recordingIndicator.show();
                this.statusText.text('Recording...');
                
                Utils.log('Video recording started');
                
            } catch (error) {
                Utils.error('Error starting video recording:', error);
                this.showError('Failed to start video recording');
            }
        }

        stopVideoRecording() {
            if (this.mediaRecorder && this.recording) {
                this.mediaRecorder.stop();
                this.recording = false;
                
                this.captureVideoBtn.removeClass('btn-success').addClass('btn-danger')
                    .find('i').removeClass('fa-stop').addClass('fa-video');
                this.recordingIndicator.hide();
                this.statusText.text('Ready');
                
                Utils.log('Video recording stopped');
            }
        }

        handleCapturedMedia(blob, type) {
            const reader = new FileReader();
            reader.onload = (e) => {
                const dataUrl = e.target.result;
                const base64Data = dataUrl.split(',')[1];
                
                const mediaData = {
                    media_type: type,
                    data: base64Data,
                    metadata: Utils.createMediaMetadata({
                        name: `${type}_${Date.now()}${Utils.getExtensionFromMime(blob.type)}`,
                        size: blob.size,
                        type: blob.type
                    }),
                    thumbnail: null // Will be generated on server
                };

                this.showMediaPreview(dataUrl, type);
                this.currentMediaData = mediaData;
            };
            reader.readAsDataURL(blob);
        }

        showMediaPreview(dataUrl, type) {
            const previewImage = this.element.find('.media-preview-image');
            const previewVideo = this.element.find('.media-preview-video');
            
            if (type === 'photo') {
                previewImage.attr('src', dataUrl).show();
                previewVideo.hide();
            } else {
                previewVideo.attr('src', dataUrl).show();
                previewImage.hide();
            }
            
            this.mediaPreview.show();
            this.element.find('.camera-controls').hide();
        }

        acceptMedia() {
            if (this.currentMediaData) {
                this.hiddenInput.val(JSON.stringify(this.currentMediaData));
                this.element.trigger('media:captured', this.currentMediaData);
            }
            this.hidePreview();
        }

        retakeMedia() {
            this.currentMediaData = null;
            this.hidePreview();
        }

        hidePreview() {
            this.mediaPreview.hide();
            this.element.find('.camera-controls').show();
        }

        showCaptureFlash() {
            const flash = $('<div class="capture-flash"></div>');
            this.element.find('.camera-preview-container').append(flash);
            flash.fadeIn(100).fadeOut(100, () => flash.remove());
        }

        enableControls(enabled) {
            this.capturePhotoBtn.prop('disabled', !enabled);
            this.captureVideoBtn.prop('disabled', !enabled);
            this.switchBtn.prop('disabled', !enabled);
        }

        showError(message) {
            // Create error toast or modal
            const toast = $(`
                <div class="alert alert-danger alert-dismissible fade show camera-error" role="alert">
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
                </div>
            `);
            
            this.element.prepend(toast);
            setTimeout(() => toast.alert('close'), 5000);
        }

        destroy() {
            if (this.stream) {
                this.stream.getTracks().forEach(track => track.stop());
            }
            if (this.mediaRecorder && this.recording) {
                this.mediaRecorder.stop();
            }
        }
    }

    // =======================================================================
    // Audio Recording Field Implementation
    // =======================================================================

    class AudioRecordingField {
        constructor(element) {
            this.element = $(element);
            this.config = this.element.data('config') || {};
            this.fieldId = this.config.field_id;
            
            this.mediaRecorder = null;
            this.audioContext = null;
            this.analyser = null;
            this.recording = false;
            this.recordedChunks = [];
            this.startTime = null;
            this.animationId = null;
            
            this.initializeElements();
            this.bindEvents();
            this.initializeAudio();
        }

        initializeElements() {
            this.visualizer = this.element.find('.audio-visualizer');
            this.waveform = this.element.find('.audio-waveform');
            this.hiddenInput = this.element.find(`#${this.fieldId}`);
            this.audioElement = this.element.find(`#${this.fieldId}_audio`);
            
            this.recordBtn = this.element.find('.audio-record');
            this.stopBtn = this.element.find('.audio-stop');
            this.playBtn = this.element.find('.audio-play');
            this.pauseBtn = this.element.find('.audio-pause');
            this.deleteBtn = this.element.find('.audio-delete');
            
            this.recordingTime = this.element.find('.recording-time');
            this.fileSize = this.element.find('.file-size');
            this.levelBar = this.element.find('.level-bar');
        }

        bindEvents() {
            this.recordBtn.on('click', () => this.startRecording());
            this.stopBtn.on('click', () => this.stopRecording());
            this.playBtn.on('click', () => this.playRecording());
            this.pauseBtn.on('click', () => this.pauseRecording());
            this.deleteBtn.on('click', () => this.deleteRecording());
            
            // Settings
            this.element.find('.quality-select').on('change', (e) => this.updateQuality(e.target.value));
            this.element.find('.format-select').on('change', (e) => this.updateFormat(e.target.value));
        }

        async initializeAudio() {
            try {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
                this.analyser = this.audioContext.createAnalyser();
                this.analyser.fftSize = 256;
                
                Utils.log('Audio context initialized');
            } catch (error) {
                Utils.error('Error initializing audio:', error);
            }
        }

        async startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        sampleRate: parseInt(this.element.find('.quality-select').val()),
                        echoCancellation: true,
                        noiseSuppression: this.element.find('.noise-reduction').is(':checked')
                    }
                });

                // Connect to analyser for visualization
                const source = this.audioContext.createMediaStreamSource(stream);
                source.connect(this.analyser);

                this.mediaRecorder = new MediaRecorder(stream, {
                    mimeType: this.element.find('.format-select').val() || 'audio/webm'
                });

                this.recordedChunks = [];
                this.mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        this.recordedChunks.push(event.data);
                    }
                };

                this.mediaRecorder.onstop = () => {
                    const blob = new Blob(this.recordedChunks, { 
                        type: this.mediaRecorder.mimeType 
                    });
                    this.handleRecordedAudio(blob);
                };

                this.mediaRecorder.start();
                this.recording = true;
                this.startTime = Date.now();
                
                this.updateUIForRecording(true);
                this.startVisualization();
                this.startTimer();
                
                Utils.log('Audio recording started');
                
            } catch (error) {
                Utils.error('Error starting audio recording:', error);
                this.showError('Failed to access microphone');
            }
        }

        stopRecording() {
            if (this.mediaRecorder && this.recording) {
                this.mediaRecorder.stop();
                this.recording = false;
                
                this.updateUIForRecording(false);
                this.stopVisualization();
                this.stopTimer();
                
                // Stop all tracks
                this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
                
                Utils.log('Audio recording stopped');
            }
        }

        handleRecordedAudio(blob) {
            const reader = new FileReader();
            reader.onload = (e) => {
                const dataUrl = e.target.result;
                const base64Data = dataUrl.split(',')[1];
                
                const mediaData = {
                    media_type: 'audio',
                    data: base64Data,
                    metadata: Utils.createMediaMetadata({
                        name: `audio_${Date.now()}${Utils.getExtensionFromMime(blob.type)}`,
                        size: blob.size,
                        type: blob.type,
                        duration: (Date.now() - this.startTime) / 1000
                    })
                };

                this.hiddenInput.val(JSON.stringify(mediaData));
                this.audioElement.attr('src', dataUrl);
                
                this.fileSize.text(Utils.formatFileSize(blob.size)).show();
                this.updateUIForPlayback(true);
                
                this.generateWaveform(blob);
                this.element.trigger('audio:recorded', mediaData);
            };
            reader.readAsDataURL(blob);
        }

        playRecording() {
            const audio = this.audioElement[0];
            if (audio.src) {
                audio.play();
                this.playBtn.hide();
                this.pauseBtn.show();
            }
        }

        pauseRecording() {
            const audio = this.audioElement[0];
            audio.pause();
            this.playBtn.show();
            this.pauseBtn.hide();
        }

        deleteRecording() {
            if (confirm('Are you sure you want to delete this recording?')) {
                this.hiddenInput.val('');
                this.audioElement.attr('src', '');
                this.fileSize.hide();
                this.updateUIForPlayback(false);
                this.clearWaveform();
                
                this.element.trigger('audio:deleted');
            }
        }

        startVisualization() {
            const canvas = this.visualizer[0];
            const ctx = canvas.getContext('2d');
            const bufferLength = this.analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            const draw = () => {
                if (!this.recording) return;
                
                this.animationId = requestAnimationFrame(draw);
                
                this.analyser.getByteFrequencyData(dataArray);
                
                ctx.fillStyle = '#f0f0f0';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                
                const barWidth = (canvas.width / bufferLength) * 2.5;
                let barHeight;
                let x = 0;
                
                for (let i = 0; i < bufferLength; i++) {
                    barHeight = (dataArray[i] / 255) * canvas.height;
                    
                    const r = barHeight + 25 * (i / bufferLength);
                    const g = 250 * (i / bufferLength);
                    const b = 50;
                    
                    ctx.fillStyle = `rgb(${r},${g},${b})`;
                    ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                    
                    x += barWidth + 1;
                }
                
                // Update level meter
                const average = dataArray.reduce((a, b) => a + b) / bufferLength;
                const level = (average / 255) * 100;
                this.levelBar.css('width', `${level}%`);
            };
            
            draw();
        }

        stopVisualization() {
            if (this.animationId) {
                cancelAnimationFrame(this.animationId);
                this.animationId = null;
            }
            
            // Clear visualizer
            const canvas = this.visualizer[0];
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            this.levelBar.css('width', '0%');
        }

        startTimer() {
            this.timerInterval = setInterval(() => {
                if (this.recording && this.startTime) {
                    const elapsed = (Date.now() - this.startTime) / 1000;
                    this.recordingTime.text(Utils.formatDuration(elapsed));
                    
                    // Check max duration
                    if (elapsed >= this.config.max_duration) {
                        this.stopRecording();
                    }
                }
            }, 100);
        }

        stopTimer() {
            if (this.timerInterval) {
                clearInterval(this.timerInterval);
                this.timerInterval = null;
            }
        }

        generateWaveform(blob) {
            // This would generate a visual waveform representation
            // For now, just show the waveform container
            this.element.find('.audio-waveform-container').show();
        }

        clearWaveform() {
            this.element.find('.audio-waveform-container').hide();
            const canvas = this.waveform[0];
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }

        updateUIForRecording(recording) {
            this.recordBtn.prop('disabled', recording);
            this.stopBtn.prop('disabled', !recording);
            
            if (recording) {
                this.recordBtn.removeClass('btn-primary').addClass('btn-secondary');
            } else {
                this.recordBtn.removeClass('btn-secondary').addClass('btn-primary');
            }
        }

        updateUIForPlayback(hasAudio) {
            this.playBtn.prop('disabled', !hasAudio);
            this.deleteBtn.prop('disabled', !hasAudio);
            
            if (hasAudio) {
                this.playBtn.show();
                this.pauseBtn.hide();
            }
        }

        showError(message) {
            const toast = $(`
                <div class="alert alert-danger alert-dismissible fade show audio-error" role="alert">
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
                </div>
            `);
            
            this.element.prepend(toast);
            setTimeout(() => toast.alert('close'), 5000);
        }

        destroy() {
            this.stopRecording();
            if (this.audioContext) {
                this.audioContext.close();
            }
        }
    }

    // =======================================================================
    // GPS Field Implementation  
    // =======================================================================

    class GPSField {
        constructor(element) {
            this.element = $(element);
            this.config = this.element.data('config') || {};
            this.fieldId = this.config.field_id;
            
            this.map = null;
            this.marker = null;
            this.watchId = null;
            this.currentPosition = null;
            
            this.initializeElements();
            this.bindEvents();
            this.initializeMap();
        }

        initializeElements() {
            this.mapContainer = this.element.find(`#${this.fieldId}_map`);
            this.hiddenInput = this.element.find(`#${this.fieldId}`);
            
            this.locateBtn = this.element.find('.gps-locate');
            this.trackBtn = this.element.find('.gps-track');
            this.clearBtn = this.element.find('.gps-clear');
            this.shareBtn = this.element.find('.gps-share');
            
            this.coordinatesDisplay = this.element.find('.coordinates-display');
            this.locationDetails = this.element.find('.location-details');
            this.addressInput = this.element.find('.address-input');
            this.addressSearch = this.element.find('.address-search');
        }

        bindEvents() {
            this.locateBtn.on('click', () => this.getCurrentLocation());
            this.trackBtn.on('click', () => this.toggleTracking());
            this.clearBtn.on('click', () => this.clearLocation());
            this.shareBtn.on('click', () => this.shareLocation());
            
            this.addressSearch.on('click', () => this.searchAddress());
            this.addressInput.on('keypress', (e) => {
                if (e.which === 13) this.searchAddress();
            });
        }

        async initializeMap() {
            try {
                const mapProvider = this.config.map_provider || 'leaflet';
                
                if (mapProvider === 'leaflet') {
                    await this.initializeLeafletMap();
                } else if (mapProvider === 'google') {
                    await this.initializeGoogleMap();
                }
                
                Utils.log('Map initialized with provider:', mapProvider);
            } catch (error) {
                Utils.error('Error initializing map:', error);
                this.showError('Failed to load map');
            }
        }

        async initializeLeafletMap() {
            // Load Leaflet if not already loaded
            if (typeof L === 'undefined') {
                await this.loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
                await this.loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
            }

            this.map = L.map(this.mapContainer[0]).setView([0, 0], this.config.zoom_level || 15);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(this.map);

            this.map.on('click', (e) => {
                this.setLocation(e.latlng.lat, e.latlng.lng);
            });
        }

        async initializeGoogleMap() {
            // This would initialize Google Maps
            // Requires Google Maps API key
            this.showError('Google Maps integration requires API key configuration');
        }

        getCurrentLocation() {
            if (!navigator.geolocation) {
                this.showError('Geolocation is not supported by this browser');
                return;
            }

            this.locateBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Locating...');

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = position.coords.accuracy;
                    
                    this.setLocation(lat, lng, {
                        accuracy: accuracy,
                        altitude: position.coords.altitude,
                        heading: position.coords.heading,
                        speed: position.coords.speed
                    });
                    
                    this.locateBtn.prop('disabled', false).html('<i class="fa fa-crosshairs"></i> Locate Me');
                },
                (error) => {
                    this.showError(`Location error: ${error.message}`);
                    this.locateBtn.prop('disabled', false).html('<i class="fa fa-crosshairs"></i> Locate Me');
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 60000
                }
            );
        }

        toggleTracking() {
            if (this.watchId) {
                navigator.geolocation.clearWatch(this.watchId);
                this.watchId = null;
                this.trackBtn.removeClass('btn-success').addClass('btn-secondary')
                    .html('<i class="fa fa-route"></i> Track');
            } else {
                this.watchId = navigator.geolocation.watchPosition(
                    (position) => {
                        const lat = position.coords.latitude;
                        const lng = position.coords.longitude;
                        this.setLocation(lat, lng, {
                            accuracy: position.coords.accuracy,
                            altitude: position.coords.altitude,
                            heading: position.coords.heading,
                            speed: position.coords.speed
                        });
                    },
                    (error) => {
                        this.showError(`Tracking error: ${error.message}`);
                    },
                    {
                        enableHighAccuracy: true,
                        timeout: 5000,
                        maximumAge: 1000
                    }
                );
                
                this.trackBtn.removeClass('btn-secondary').addClass('btn-success')
                    .html('<i class="fa fa-stop"></i> Stop Tracking');
            }
        }

        setLocation(lat, lng, additionalData = {}) {
            this.currentPosition = {
                latitude: lat,
                longitude: lng,
                timestamp: new Date().toISOString(),
                ...additionalData
            };

            // Update map
            if (this.map) {
                this.map.setView([lat, lng], this.config.zoom_level || 15);
                
                if (this.marker) {
                    this.marker.setLatLng([lat, lng]);
                } else {
                    this.marker = L.marker([lat, lng]).addTo(this.map);
                }
            }

            // Update UI
            this.coordinatesDisplay.text(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
            this.locationDetails.show();
            this.element.find('.latitude-value').text(lat.toFixed(6));
            this.element.find('.longitude-value').text(lng.toFixed(6));
            this.element.find('.altitude-value').text(additionalData.altitude ? `${additionalData.altitude.toFixed(1)}m` : '-');
            this.element.find('.accuracy-value').text(additionalData.accuracy ? `±${additionalData.accuracy.toFixed(1)}m` : '-');

            // Update hidden input
            const locationData = {
                media_type: 'location',
                data: '',
                coordinates: this.currentPosition,
                metadata: Utils.createMediaMetadata({
                    name: `location_${Date.now()}.json`,
                    size: JSON.stringify(this.currentPosition).length,
                    type: 'application/json'
                })
            };

            this.hiddenInput.val(JSON.stringify(locationData));
            this.element.trigger('location:updated', locationData);

            // Reverse geocoding
            this.reverseGeocode(lat, lng);
        }

        async reverseGeocode(lat, lng) {
            try {
                const response = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`);
                const data = await response.json();
                
                if (data.display_name) {
                    this.coordinatesDisplay.text(`${data.display_name}`);
                }
            } catch (error) {
                Utils.log('Reverse geocoding failed:', error);
            }
        }

        async searchAddress() {
            const address = this.addressInput.val().trim();
            if (!address) return;

            try {
                this.addressSearch.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');
                
                const response = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(address)}&format=json&limit=1`);
                const data = await response.json();
                
                if (data.length > 0) {
                    const result = data[0];
                    this.setLocation(parseFloat(result.lat), parseFloat(result.lon));
                } else {
                    this.showError('Address not found');
                }
                
                this.addressSearch.prop('disabled', false).html('<i class="fa fa-search"></i>');
            } catch (error) {
                this.showError('Address search failed');
                this.addressSearch.prop('disabled', false).html('<i class="fa fa-search"></i>');
            }
        }

        clearLocation() {
            this.currentPosition = null;
            this.hiddenInput.val('');
            
            if (this.marker) {
                this.map.removeLayer(this.marker);
                this.marker = null;
            }
            
            this.coordinatesDisplay.text('No location selected');
            this.locationDetails.hide();
            
            this.element.trigger('location:cleared');
        }

        shareLocation() {
            if (!this.currentPosition) {
                this.showError('No location to share');
                return;
            }

            const url = `https://www.openstreetmap.org/?mlat=${this.currentPosition.latitude}&mlon=${this.currentPosition.longitude}&zoom=15`;
            
            if (navigator.share) {
                navigator.share({
                    title: 'My Location',
                    text: `Latitude: ${this.currentPosition.latitude}, Longitude: ${this.currentPosition.longitude}`,
                    url: url
                });
            } else {
                // Fallback to copying to clipboard
                navigator.clipboard.writeText(url).then(() => {
                    this.showSuccess('Location URL copied to clipboard');
                });
            }
        }

        loadScript(src) {
            return new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = src;
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }

        loadCSS(href) {
            return new Promise((resolve) => {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = href;
                link.onload = resolve;
                document.head.appendChild(link);
            });
        }

        showError(message) {
            const toast = $(`
                <div class="alert alert-danger alert-dismissible fade show gps-error" role="alert">
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
                </div>
            `);
            
            this.element.prepend(toast);
            setTimeout(() => toast.alert('close'), 5000);
        }

        showSuccess(message) {
            const toast = $(`
                <div class="alert alert-success alert-dismissible fade show gps-success" role="alert">
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
                </div>
            `);
            
            this.element.prepend(toast);
            setTimeout(() => toast.alert('close'), 3000);
        }

        destroy() {
            if (this.watchId) {
                navigator.geolocation.clearWatch(this.watchId);
            }
            if (this.map) {
                this.map.remove();
            }
        }
    }

    // =======================================================================
    // Media Gallery Field Implementation
    // =======================================================================

    class MediaGalleryField {
        constructor(element) {
            this.element = $(element);
            this.config = this.element.data('config') || {};
            this.fieldId = this.config.field_id;
            
            this.mediaItems = [];
            this.currentPreview = null;
            
            this.initializeElements();
            this.bindEvents();
            this.loadExistingMedia();
        }

        initializeElements() {
            this.dropzone = this.element.find('.upload-dropzone');
            this.fileInput = this.element.find('.gallery-file-input');
            this.hiddenInput = this.element.find(`#${this.fieldId}`);
            this.itemsContainer = this.element.find('.gallery-items-container');
            this.addButton = this.element.find('.gallery-add');
            this.previewModal = this.element.find('.gallery-preview-modal');
        }

        bindEvents() {
            // File upload
            this.dropzone.on('click', () => this.fileInput.click());
            this.addButton.on('click', () => this.fileInput.click());
            this.fileInput.on('change', (e) => this.handleFileSelect(e.target.files));
            
            // Drag and drop
            this.dropzone.on('dragover', (e) => {
                e.preventDefault();
                this.dropzone.addClass('dragover');
            });
            
            this.dropzone.on('dragleave', () => {
                this.dropzone.removeClass('dragover');
            });
            
            this.dropzone.on('drop', (e) => {
                e.preventDefault();
                this.dropzone.removeClass('dragover');
                this.handleFileSelect(e.originalEvent.dataTransfer.files);
            });
            
            // Preview modal
            this.element.find('.preview-close').on('click', () => this.closePreview());
            this.element.find('.preview-overlay').on('click', () => this.closePreview());
            this.element.find('.preview-delete').on('click', () => this.deleteCurrentPreview());
        }

        handleFileSelect(files) {
            if (files.length === 0) return;
            
            if (this.mediaItems.length + files.length > this.config.max_files) {
                this.showError(`Maximum ${this.config.max_files} files allowed`);
                return;
            }

            Array.from(files).forEach(file => {
                if (this.isValidFile(file)) {
                    this.addMediaItem(file);
                } else {
                    this.showError(`Invalid file type: ${file.name}`);
                }
            });
        }

        isValidFile(file) {
            const allowedTypes = this.config.accept ? this.config.accept.split(',') : ['*/*'];
            return allowedTypes.some(type => {
                if (type === '*/*') return true;
                if (type.endsWith('/*')) {
                    return file.type.startsWith(type.substring(0, type.length - 1));
                }
                return file.type === type;
            });
        }

        async addMediaItem(file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                const dataUrl = e.target.result;
                const base64Data = dataUrl.split(',')[1];
                
                const mediaData = {
                    id: Utils.generateId(),
                    media_type: this.getMediaType(file.type),
                    data: base64Data,
                    metadata: Utils.createMediaMetadata(file),
                    thumbnail: null
                };

                this.mediaItems.push(mediaData);
                this.renderMediaItem(mediaData, dataUrl);
                this.updateHiddenInput();
                
                this.element.trigger('media:added', mediaData);
            };
            reader.readAsDataURL(file);
        }

        getMediaType(mimeType) {
            if (mimeType.startsWith('image/')) return 'photo';
            if (mimeType.startsWith('video/')) return 'video';
            if (mimeType.startsWith('audio/')) return 'audio';
            return 'document';
        }

        renderMediaItem(mediaData, dataUrl) {
            const item = $(`
                <div class="gallery-item" data-id="${mediaData.id}">
                    <div class="gallery-item-content">
                        ${this.renderMediaPreview(mediaData, dataUrl)}
                        <div class="gallery-item-overlay">
                            <button type="button" class="btn btn-sm btn-primary gallery-item-preview">
                                <i class="fa fa-eye"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-danger gallery-item-delete">
                                <i class="fa fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div class="gallery-item-info">
                        <small class="text-muted">${mediaData.metadata.filename}</small>
                        <small class="text-muted">${Utils.formatFileSize(mediaData.metadata.size)}</small>
                    </div>
                </div>
            `);

            item.find('.gallery-item-preview').on('click', () => this.showPreview(mediaData, dataUrl));
            item.find('.gallery-item-delete').on('click', () => this.deleteMediaItem(mediaData.id));

            this.itemsContainer.append(item);
        }

        renderMediaPreview(mediaData, dataUrl) {
            switch (mediaData.media_type) {
                case 'photo':
                    return `<img src="${dataUrl}" class="gallery-thumbnail" alt="${mediaData.metadata.filename}">`;
                case 'video':
                    return `<video src="${dataUrl}" class="gallery-thumbnail" muted></video>`;
                case 'audio':
                    return `<div class="gallery-audio-preview">
                        <i class="fa fa-music"></i>
                        <span>Audio</span>
                    </div>`;
                default:
                    return `<div class="gallery-document-preview">
                        <i class="fa fa-file"></i>
                        <span>Document</span>
                    </div>`;
            }
        }

        showPreview(mediaData, dataUrl) {
            this.currentPreview = mediaData;
            
            const previewImage = this.element.find('.preview-image');
            const previewVideo = this.element.find('.preview-video');
            const previewAudio = this.element.find('.preview-audio');
            
            // Hide all previews
            previewImage.hide();
            previewVideo.hide();
            previewAudio.hide();
            
            // Show appropriate preview
            switch (mediaData.media_type) {
                case 'photo':
                    previewImage.attr('src', dataUrl).show();
                    break;
                case 'video':
                    previewVideo.attr('src', dataUrl).show();
                    break;
                case 'audio':
                    previewAudio.attr('src', dataUrl).show();
                    break;
            }
            
            this.element.find('.preview-title').text(mediaData.metadata.filename);
            this.previewModal.show();
        }

        closePreview() {
            this.previewModal.hide();
            this.currentPreview = null;
        }

        deleteCurrentPreview() {
            if (this.currentPreview) {
                this.deleteMediaItem(this.currentPreview.id);
                this.closePreview();
            }
        }

        deleteMediaItem(id) {
            this.mediaItems = this.mediaItems.filter(item => item.id !== id);
            this.element.find(`.gallery-item[data-id="${id}"]`).remove();
            this.updateHiddenInput();
            
            this.element.trigger('media:deleted', { id });
        }

        updateHiddenInput() {
            this.hiddenInput.val(JSON.stringify(this.mediaItems));
        }

        loadExistingMedia() {
            const existingData = this.hiddenInput.val();
            if (existingData) {
                try {
                    this.mediaItems = JSON.parse(existingData);
                    this.mediaItems.forEach(item => {
                        const dataUrl = `data:${item.metadata.mime_type};base64,${item.data}`;
                        this.renderMediaItem(item, dataUrl);
                    });
                } catch (error) {
                    Utils.error('Error loading existing media:', error);
                }
            }
        }

        showError(message) {
            const toast = $(`
                <div class="alert alert-danger alert-dismissible fade show gallery-error" role="alert">
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span>&times;</span>
                    </button>
                </div>
            `);
            
            this.element.prepend(toast);
            setTimeout(() => toast.alert('close'), 5000);
        }
    }

    // =======================================================================
    // Public API and Initialization
    // =======================================================================

    // Expose classes
    window.FABMediaFields.CameraField = CameraField;
    window.FABMediaFields.AudioRecordingField = AudioRecordingField;
    window.FABMediaFields.GPSField = GPSField;
    window.FABMediaFields.MediaGalleryField = MediaGalleryField;
    window.FABMediaFields.Utils = Utils;

    // Auto-initialize fields
    $(document).ready(function() {
        // Initialize camera fields
        $('.fab-camera-field').each(function() {
            new CameraField(this);
        });

        // Initialize audio recording fields
        $('.fab-audio-field').each(function() {
            new AudioRecordingField(this);
        });

        // Initialize GPS fields
        $('.fab-gps-field').each(function() {
            new GPSField(this);
        });

        // Initialize media gallery fields
        $('.fab-media-gallery-field').each(function() {
            new MediaGalleryField(this);
        });

        Utils.log('FAB Media Fields initialized');
    });

})(window, document, jQuery);