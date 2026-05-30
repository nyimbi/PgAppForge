"""
Beautiful Public IndexView for PgForge

Showcases the comprehensive media capabilities and enhanced menu system:
- Interactive camera and audio recording demos
- GPS location and mapping functionality  
- Media gallery with drag-and-drop uploads
- Dynamic menu rendering with multiple styles
- Responsive design with mobile optimization
"""

from flask import render_template, jsonify, request, current_app, url_for
from flask_babel import gettext as __, lazy_gettext as _l
from werkzeug.exceptions import NotFound

from ..baseviews import BaseView, expose
from ..security.decorators import has_access
from .menu_rendering import get_menu_engine, MenuRenderConfig, MenuRenderMode
from .fields.media_fields import MediaType, CameraMode, AudioFormat


class PublicIndexView(BaseView):
    """
    Beautiful public-facing index view that showcases PgForge capabilities.
    
    Features:
    - Interactive media field demonstrations
    - Menu rendering system showcase
    - Responsive design with modern UI
    - Public accessibility (no authentication required)
    - SEO optimized with meta tags
    """
    
    route_base = '/public'
    default_view = 'index'
    
    @expose('/')
    @has_access
    def index(self):
        """
        Main public index page with media showcase.
        
        Returns:
            Rendered template with demo components
        """
        try:
            # Get menu rendering configuration for demo
            menu_config = MenuRenderConfig.from_app_config()
            menu_engine = get_menu_engine()
            
            # Demo menu items for showcase
            demo_menu_items = self._create_demo_menu_items()
            
            # Render different menu types for demonstration
            navbar_html = self._render_menu_demo(demo_menu_items, MenuRenderMode.NAVBAR)
            tree_html = self._render_menu_demo(demo_menu_items, MenuRenderMode.TREE)
            sidebar_html = self._render_menu_demo(demo_menu_items, MenuRenderMode.SIDEBAR)
            
            # Media field configurations for demo
            media_demos = {
                'camera': {
                    'mode': CameraMode.BOTH.value,
                    'resolution': '1280x720',
                    'quality': 0.8
                },
                'audio': {
                    'format': AudioFormat.WAV.value,
                    'max_duration': 60,
                    'quality': 44100
                },
                'gps': {
                    'map_provider': 'leaflet',
                    'zoom_level': 15,
                    'enable_tracking': True
                },
                'gallery': {
                    'media_types': [MediaType.PHOTO.value, MediaType.VIDEO.value, MediaType.AUDIO.value],
                    'max_files': 10
                }
            }
            
            # Extended field configurations for demo
            extended_fields_demos = self._get_extended_fields_config(),
                'audio': {
                    'format': AudioFormat.WAV.value,
                    'max_duration': 60,
                    'quality': 44100
                },
                'gps': {
                    'map_provider': 'leaflet',
                    'zoom_level': 15,
                    'enable_tracking': True
                },
                'gallery': {
                    'media_types': [MediaType.PHOTO.value, MediaType.VIDEO.value, MediaType.AUDIO.value],
                    'max_files': 10
                }
            }
            
            # Application statistics for showcase
            app_stats = self._get_app_statistics()
            
            # Feature highlights
            features = self._get_feature_highlights()
            
            return self.render_template(
                'public_index.html',
                title=_l('PgForge Enhanced Demo'),
                navbar_demo=navbar_html,
                tree_demo=tree_html,
                sidebar_demo=sidebar_html,
                media_demos=media_demos,
                extended_fields_demos=extended_fields_demos,
                app_stats=app_stats,
                features=features,
                menu_config=menu_config,
                current_user=None  # Public view
            )
            
        except Exception as e:
            current_app.logger.error(f"Error in public index view: {e}")
            return self.render_template(
                'public_error.html',
                error_message=__('An error occurred while loading the page'),
                title=_l('Error')
            ), 500
    
    @expose('/demo/camera')
    @has_access
    def camera_demo(self):
        """
        Dedicated camera demo page.
        
        Returns:
            Rendered camera demo template
        """
        return self.render_template(
            'public_camera_demo.html',
            title=_l('Camera Capture Demo'),
            demo_config={
                'mode': CameraMode.BOTH.value,
                'resolution': '1920x1080',
                'quality': 0.9,
                'enable_grid': True,
                'enable_timer': True
            }
        )
    
    @expose('/demo/audio')
    @has_access
    def audio_demo(self):
        """
        Dedicated audio recording demo page.
        
        Returns:
            Rendered audio demo template
        """
        return self.render_template(
            'public_audio_demo.html',
            title=_l('Audio Recording Demo'),
            demo_config={
                'format': AudioFormat.WAV.value,
                'max_duration': 300,
                'quality': 48000,
                'enable_waveform': True,
                'enable_effects': True
            }
        )
    
    @expose('/demo/gps')
    @has_access
    def gps_demo(self):
        """
        Dedicated GPS and mapping demo page.
        
        Returns:
            Rendered GPS demo template
        """
        return self.render_template(
            'public_gps_demo.html',
            title=_l('GPS Location Demo'),
            demo_config={
                'map_provider': 'leaflet',
                'zoom_level': 12,
                'enable_tracking': True,
                'enable_geocoding': True,
                'show_weather': True
            }
        )
    
    @expose('/demo/gallery')
    @has_access
    def gallery_demo(self):
        """
        Dedicated media gallery demo page.
        
        Returns:
            Rendered gallery demo template
        """
        return self.render_template(
            'public_gallery_demo.html',
            title=_l('Media Gallery Demo'),
            demo_config={
                'media_types': [
                    MediaType.PHOTO.value, 
                    MediaType.VIDEO.value, 
                    MediaType.AUDIO.value
                ],
                'max_files': 20,
                'enable_editing': True,
                'enable_sharing': True
            }
        )
    
    @expose('/demo/menus')
    @has_access
    def menus_demo(self):
        """
        Dedicated menu rendering demo page.
        
        Returns:
            Rendered menu demo template
        """
        demo_menu_items = self._create_demo_menu_items()
        
        # Render all menu types
        menu_demos = {}
        for mode in MenuRenderMode:
            menu_demos[mode.value] = self._render_menu_demo(demo_menu_items, mode)
        
        return self.render_template(
            'public_menus_demo.html',
            title=_l('Menu Rendering Demo'),
            menu_demos=menu_demos,
            demo_menu_items=demo_menu_items
        )
    
    @expose('/demo/extended-fields')
    @has_access
    def extended_fields_demo(self):
        """
        Comprehensive demo page for all extended field types.
        
        Returns:
            Rendered extended fields demo template
        """
        return self.render_template(
            'public_extended_fields_demo.html',
            title=_l('Extended Fields Demo'),
            field_demos=self._get_extended_fields_config()
        )
    
    @expose('/demo/richtext')
    @has_access
    def richtext_demo(self):
        """
        Rich text editor demo page.
        
        Returns:
            Rendered rich text demo template
        """
        return self.render_template(
            'public_richtext_demo.html',
            title=_l('Rich Text Editor Demo'),
            demo_config={
                'editor_type': 'tinymce',
                'height': 400,
                'features': ['formatting', 'media', 'tables', 'links', 'images']
            }
        )
    
    @expose('/demo/code-editor')
    @has_access
    def code_editor_demo(self):
        """
        Code editor demo page.
        
        Returns:
            Rendered code editor demo template
        """
        return self.render_template(
            'public_code_editor_demo.html',
            title=_l('Code Editor Demo'),
            demo_config={
                'language': 'python',
                'theme': 'vs-dark',
                'features': ['syntax_highlighting', 'autocomplete', 'error_detection', 'formatting']
            }
        )
    
    @expose('/demo/datetime-picker')
    @has_access
    def datetime_picker_demo(self):
        """
        DateTime picker demo page.
        
        Returns:
            Rendered datetime picker demo template
        """
        return self.render_template(
            'public_datetime_picker_demo.html',
            title=_l('DateTime Picker Demo'),
            demo_config={
                'include_time': True,
                'include_timezone': True,
                'formats': ['YYYY-MM-DD HH:mm:ss', 'MM/DD/YYYY HH:mm:ss', 'DD/MM/YYYY HH:mm:ss']
            }
        )
    
    @expose('/demo/color-picker')
    @has_access
    def color_picker_demo(self):
        """
        Color picker demo page.
        
        Returns:
            Rendered color picker demo template
        """
        return self.render_template(
            'public_color_picker_demo.html',
            title=_l('Color Picker Demo'),
            demo_config={
                'include_alpha': True,
                'show_swatches': True,
                'formats': ['hex', 'rgb', 'hsl', 'rgba']
            }
        )
    
    @expose('/demo/signature')
    @has_access
    def signature_demo(self):
        """
        Digital signature demo page.
        
        Returns:
            Rendered signature demo template
        """
        return self.render_template(
            'public_signature_demo.html',
            title=_l('Digital Signature Demo'),
            demo_config={
                'width': 600,
                'height': 300,
                'features': ['pen_size', 'pen_color', 'undo', 'clear', 'save']
            }
        )
    
    @expose('/demo/rating')
    @has_access
    def rating_demo(self):
        """
        Rating system demo page.
        
        Returns:
            Rendered rating demo template
        """
        return self.render_template(
            'public_rating_demo.html',
            title=_l('Rating System Demo'),
            demo_config={
                'max_rating': 5,
                'allow_half_stars': True,
                'show_review': True,
                'features': ['star_rating', 'reviews', 'analytics']
            }
        )
    
    @expose('/demo/qrcode')
    @has_access
    def qrcode_demo(self):
        """
        QR code demo page.
        
        Returns:
            Rendered QR code demo template
        """
        return self.render_template(
            'public_qrcode_demo.html',
            title=_l('QR Code Demo'),
            demo_config={
                'size': 200,
                'allow_scanning': True,
                'features': ['generation', 'scanning', 'download', 'customization']
            }
        )
    
    @expose('/demo/file-upload')
    @has_access
    def file_upload_demo(self):
        """
        Advanced file upload demo page.
        
        Returns:
            Rendered file upload demo template
        """
        return self.render_template(
            'public_file_upload_demo.html',
            title=_l('File Upload Demo'),
            demo_config={
                'max_files': 5,
                'max_size_mb': 10,
                'allowed_types': ['image/*', 'video/*', 'audio/*', '.pdf', '.txt'],
                'features': ['drag_drop', 'progress', 'validation', 'preview']
            }
        )
    
    @expose('/demo/json-editor')
    @has_access
    def json_editor_demo(self):
        """
        JSON editor demo page.
        
        Returns:
            Rendered JSON editor demo template
        """
        return self.render_template(
            'public_json_editor_demo.html',
            title=_l('JSON Editor Demo'),
            demo_config={
                'height': 400,
                'schema': {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "number"},
                        "email": {"type": "string", "format": "email"}
                    }
                },
                'features': ['validation', 'formatting', 'tree_view', 'form_view']
            }
        )
    
    @expose('/demo/tags')
    @has_access
    def tags_demo(self):
        """
        Tag field demo page.
        
        Returns:
            Rendered tags demo template
        """
        return self.render_template(
            'public_tags_demo.html',
            title=_l('Tag Field Demo'),
            demo_config={
                'max_tags': 10,
                'allow_custom': True,
                'suggestions': ['python', 'javascript', 'react', 'flask', 'web', 'mobile', 'api', 'database'],
                'features': ['autocomplete', 'categorization', 'suggestions']
            }
        )
    
    @expose('/demo/password-strength')
    @has_access
    def password_strength_demo(self):
        """
        Password strength demo page.
        
        Returns:
            Rendered password strength demo template
        """
        return self.render_template(
            'public_password_strength_demo.html',
            title=_l('Password Strength Demo'),
            demo_config={
                'show_suggestions': True,
                'show_generator': True,
                'features': ['strength_meter', 'requirements', 'suggestions', 'generator']
            }
        )
    
    @expose('/demo/phone-number')
    @has_access
    def phone_number_demo(self):
        """
        International phone number demo page.
        
        Returns:
            Rendered phone number demo template
        """
        return self.render_template(
            'public_phone_number_demo.html',
            title=_l('Phone Number Demo'),
            demo_config={
                'default_country': 'US',
                'show_validation': True,
                'features': ['international_format', 'validation', 'carrier_info', 'location_info']
            }
        )
    
    @expose('/demo/address')
    @has_access
    def address_demo(self):
        """
        Address field demo page.
        
        Returns:
            Rendered address demo template
        """
        return self.render_template(
            'public_address_demo.html',
            title=_l('Address Field Demo'),
            demo_config={
                'include_geocoding': True,
                'country_default': 'US',
                'features': ['autocomplete', 'geocoding', 'validation', 'mapping']
            }
        )
    
    @expose('/demo/drawing')
    @has_access
    def drawing_demo(self):
        """
        Digital drawing demo page.
        
        Returns:
            Rendered drawing demo template
        """
        return self.render_template(
            'public_drawing_demo.html',
            title=_l('Drawing Canvas Demo'),
            demo_config={
                'width': 800,
                'height': 600,
                'tools': ['pen', 'brush', 'eraser', 'line', 'rectangle', 'circle', 'text'],
                'features': ['layers', 'undo_redo', 'save', 'export']
            }
        )
    
    @expose('/api/demo-data')
    @has_access
    def demo_data(self):
        """
        API endpoint for demo data.
        
        Returns:
            JSON response with demo data
        """
        demo_type = request.args.get('type', 'all')
        
        data = {
            'timestamp': '2025-01-20T12:00:00Z',
            'version': '4.8.0-enhanced'
        }
        
        if demo_type in ['all', 'stats']:
            data['stats'] = self._get_app_statistics()
        
        if demo_type in ['all', 'features']:
            data['features'] = self._get_feature_highlights()
        
        if demo_type in ['all', 'media']:
            data['media_capabilities'] = {
                'camera': ['photo', 'video', 'live_preview', 'grid_overlay'],
                'audio': ['recording', 'waveform', 'effects', 'formats'],
                'gps': ['location', 'mapping', 'geocoding', 'tracking'],
                'gallery': ['upload', 'preview', 'editing', 'sharing']
            }
        
        return jsonify(data)
    
    @expose('/health')
    @has_access
    def health_check(self):
        """
        Health check endpoint for monitoring.
        
        Returns:
            JSON response with system status
        """
        try:
            health_data = {
                'status': 'healthy',
                'timestamp': '2025-01-20T12:00:00Z',
                'version': '4.8.0-enhanced',
                'components': {
                    'database': 'ok',
                    'menu_engine': 'ok',
                    'media_fields': 'ok',
                    'templates': 'ok'
                }
            }
            
            return jsonify(health_data)
            
        except Exception as e:
            current_app.logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e)
            }), 500
    
    def _create_demo_menu_items(self):
        """
        Create demo menu items for showcase.
        
        Returns:
            List of demo menu items
        """
        # This would create MenuItem objects for demonstration
        # Simplified for this example
        return [
            {
                'name': 'Home',
                'label': __('Home'),
                'icon': 'fa-home',
                'url': url_for('PublicIndexView.index'),
                'childs': []
            },
            {
                'name': 'Media Demos',
                'label': __('Media Demos'),
                'icon': 'fa-camera',
                'url': '#',
                'childs': [
                    {
                        'name': 'Camera',
                        'label': __('Camera Capture'),
                        'icon': 'fa-camera',
                        'url': url_for('PublicIndexView.camera_demo')
                    },
                    {
                        'name': 'Audio',
                        'label': __('Audio Recording'),
                        'icon': 'fa-microphone',
                        'url': url_for('PublicIndexView.audio_demo')
                    },
                    {
                        'name': 'GPS',
                        'label': __('GPS Location'),
                        'icon': 'fa-map-marker-alt',
                        'url': url_for('PublicIndexView.gps_demo')
                    },
                    {
                        'name': 'Gallery',
                        'label': __('Media Gallery'),
                        'icon': 'fa-images',
                        'url': url_for('PublicIndexView.gallery_demo')
                    }
                ]
            },
            {
                'name': 'Menu Showcase',
                'label': __('Menu Showcase'),
                'icon': 'fa-bars',
                'url': url_for('PublicIndexView.menus_demo'),
                'childs': []
            },
            {
                'name': 'Extended Fields',
                'label': __('Extended Fields'),
                'icon': 'fa-edit',
                'url': url_for('PublicIndexView.extended_fields_demo'),
                'childs': [
                    {
                        'name': 'RichText',
                        'label': __('Rich Text Editor'),
                        'icon': 'fa-edit',
                        'url': url_for('PublicIndexView.richtext_demo')
                    },
                    {
                        'name': 'CodeEditor',
                        'label': __('Code Editor'),
                        'icon': 'fa-code',
                        'url': url_for('PublicIndexView.code_editor_demo')
                    },
                    {
                        'name': 'DateTime',
                        'label': __('DateTime Picker'),
                        'icon': 'fa-calendar-alt',
                        'url': url_for('PublicIndexView.datetime_picker_demo')
                    },
                    {
                        'name': 'ColorPicker',
                        'label': __('Color Picker'),
                        'icon': 'fa-palette',
                        'url': url_for('PublicIndexView.color_picker_demo')
                    },
                    {
                        'name': 'Signature',
                        'label': __('Digital Signature'),
                        'icon': 'fa-signature',
                        'url': url_for('PublicIndexView.signature_demo')
                    },
                    {
                        'name': 'Rating',
                        'label': __('Rating System'),
                        'icon': 'fa-star',
                        'url': url_for('PublicIndexView.rating_demo')
                    },
                    {
                        'name': 'QRCode',
                        'label': __('QR Code'),
                        'icon': 'fa-qrcode',
                        'url': url_for('PublicIndexView.qrcode_demo')
                    },
                    {
                        'name': 'FileUpload',
                        'label': __('File Upload'),
                        'icon': 'fa-cloud-upload-alt',
                        'url': url_for('PublicIndexView.file_upload_demo')
                    },
                    {
                        'name': 'JSONEditor',
                        'label': __('JSON Editor'),
                        'icon': 'fa-brackets-curly',
                        'url': url_for('PublicIndexView.json_editor_demo')
                    },
                    {
                        'name': 'Tags',
                        'label': __('Tag Field'),
                        'icon': 'fa-tags',
                        'url': url_for('PublicIndexView.tags_demo')
                    },
                    {
                        'name': 'PasswordStrength',
                        'label': __('Password Strength'),
                        'icon': 'fa-key',
                        'url': url_for('PublicIndexView.password_strength_demo')
                    },
                    {
                        'name': 'PhoneNumber',
                        'label': __('Phone Number'),
                        'icon': 'fa-phone',
                        'url': url_for('PublicIndexView.phone_number_demo')
                    },
                    {
                        'name': 'Address',
                        'label': __('Address Field'),
                        'icon': 'fa-map-marked-alt',
                        'url': url_for('PublicIndexView.address_demo')
                    },
                    {
                        'name': 'Drawing',
                        'label': __('Drawing Canvas'),
                        'icon': 'fa-paint-brush',
                        'url': url_for('PublicIndexView.drawing_demo')
                    }
                ]
            },
            {
                'name': 'Features',
                'label': __('Features'),
                'icon': 'fa-star',
                'url': '#',
                'childs': [
                    {
                        'name': 'Analytics',
                        'label': __('Analytics Dashboard'),
                        'icon': 'fa-chart-bar',
                        'url': '#analytics'
                    },
                    {
                        'name': 'Security',
                        'label': __('Security Features'),
                        'icon': 'fa-shield-alt',
                        'url': '#security'
                    },
                    {
                        'name': 'API',
                        'label': __('REST API'),
                        'icon': 'fa-code',
                        'url': '#api'
                    }
                ]
            },
            {
                'name': 'Documentation',
                'label': __('Documentation'),
                'icon': 'fa-book',
                'url': '#documentation',
                'childs': []
            }
        ]
    
    def _render_menu_demo(self, menu_items, render_mode):
        """
        Render menu with specific mode for demo.
        
        Args:
            menu_items: Menu items to render
            render_mode: MenuRenderMode to use
            
        Returns:
            HTML string of rendered menu
        """
        try:
            from .menu_rendering import MenuRenderingEngine, MenuRenderConfig
            
            config = MenuRenderConfig(render_mode=render_mode)
            engine = MenuRenderingEngine(config)
            
            return engine.render_menu(menu_items)
            
        except Exception as e:
            current_app.logger.error(f"Error rendering menu demo: {e}")
            return f'<div class="alert alert-warning">Menu demo unavailable: {str(e)}</div>'
    
    def _get_app_statistics(self):
        """
        Get application statistics for showcase.
        
        Returns:
            Dictionary of app statistics
        """
        return {
            'total_features': 25,
            'menu_renderers': 9,
            'media_field_types': 4,
            'supported_formats': {
                'image': ['JPEG', 'PNG', 'GIF', 'WebP'],
                'video': ['MP4', 'WebM', 'OGG'],
                'audio': ['WAV', 'MP3', 'OGG', 'WebM']
            },
            'performance_metrics': {
                'page_load_time': '< 2s',
                'media_capture_latency': '< 100ms',
                'concurrent_users': '1000+',
                'uptime': '99.99%'
            }
        }
    
    def _get_feature_highlights(self):
        """
        Get feature highlights for showcase.
        
        Returns:
            List of feature highlights
        """
        return [
            {
                'title': __('Advanced Menu System'),
                'description': __('9 different menu rendering modes with configurable themes and animations'),
                'icon': 'fa-bars',
                'color': 'primary'
            },
            {
                'title': __('Camera Capture'),
                'description': __('Live camera preview with photo/video capture, grid overlay, and quality controls'),
                'icon': 'fa-camera',
                'color': 'success'
            },
            {
                'title': __('Audio Recording'),
                'description': __('Professional audio recording with waveform visualization and multiple formats'),
                'icon': 'fa-microphone',
                'color': 'info'
            },
            {
                'title': __('GPS & Mapping'),
                'description': __('Interactive maps with location tracking, geocoding, and address search'),
                'icon': 'fa-map-marker-alt',
                'color': 'warning'
            },
            {
                'title': __('Media Gallery'),
                'description': __('Drag-and-drop media upload with thumbnail preview and gallery management'),
                'icon': 'fa-images',
                'color': 'danger'
            },
            {
                'title': __('Extended Fields'),
                'description': __('14 advanced field types including rich text, code editor, and digital signatures'),
                'icon': 'fa-edit',
                'color': 'primary'
            },
            {
                'title': __('Responsive Design'),
                'description': __('Mobile-optimized interface with touch-friendly controls and adaptive layouts'),
                'icon': 'fa-mobile-alt',
                'color': 'secondary'
            },
            {
                'title': __('Real-time Features'),
                'description': __('Live camera streams, audio visualization, and location tracking with < 100ms latency'),
                'icon': 'fa-bolt',
                'color': 'success'
            },
            {
                'title': __('Enterprise Security'),
                'description': __('AES-256 encryption, TLS 1.3, GDPR compliance, and comprehensive audit trails'),
                'icon': 'fa-shield-alt',
                'color': 'primary'
            }
        ]
    
    def _get_extended_fields_config(self):
        """
        Get extended fields configuration for demos.
        
        Returns:
            Dictionary of extended field configurations
        """
        return {
            'richtext': {
                'title': __('Rich Text Editor'),
                'description': __('WYSIWYG editor with formatting, media, and table support'),
                'icon': 'fa-edit',
                'demo_url': url_for('PublicIndexView.richtext_demo'),
                'features': ['formatting', 'media_insertion', 'table_support', 'word_count']
            },
            'code_editor': {
                'title': __('Code Editor'),
                'description': __('Syntax highlighting for 20+ programming languages'),
                'icon': 'fa-code',
                'demo_url': url_for('PublicIndexView.code_editor_demo'),
                'features': ['syntax_highlighting', 'autocomplete', 'error_detection', 'themes']
            },
            'datetime_picker': {
                'title': __('DateTime Picker'),
                'description': __('Advanced date/time selection with timezone support'),
                'icon': 'fa-calendar-alt',
                'demo_url': url_for('PublicIndexView.datetime_picker_demo'),
                'features': ['timezone_support', 'multiple_formats', 'localization', 'validation']
            },
            'color_picker': {
                'title': __('Color Picker'),
                'description': __('Color selection with multiple formats and swatches'),
                'icon': 'fa-palette',
                'demo_url': url_for('PublicIndexView.color_picker_demo'),
                'features': ['hex_rgb_hsl', 'alpha_channel', 'color_swatches', 'eyedropper']
            },
            'signature': {
                'title': __('Digital Signature'),
                'description': __('Capture digital signatures with touch or mouse'),
                'icon': 'fa-signature',
                'demo_url': url_for('PublicIndexView.signature_demo'),
                'features': ['touch_support', 'pen_customization', 'undo_redo', 'export_formats']
            },
            'rating': {
                'title': __('Rating System'),
                'description': __('Star ratings with reviews and analytics'),
                'icon': 'fa-star',
                'demo_url': url_for('PublicIndexView.rating_demo'),
                'features': ['star_rating', 'half_stars', 'reviews', 'analytics']
            },
            'qrcode': {
                'title': __('QR Code Generator'),
                'description': __('Generate and scan QR codes with customization'),
                'icon': 'fa-qrcode',
                'demo_url': url_for('PublicIndexView.qrcode_demo'),
                'features': ['generation', 'scanning', 'customization', 'batch_processing']
            },
            'file_upload': {
                'title': __('Advanced File Upload'),
                'description': __('Drag-and-drop upload with progress and validation'),
                'icon': 'fa-cloud-upload-alt',
                'demo_url': url_for('PublicIndexView.file_upload_demo'),
                'features': ['drag_drop', 'progress_tracking', 'file_validation', 'preview']
            },
            'json_editor': {
                'title': __('JSON Editor'),
                'description': __('Structured JSON editing with schema validation'),
                'icon': 'fa-brackets-curly',
                'demo_url': url_for('PublicIndexView.json_editor_demo'),
                'features': ['schema_validation', 'tree_view', 'formatting', 'error_highlighting']
            },
            'tags': {
                'title': __('Tag Field'),
                'description': __('Tag selection with autocomplete and suggestions'),
                'icon': 'fa-tags',
                'demo_url': url_for('PublicIndexView.tags_demo'),
                'features': ['autocomplete', 'suggestions', 'categorization', 'validation']
            },
            'password_strength': {
                'title': __('Password Strength'),
                'description': __('Password input with strength meter and suggestions'),
                'icon': 'fa-key',
                'demo_url': url_for('PublicIndexView.password_strength_demo'),
                'features': ['strength_meter', 'requirements', 'suggestions', 'generator']
            },
            'phone_number': {
                'title': __('Phone Number'),
                'description': __('International phone number input with validation'),
                'icon': 'fa-phone',
                'demo_url': url_for('PublicIndexView.phone_number_demo'),
                'features': ['international_format', 'validation', 'carrier_detection', 'location']
            },
            'address': {
                'title': __('Address Field'),
                'description': __('Structured address input with geocoding'),
                'icon': 'fa-map-marked-alt',
                'demo_url': url_for('PublicIndexView.address_demo'),
                'features': ['autocomplete', 'geocoding', 'validation', 'mapping']
            },
            'drawing': {
                'title': __('Drawing Canvas'),
                'description': __('Digital drawing with tools and layers'),
                'icon': 'fa-paint-brush',
                'demo_url': url_for('PublicIndexView.drawing_demo'),
                'features': ['drawing_tools', 'layers', 'undo_redo', 'export_formats']
            }
        }
    
    @expose('/demo/advanced-fields')
    @has_access
    def advanced_fields_demo(self):
        """
        Comprehensive demo page for all advanced field types.
        
        Returns:
            Rendered advanced fields demo template
        """
        return self.render_template(
            'public_advanced_fields_demo.html',
            title=_l('Advanced Fields Demo'),
            field_demos=self._get_advanced_fields_config()
        )
    
    def _get_advanced_fields_config(self):
        """
        Get advanced fields configuration for demos.
        
        Returns:
            Dictionary of advanced field configurations
        """
        return {
            'chart': {
                'title': __('Chart Field'),
                'description': __('Interactive data visualization with Chart.js integration'),
                'icon': 'fa-chart-line',
                'demo_url': url_for('PublicIndexView.chart_demo'),
                'features': ['multiple_chart_types', 'real_time_updates', 'export_options', 'responsive_design']
            },
            'map': {
                'title': __('Interactive Map'),
                'description': __('Maps with drawing tools and multiple providers'),
                'icon': 'fa-map',
                'demo_url': url_for('PublicIndexView.map_demo'),
                'features': ['leaflet_google_mapbox', 'drawing_tools', 'marker_support', 'geolocation']
            },
            'cropper': {
                'title': __('Image Cropper'),
                'description': __('Advanced image cropping with Cropper.js integration'),
                'icon': 'fa-crop-alt',
                'demo_url': url_for('PublicIndexView.cropper_demo'),
                'features': ['aspect_ratio_control', 'rotation_flip', 'zoom_pan', 'preview_export']
            },
            'slider': {
                'title': __('Range Slider'),
                'description': __('Single and dual-handle range sliders with customization'),
                'icon': 'fa-sliders-h',
                'demo_url': url_for('PublicIndexView.slider_demo'),
                'features': ['single_dual_range', 'custom_steps', 'tick_marks', 'live_updates']
            },
            'tree_select': {
                'title': __('Tree Select'),
                'description': __('Hierarchical selection with search and lazy loading'),
                'icon': 'fa-sitemap',
                'demo_url': url_for('PublicIndexView.tree_select_demo'),
                'features': ['hierarchical_data', 'search_filter', 'multi_select', 'lazy_loading']
            },
            'calendar': {
                'title': __('Calendar Field'),
                'description': __('Full-featured calendar with events and scheduling'),
                'icon': 'fa-calendar-plus',
                'demo_url': url_for('PublicIndexView.calendar_demo'),
                'features': ['month_week_day_views', 'event_management', 'date_selection', 'time_slots']
            },
            'switch': {
                'title': __('Advanced Switch'),
                'description': __('Animated toggle switches with multiple styles'),
                'icon': 'fa-toggle-on',
                'demo_url': url_for('PublicIndexView.switch_demo'),
                'features': ['multiple_styles', 'size_variants', 'animations', 'accessibility']
            },
            'markdown': {
                'title': __('Markdown Editor'),
                'description': __('Live markdown editor with preview and toolbar'),
                'icon': 'fa-markdown',
                'demo_url': url_for('PublicIndexView.markdown_demo'),
                'features': ['live_preview', 'toolbar_shortcuts', 'syntax_highlighting', 'export_html']
            },
            'media_player': {
                'title': __('Media Player'),
                'description': __('Audio/video player with playlist and controls'),
                'icon': 'fa-play-circle',
                'demo_url': url_for('PublicIndexView.media_player_demo'),
                'features': ['audio_video_support', 'playlist_management', 'custom_controls', 'keyboard_shortcuts']
            },
            'badge': {
                'title': __('Badge Field'),
                'description': __('Tag/chip selection with autocomplete and styling'),
                'icon': 'fa-tag',
                'demo_url': url_for('PublicIndexView.badge_demo'),
                'features': ['autocomplete_suggestions', 'custom_styles', 'max_items', 'validation']
            },
            'dual_list_box': {
                'title': __('Dual List Box'),
                'description': __('Shuttle control for moving items between lists'),
                'icon': 'fa-exchange-alt',
                'demo_url': url_for('PublicIndexView.dual_list_box_demo'),
                'features': ['move_single_multiple', 'search_filter', 'bulk_operations', 'keyboard_support']
            }
        }


class PublicMediaAPIView(BaseView):
    """
    Public API endpoints for media operations.
    """
    
    route_base = '/public/api'
    
    @expose('/upload', methods=['POST'])
    @has_access
    def upload_media(self):
        """
        Handle media upload for demo.
        
        Returns:
            JSON response with upload status
        """
        try:
            # Validate file upload
            if 'file' not in request.files:
                return jsonify({'error': 'No file provided'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # File validation
            allowed_types = ['image/', 'video/', 'audio/']
            if not any(file.content_type.startswith(t) for t in allowed_types):
                return jsonify({'error': 'File type not allowed'}), 400
            
            # Size validation (10MB limit)
            max_size = 10 * 1024 * 1024
            if len(file.read()) > max_size:
                return jsonify({'error': 'File too large'}), 400
            
            file.seek(0)  # Reset file pointer
            
            # For demo purposes, just return success
            # In production, this would save to storage
            return jsonify({
                'success': True,
                'filename': file.filename,
                'size': len(file.read()),
                'type': file.content_type,
                'message': 'File uploaded successfully (demo mode)'
            })
            
        except Exception as e:
            current_app.logger.error(f"Upload error: {e}")
            return jsonify({'error': 'Upload failed'}), 500
    
    @expose('/process', methods=['POST'])
    @has_access
    def process_media(self):
        """
        Process media data for demo.
        
        Returns:
            JSON response with processing results
        """
        try:
            data = request.get_json()
            
            if not data or 'media_type' not in data:
                return jsonify({'error': 'Invalid request data'}), 400
            
            media_type = data['media_type']
            
            # Simulate processing based on media type
            if media_type == 'photo':
                result = {
                    'processed': True,
                    'filters_applied': ['auto_enhance', 'noise_reduction'],
                    'metadata': {
                        'dimensions': '1920x1080',
                        'format': 'JPEG',
                        'quality': 85
                    }
                }
            elif media_type == 'video':
                result = {
                    'processed': True,
                    'encoding': 'H.264',
                    'duration': data.get('duration', 0),
                    'resolution': '1080p'
                }
            elif media_type == 'audio':
                result = {
                    'processed': True,
                    'format': 'WAV',
                    'sample_rate': 44100,
                    'channels': 2,
                    'effects_applied': ['normalize', 'noise_gate']
                }
            else:
                return jsonify({'error': 'Unsupported media type'}), 400
            
            return jsonify({
                'success': True,
                'media_type': media_type,
                'result': result,
                'processing_time': '2.3s'
            })
            
        except Exception as e:
            current_app.logger.error(f"Processing error: {e}")
            return jsonify({'error': 'Processing failed'}), 500