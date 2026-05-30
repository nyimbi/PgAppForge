"""
PgAppForge Enhanced Configuration Example

Comprehensive configuration options for:
- Menu rendering system with 9+ different styles
- Media field capabilities (camera, audio, GPS, gallery)
- Security and performance settings
- Public IndexView customization
- Integration settings for external services
"""

import os
from datetime import timedelta


class Config:
    """Base configuration class with enhanced features."""
    
    # =======================================================================
    # CORE FLASK-APPBUILDER SETTINGS
    # =======================================================================
    
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'connect_args': {'check_same_thread': False} if 'sqlite' in SQLALCHEMY_DATABASE_URI else {}
    }
    
    # Application
    APP_NAME = "PgAppForge Enhanced"
    APP_THEME = "cerulean"  # or custom theme
    APP_ICON = "/static/img/logo.png"
    
    # =======================================================================
    # ENHANCED MENU RENDERING CONFIGURATION
    # =======================================================================
    
    # Menu Rendering Settings
    MENU_RENDER_MODE = 'navbar'  # navbar, tree, sidebar, breadcrumb, mega_menu, tabs, context_menu, floating_action, accordion, horizontal_scroll
    MENU_POSITION = 'top'        # top, left, right
    MENU_COLLAPSIBLE = True
    MENU_THEME = 'light'         # light, dark, custom
    MENU_MAX_DEPTH = 3
    MENU_SHOW_ICONS = True
    MENU_SHOW_BADGES = True
    MENU_ANIMATION_DURATION = 300  # milliseconds
    MENU_AUTO_COLLAPSE = False
    MENU_COMPACT_MODE = False
    
    # Menu Theme Customization
    MENU_CUSTOM_CSS = {
        'navbar': {
            'background_color': '#007bff',
            'text_color': '#ffffff',
            'hover_color': '#0056b3',
            'border_radius': '8px'
        },
        'sidebar': {
            'width': '280px',
            'background_color': '#f8f9fa',
            'border_color': '#dee2e6'
        },
        'tree': {
            'indent_size': '20px',
            'expand_icon': 'fa-chevron-right',
            'collapse_icon': 'fa-chevron-down'
        }
    }
    
    # =======================================================================
    # MEDIA FIELD CONFIGURATION
    # =======================================================================
    
    # Camera Field Settings
    CAMERA_FIELD_CONFIG = {
        'default_mode': 'photo',        # photo, video, both
        'default_resolution': '1280x720',
        'default_quality': 0.8,
        'max_file_size': 50 * 1024 * 1024,  # 50MB
        'supported_formats': {
            'photo': ['image/jpeg', 'image/png', 'image/webp'],
            'video': ['video/mp4', 'video/webm', 'video/ogg']
        },
        'enable_grid_overlay': True,
        'enable_timer': True,
        'enable_flash': True,
        'capture_timeout': 30,  # seconds
        'preview_timeout': 10   # seconds
    }
    
    # Audio Recording Field Settings
    AUDIO_FIELD_CONFIG = {
        'default_format': 'audio/wav',
        'default_quality': 44100,       # sample rate
        'max_duration': 300,            # seconds
        'max_file_size': 20 * 1024 * 1024,  # 20MB
        'supported_formats': ['audio/wav', 'audio/mp3', 'audio/ogg', 'audio/webm'],
        'enable_noise_reduction': True,
        'enable_echo_cancellation': True,
        'enable_waveform': True,
        'enable_real_time_effects': True,
        'channels': 2,                  # stereo
        'bit_depth': 16
    }
    
    # GPS Field Settings
    GPS_FIELD_CONFIG = {
        'default_provider': 'leaflet',  # leaflet, google, mapbox
        'default_zoom': 15,
        'enable_tracking': True,
        'enable_geocoding': True,
        'enable_weather': False,
        'tracking_accuracy': 'high',    # high, medium, low
        'cache_location': True,
        'location_timeout': 10,         # seconds
        'max_age': 60,                  # seconds
        'google_maps_api_key': os.environ.get('GOOGLE_MAPS_API_KEY'),
        'mapbox_access_token': os.environ.get('MAPBOX_ACCESS_TOKEN')
    }
    
    # Media Gallery Field Settings
    GALLERY_FIELD_CONFIG = {
        'max_files': 20,
        'max_total_size': 100 * 1024 * 1024,  # 100MB
        'supported_types': [
            'image/jpeg', 'image/png', 'image/gif', 'image/webp',
            'video/mp4', 'video/webm', 'video/ogg',
            'audio/wav', 'audio/mp3', 'audio/ogg', 'audio/webm'
        ],
        'thumbnail_size': (150, 150),
        'enable_drag_drop': True,
        'enable_preview': True,
        'enable_editing': True,
        'enable_sharing': True,
        'auto_generate_thumbnails': True,
        'compress_uploads': True,
        'compression_quality': 0.85
    }
    
    # =======================================================================
    # MEDIA STORAGE CONFIGURATION
    # =======================================================================
    
    # Storage Settings
    MEDIA_STORAGE_PATH = os.path.join(os.path.dirname(__file__), 'media')
    MEDIA_URL_PREFIX = '/media'
    MEDIA_SERVE_LOCALLY = True  # Set to False for cloud storage
    
    # Cloud Storage (Optional)
    CLOUD_STORAGE_CONFIG = {
        'provider': 'aws',  # aws, azure, gcp
        'aws': {
            'bucket_name': os.environ.get('AWS_S3_BUCKET'),
            'region': os.environ.get('AWS_REGION', 'us-east-1'),
            'access_key': os.environ.get('AWS_ACCESS_KEY_ID'),
            'secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'endpoint_url': os.environ.get('AWS_S3_ENDPOINT_URL')  # For MinIO
        },
        'azure': {
            'account_name': os.environ.get('AZURE_STORAGE_ACCOUNT'),
            'account_key': os.environ.get('AZURE_STORAGE_KEY'),
            'container_name': os.environ.get('AZURE_CONTAINER_NAME')
        },
        'gcp': {
            'bucket_name': os.environ.get('GCP_STORAGE_BUCKET'),
            'credentials_path': os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        }
    }
    
    # =======================================================================
    # PUBLIC INDEX VIEW CONFIGURATION
    # =======================================================================
    
    # Public Index Settings
    PUBLIC_INDEX_CONFIG = {
        'enable_public_access': True,
        'show_demo_features': True,
        'enable_interactive_demos': True,
        'show_performance_metrics': True,
        'enable_api_examples': True,
        'custom_branding': {
            'title': 'PgAppForge Enhanced',
            'subtitle': 'Revolutionary web application framework',
            'logo_url': '/static/img/logo.png',
            'favicon_url': '/static/img/favicon.ico',
            'primary_color': '#007bff',
            'secondary_color': '#6c757d'
        },
        'contact_info': {
            'email': 'contact@example.com',
            'website': 'https://flask-appbuilder-enhanced.com',
            'github': 'https://github.com/your-org/flask-appbuilder-enhanced',
            'documentation': 'https://docs.flask-appbuilder-enhanced.com'
        }
    }
    
    # =======================================================================
    # SECURITY AND PERFORMANCE SETTINGS
    # =======================================================================
    
    # Security
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = "100 per hour"
    RATELIMIT_STORAGE_URL = "redis://localhost:6379/0"
    
    # Media Upload Security
    MEDIA_UPLOAD_SECURITY = {
        'scan_for_malware': True,
        'check_file_headers': True,
        'validate_mime_types': True,
        'quarantine_suspicious': True,
        'max_file_size_per_request': 100 * 1024 * 1024,  # 100MB
        'allowed_extensions': [
            '.jpg', '.jpeg', '.png', '.gif', '.webp',
            '.mp4', '.webm', '.ogv',
            '.wav', '.mp3', '.ogg', '.weba'
        ]
    }
    
    # Performance
    PERFORMANCE_CONFIG = {
        'enable_caching': True,
        'cache_type': 'redis',  # simple, redis, memcached
        'cache_redis_url': 'redis://localhost:6379/1',
        'cache_default_timeout': 300,
        'enable_compression': True,
        'compression_level': 6,
        'enable_minification': True,
        'enable_asset_bundling': True
    }
    
    # =======================================================================
    # INTEGRATION SETTINGS
    # =======================================================================
    
    # Email Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    
    # External API Integration
    EXTERNAL_APIS = {
        'weather': {
            'provider': 'openweathermap',
            'api_key': os.environ.get('OPENWEATHER_API_KEY'),
            'enable_caching': True,
            'cache_duration': 3600  # seconds
        },
        'geocoding': {
            'provider': 'nominatim',  # nominatim, google, mapbox
            'rate_limit': 1,  # requests per second
            'enable_caching': True,
            'cache_duration': 86400  # 24 hours
        },
        'analytics': {
            'google_analytics_id': os.environ.get('GOOGLE_ANALYTICS_ID'),
            'enable_user_tracking': False,  # GDPR compliance
            'track_media_interactions': True,
            'track_menu_usage': True
        }
    }
    
    # WebSocket Configuration (for real-time features)
    WEBSOCKET_CONFIG = {
        'enable_websockets': True,
        'redis_url': 'redis://localhost:6379/2',
        'max_connections': 1000,
        'heartbeat_interval': 30,
        'enable_real_time_collaboration': True,
        'enable_live_camera_sharing': False,  # Privacy consideration
        'enable_location_broadcasting': False  # Privacy consideration
    }
    
    # =======================================================================
    # LOGGING AND MONITORING
    # =======================================================================
    
    # Logging
    LOGGING_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
            },
            'detailed': {
                'format': '[%(asctime)s] %(levelname)s %(name)s %(funcName)s():%(lineno)d: %(message)s',
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'default',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'detailed',
                'filename': 'logs/app.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5
            }
        },
        'loggers': {
            'pgappforge': {
                'level': 'INFO',
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'media_fields': {
                'level': 'DEBUG',
                'handlers': ['console', 'file'],
                'propagate': False
            }
        }
    }
    
    # Monitoring
    MONITORING_CONFIG = {
        'enable_metrics': True,
        'metrics_endpoint': '/metrics',
        'health_check_endpoint': '/health',
        'enable_profiling': False,  # Enable in development only
        'track_performance': True,
        'alert_thresholds': {
            'response_time': 2.0,  # seconds
            'error_rate': 0.05,    # 5%
            'memory_usage': 0.8,   # 80%
            'disk_usage': 0.9      # 90%
        }
    }


class DevelopmentConfig(Config):
    """Development environment configuration."""
    
    DEBUG = True
    TESTING = False
    
    # Relaxed security for development
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    
    # Enable debugging features
    PERFORMANCE_CONFIG = Config.PERFORMANCE_CONFIG.copy()
    PERFORMANCE_CONFIG.update({
        'enable_caching': False,
        'enable_compression': False,
        'enable_minification': False
    })
    
    # Enable profiling
    MONITORING_CONFIG = Config.MONITORING_CONFIG.copy()
    MONITORING_CONFIG['enable_profiling'] = True
    
    # Development-friendly media settings
    CAMERA_FIELD_CONFIG = Config.CAMERA_FIELD_CONFIG.copy()
    CAMERA_FIELD_CONFIG['capture_timeout'] = 60
    
    AUDIO_FIELD_CONFIG = Config.AUDIO_FIELD_CONFIG.copy()
    AUDIO_FIELD_CONFIG['max_duration'] = 600


class ProductionConfig(Config):
    """Production environment configuration."""
    
    DEBUG = False
    TESTING = False
    
    # Production security settings
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_ENABLED = True
    RATELIMIT_ENABLED = True
    
    # Production performance settings
    PERFORMANCE_CONFIG = Config.PERFORMANCE_CONFIG.copy()
    PERFORMANCE_CONFIG.update({
        'enable_caching': True,
        'enable_compression': True,
        'enable_minification': True,
        'enable_asset_bundling': True
    })
    
    # Stricter media settings
    CAMERA_FIELD_CONFIG = Config.CAMERA_FIELD_CONFIG.copy()
    CAMERA_FIELD_CONFIG.update({
        'max_file_size': 25 * 1024 * 1024,  # 25MB
        'capture_timeout': 15
    })
    
    AUDIO_FIELD_CONFIG = Config.AUDIO_FIELD_CONFIG.copy()
    AUDIO_FIELD_CONFIG.update({
        'max_file_size': 10 * 1024 * 1024,  # 10MB
        'max_duration': 180
    })
    
    # Enable cloud storage
    MEDIA_SERVE_LOCALLY = False


class TestingConfig(Config):
    """Testing environment configuration."""
    
    TESTING = True
    DEBUG = False
    
    # Use in-memory database for testing
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
    # Disable external services
    RATELIMIT_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    WTF_CSRF_ENABLED = False
    
    # Fast settings for testing
    MENU_ANIMATION_DURATION = 0
    CAMERA_FIELD_CONFIG = Config.CAMERA_FIELD_CONFIG.copy()
    CAMERA_FIELD_CONFIG.update({
        'capture_timeout': 5,
        'preview_timeout': 2
    })


# Configuration selection
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Get configuration based on environment."""
    return config[os.environ.get('FLASK_ENV', 'default')]


# Example usage in your Flask app:
"""
from flask import Flask
from pgappforge import AppBuilder
from .config_example_enhanced import get_config

def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())
    
    # Initialize PgAppForge with enhanced features
    appbuilder = AppBuilder(app, update_perms=app.config.get('PGAF_UPDATE_PERMS', True))
    
    # Register enhanced views
    from .public_index_view import PublicIndexView, PublicMediaAPIView
    appbuilder.add_view_no_menu(PublicIndexView)
    appbuilder.add_view_no_menu(PublicMediaAPIView)
    
    return app
"""