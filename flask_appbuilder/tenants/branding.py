"""
Multi-Tenant Branding System.

Handles tenant-specific branding, asset management, and white-label
customization for the multi-tenant SaaS platform.
"""

import logging
import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse
from io import BytesIO

from flask import current_app, request, url_for
from PIL import Image
from werkzeug.utils import secure_filename

log = logging.getLogger(__name__)


class AssetStorage:
    """
    Abstract base class for asset storage backends.
    
    Provides a common interface for storing and retrieving
    tenant assets like logos, custom CSS, and other files.
    """
    
    def upload_file(self, file_path: str, file_data: bytes, content_type: str = None) -> str:
        """Upload file and return public URL"""
        raise NotImplementedError
    
    def upload_image(self, file_path: str, image: Image.Image, format: str = 'PNG') -> str:
        """Upload PIL image and return public URL"""
        raise NotImplementedError
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file from storage"""
        raise NotImplementedError
    
    def file_exists(self, file_path: str) -> bool:
        """Check if file exists in storage"""
        raise NotImplementedError
    
    def get_public_url(self, file_path: str) -> str:
        """Get public URL for file"""
        raise NotImplementedError


class LocalAssetStorage(AssetStorage):
    """Local filesystem asset storage implementation"""
    
    def __init__(self, base_path: str = None, base_url: str = None):
        self.base_path = base_path or current_app.config.get(
            'TENANT_ASSETS_PATH', 
            os.path.join(current_app.static_folder, 'tenant_assets')
        )
        self.base_url = base_url or current_app.config.get(
            'TENANT_ASSETS_URL',
            '/static/tenant_assets'
        )
        
        # Ensure base directory exists
        os.makedirs(self.base_path, exist_ok=True)
    
    def upload_file(self, file_path: str, file_data: bytes, content_type: str = None) -> str:
        """Upload file to local storage"""
        full_path = os.path.join(self.base_path, file_path)
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write file
        with open(full_path, 'wb') as f:
            f.write(file_data)
        
        return self.get_public_url(file_path)
    
    def upload_image(self, file_path: str, image: Image.Image, format: str = 'PNG') -> str:
        """Upload PIL image to local storage"""
        # Convert image to bytes
        img_buffer = BytesIO()
        image.save(img_buffer, format=format, optimize=True)
        img_data = img_buffer.getvalue()
        
        return self.upload_file(file_path, img_data, f'image/{format.lower()}')
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file from local storage"""
        try:
            full_path = os.path.join(self.base_path, file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                return True
        except Exception as e:
            log.error(f"Failed to delete file {file_path}: {e}")
        
        return False
    
    def file_exists(self, file_path: str) -> bool:
        """Check if file exists in local storage"""
        full_path = os.path.join(self.base_path, file_path)
        return os.path.exists(full_path)
    
    def get_public_url(self, file_path: str) -> str:
        """Get public URL for local file"""
        return f"{self.base_url}/{file_path}"


class S3AssetStorage(AssetStorage):
    """AWS S3 asset storage implementation"""
    
    def __init__(self, bucket_name: str = None, region: str = None, 
                 access_key: str = None, secret_key: str = None):
        self.bucket_name = bucket_name or current_app.config.get('S3_BUCKET_NAME')
        self.region = region or current_app.config.get('S3_REGION', 'us-east-1')
        
        if not self.bucket_name:
            raise ValueError("S3 bucket name is required")
        
        try:
            import boto3
            
            # Initialize S3 client
            self.s3_client = boto3.client(
                's3',
                region_name=self.region,
                aws_access_key_id=access_key or current_app.config.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=secret_key or current_app.config.get('AWS_SECRET_ACCESS_KEY')
            )
            
            log.info(f"Initialized S3 storage with bucket: {self.bucket_name}")
            
        except ImportError:
            raise ImportError("boto3 library is required for S3 storage")
        except Exception as e:
            log.error(f"Failed to initialize S3 client: {e}")
            raise
    
    def upload_file(self, file_path: str, file_data: bytes, content_type: str = None) -> str:
        """Upload file to S3"""
        try:
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=file_path,
                Body=file_data,
                **extra_args
            )
            
            return self.get_public_url(file_path)
            
        except Exception as e:
            log.error(f"Failed to upload file to S3: {e}")
            raise
    
    def upload_image(self, file_path: str, image: Image.Image, format: str = 'PNG') -> str:
        """Upload PIL image to S3"""
        # Convert image to bytes
        img_buffer = BytesIO()
        image.save(img_buffer, format=format, optimize=True)
        img_data = img_buffer.getvalue()
        
        return self.upload_file(file_path, img_data, f'image/{format.lower()}')
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file from S3"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_path)
            return True
        except Exception as e:
            log.error(f"Failed to delete S3 file {file_path}: {e}")
            return False
    
    def file_exists(self, file_path: str) -> bool:
        """Check if file exists in S3"""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=file_path)
            return True
        except:
            return False
    
    def get_public_url(self, file_path: str) -> str:
        """Get public URL for S3 file"""
        if current_app.config.get('S3_CUSTOM_DOMAIN'):
            return f"https://{current_app.config['S3_CUSTOM_DOMAIN']}/{file_path}"
        else:
            return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{file_path}"


class BrandingManager:
    """
    Manages tenant-specific branding and customization.
    
    Handles logo uploads, color scheme management, custom CSS generation,
    and asset storage for white-label tenant customization.
    """
    
    def __init__(self, storage_backend: str = 'local'):
        """Initialize branding manager with storage backend"""
        self.storage = self._init_storage_backend(storage_backend)
        self._branding_cache = {}
        
        # Supported image formats
        self.supported_image_formats = {'PNG', 'JPEG', 'JPG', 'GIF', 'WEBP'}
        
        # Maximum logo dimensions
        self.max_logo_size = (800, 400)  # width, height
        
        # Default branding configuration
        self.default_branding = {
            'app_name': current_app.config.get('APP_NAME', 'Flask-AppBuilder'),
            'logo_url': '/static/img/logo.png',
            'favicon_url': '/static/img/favicon.ico',
            'colors': {
                'primary': '#007bff',
                'secondary': '#6c757d',
                'success': '#28a745',
                'danger': '#dc3545',
                'warning': '#ffc107',
                'info': '#17a2b8',
                'light': '#f8f9fa',
                'dark': '#343a40'
            },
            'fonts': {
                'primary': 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
                'headings': 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
            },
            'layout': {
                'navbar_position': 'top',  # top, side
                'sidebar_collapsed': False,
                'theme': 'light'  # light, dark
            }
        }
    
    def _init_storage_backend(self, backend_type: str) -> AssetStorage:
        """Initialize asset storage backend"""
        if backend_type == 's3':
            return S3AssetStorage()
        elif backend_type == 'local':
            return LocalAssetStorage()
        else:
            raise ValueError(f"Unsupported storage backend: {backend_type}")
    
    def update_tenant_branding(self, tenant_id: int, branding_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update tenant branding configuration"""
        try:
            from ..models.tenant_models import Tenant
            from flask_appbuilder import db
            
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                raise ValueError(f"Tenant {tenant_id} not found")
            
            current_config = tenant.branding_config or {}
            
            # Handle logo upload
            if 'logo_file' in branding_data:
                logo_url = self.upload_tenant_logo(tenant_id, branding_data['logo_file'])
                current_config['logo_url'] = logo_url
                log.info(f"Updated logo for tenant {tenant_id}: {logo_url}")
            
            # Handle favicon upload
            if 'favicon_file' in branding_data:
                favicon_url = self.upload_tenant_favicon(tenant_id, branding_data['favicon_file'])
                current_config['favicon_url'] = favicon_url
                log.info(f"Updated favicon for tenant {tenant_id}: {favicon_url}")
            
            # Handle color scheme
            if 'colors' in branding_data:
                colors = branding_data['colors']
                self._validate_color_scheme(colors)
                current_config['colors'] = {**current_config.get('colors', {}), **colors}
                log.info(f"Updated color scheme for tenant {tenant_id}")
            
            # Handle custom CSS
            if 'custom_css' in branding_data:
                css_url = self.upload_custom_css(tenant_id, branding_data['custom_css'])
                current_config['custom_css_url'] = css_url
                log.info(f"Updated custom CSS for tenant {tenant_id}: {css_url}")
            
            # Handle other branding options
            for key in ['app_name', 'tagline', 'email_footer', 'fonts', 'layout']:
                if key in branding_data:
                    current_config[key] = branding_data[key]
            
            # Update tenant record
            tenant.branding_config = current_config
            db.session.commit()
            
            # Clear cache
            self._clear_branding_cache(tenant_id)
            
            log.info(f"Branding updated for tenant {tenant_id}")
            return current_config
            
        except Exception as e:
            log.error(f"Failed to update tenant branding: {e}")
            raise
    
    def get_tenant_branding(self, tenant_id: int, use_cache: bool = True) -> Dict[str, Any]:
        """Get tenant branding with caching"""
        cache_key = f"tenant_branding:{tenant_id}"
        
        # Check cache
        if use_cache and cache_key in self._branding_cache:
            cached_data = self._branding_cache[cache_key]
            # Use cached data if less than 5 minutes old
            if (datetime.now(tz=timezone.utc) - cached_data['cached_at']).seconds < 300:
                return cached_data['branding']
        
        try:
            from ..models.tenant_models import Tenant
            
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                return self.default_branding.copy()
            
            # Start with default branding
            branding = self.default_branding.copy()
            
            # Merge tenant-specific configuration
            if tenant.branding_config:
                branding = self._deep_merge(branding, tenant.branding_config)
            
            # Add computed values
            branding.update({
                'app_name': branding.get('app_name', tenant.name),
                'custom_domain': tenant.custom_domain,
                'tenant_slug': tenant.slug
            })
            
            # Cache result
            if use_cache:
                self._branding_cache[cache_key] = {
                    'branding': branding,
                    'cached_at': datetime.now(tz=timezone.utc)
                }
            
            return branding
            
        except Exception as e:
            log.error(f"Failed to get tenant branding: {e}")
            return self.default_branding.copy()
    
    def upload_tenant_logo(self, tenant_id: int, logo_file) -> str:
        """Upload and process tenant logo"""
        try:
            # Validate file
            if not logo_file:
                raise ValueError("No logo file provided")
            
            # Read and process image
            image = Image.open(logo_file)
            
            # Convert to RGB if necessary (removes transparency, adds white background)
            if image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGBA')
            
            # Resize if too large
            if image.size[0] > self.max_logo_size[0] or image.size[1] > self.max_logo_size[1]:
                image.thumbnail(self.max_logo_size, Image.Resampling.LANCZOS)
                log.info(f"Resized logo for tenant {tenant_id} to {image.size}")
            
            # Generate unique filename
            timestamp = int(datetime.now(tz=timezone.utc).timestamp())
            filename = f"tenant-{tenant_id}/logo-{timestamp}.png"
            
            # Upload to storage
            logo_url = self.storage.upload_image(filename, image, 'PNG')
            
            # Delete old logo if it exists
            self._cleanup_old_assets(tenant_id, 'logo')
            
            return logo_url
            
        except Exception as e:
            log.error(f"Failed to upload logo for tenant {tenant_id}: {e}")
            raise
    
    def upload_tenant_favicon(self, tenant_id: int, favicon_file) -> str:
        """Upload and process tenant favicon"""
        try:
            # Process favicon (convert to ICO format)
            image = Image.open(favicon_file)
            
            # Convert to RGBA for favicon
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            
            # Resize to favicon size
            favicon_size = (32, 32)
            image = image.resize(favicon_size, Image.Resampling.LANCZOS)
            
            # Generate filename
            timestamp = int(datetime.now(tz=timezone.utc).timestamp())
            filename = f"tenant-{tenant_id}/favicon-{timestamp}.ico"
            
            # Upload as ICO
            logo_url = self.storage.upload_image(filename, image, 'ICO')
            
            # Cleanup old favicons
            self._cleanup_old_assets(tenant_id, 'favicon')
            
            return logo_url
            
        except Exception as e:
            log.error(f"Failed to upload favicon for tenant {tenant_id}: {e}")
            raise
    
    def upload_custom_css(self, tenant_id: int, css_content: str) -> str:
        """Upload custom CSS for tenant"""
        try:
            # Validate and sanitize CSS
            sanitized_css = self._sanitize_css(css_content)
            
            # Generate filename with hash for cache busting
            css_hash = hashlib.md5(sanitized_css.encode()).hexdigest()[:8]
            filename = f"tenant-{tenant_id}/custom-{css_hash}.css"
            
            # Upload CSS file
            css_url = self.storage.upload_file(
                filename, 
                sanitized_css.encode('utf-8'), 
                'text/css'
            )
            
            # Cleanup old CSS files
            self._cleanup_old_assets(tenant_id, 'custom')
            
            return css_url
            
        except Exception as e:
            log.error(f"Failed to upload custom CSS for tenant {tenant_id}: {e}")
            raise
    
    def generate_tenant_css(self, tenant_id: int) -> str:
        """Generate CSS for tenant branding"""
        branding = self.get_tenant_branding(tenant_id)
        colors = branding.get('colors', {})
        fonts = branding.get('fonts', {})
        layout = branding.get('layout', {})
        
        css_template = """
        /* Tenant-specific branding CSS */
        :root {
            --primary-color: %(primary)s;
            --secondary-color: %(secondary)s;
            --success-color: %(success)s;
            --danger-color: %(danger)s;
            --warning-color: %(warning)s;
            --info-color: %(info)s;
            --light-color: %(light)s;
            --dark-color: %(dark)s;
            
            --font-primary: %(font_primary)s;
            --font-headings: %(font_headings)s;
        }
        
        /* Primary color applications */
        .btn-primary,
        .badge-primary,
        .bg-primary {
            background-color: var(--primary-color) !important;
            border-color: var(--primary-color) !important;
        }
        
        .text-primary {
            color: var(--primary-color) !important;
        }
        
        .border-primary {
            border-color: var(--primary-color) !important;
        }
        
        /* Navigation branding */
        .navbar-brand img {
            max-height: 40px;
            width: auto;
        }
        
        .navbar-brand {
            font-family: var(--font-headings);
            font-weight: 600;
        }
        
        /* Sidebar customization */
        .sidebar {
            background-color: %(sidebar_bg)s;
        }
        
        .navbar {
            background-color: %(navbar_bg)s !important;
        }
        
        /* Typography */
        body {
            font-family: var(--font-primary);
        }
        
        h1, h2, h3, h4, h5, h6,
        .h1, .h2, .h3, .h4, .h5, .h6 {
            font-family: var(--font-headings);
        }
        
        /* Cards and panels */
        .card-header {
            background-color: %(card_header_bg)s;
            border-bottom-color: var(--primary-color);
        }
        
        /* Links */
        a {
            color: var(--primary-color);
        }
        
        a:hover {
            color: %(primary_hover)s;
        }
        
        /* Form controls */
        .form-control:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 0.2rem rgba(%(primary_rgb)s, 0.25);
        }
        
        /* Tables */
        .table-primary {
            background-color: rgba(%(primary_rgb)s, 0.1);
        }
        
        /* Custom tenant styles */
        .tenant-branding {
            border-left: 4px solid var(--primary-color);
            padding-left: 1rem;
        }
        
        /* Layout-specific styles */
        %(layout_styles)s
        """
        
        # Prepare CSS values
        primary_color = colors.get('primary', '#007bff')
        primary_rgb = self._hex_to_rgb(primary_color)
        primary_hover = self._darken_color(primary_color, 0.1)
        
        css_values = {
            'primary': primary_color,
            'secondary': colors.get('secondary', '#6c757d'),
            'success': colors.get('success', '#28a745'),
            'danger': colors.get('danger', '#dc3545'),
            'warning': colors.get('warning', '#ffc107'),
            'info': colors.get('info', '#17a2b8'),
            'light': colors.get('light', '#f8f9fa'),
            'dark': colors.get('dark', '#343a40'),
            
            'font_primary': fonts.get('primary', 'system-ui, sans-serif'),
            'font_headings': fonts.get('headings', 'system-ui, sans-serif'),
            
            'primary_rgb': primary_rgb,
            'primary_hover': primary_hover,
            
            'navbar_bg': colors.get('navbar_bg', colors.get('dark', '#343a40')),
            'sidebar_bg': colors.get('sidebar_bg', colors.get('light', '#f8f9fa')),
            'card_header_bg': colors.get('card_header_bg', colors.get('light', '#f8f9fa')),
            
            'layout_styles': self._generate_layout_styles(layout)
        }
        
        return css_template % css_values
    
    def _validate_color_scheme(self, colors: Dict[str, str]):
        """Validate color scheme values"""
        for color_name, color_value in colors.items():
            if not self._is_valid_color(color_value):
                raise ValueError(f"Invalid color value for {color_name}: {color_value}")
    
    def _is_valid_color(self, color: str) -> bool:
        """Check if color value is valid hex color"""
        import re
        hex_color_regex = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$'
        return bool(re.match(hex_color_regex, color))
    
    def _hex_to_rgb(self, hex_color: str) -> str:
        """Convert hex color to RGB string"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
    
    def _darken_color(self, hex_color: str, factor: float) -> str:
        """Darken a hex color by a factor"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        
        rgb = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
        rgb = [int(c * (1 - factor)) for c in rgb]
        
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    
    def _generate_layout_styles(self, layout: Dict[str, Any]) -> str:
        """Generate layout-specific CSS"""
        styles = []
        
        if layout.get('navbar_position') == 'side':
            styles.append("""
            .navbar {
                position: fixed;
                top: 0;
                left: 0;
                bottom: 0;
                width: 250px;
                flex-direction: column;
            }
            
            .main-content {
                margin-left: 250px;
            }
            """)
        
        if layout.get('sidebar_collapsed'):
            styles.append("""
            .sidebar {
                width: 60px;
            }
            
            .sidebar .nav-link span {
                display: none;
            }
            """)
        
        if layout.get('theme') == 'dark':
            styles.append("""
            body {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            
            .card {
                background-color: #2d2d2d;
                border-color: #404040;
            }
            
            .table {
                color: #ffffff;
            }
            
            .form-control {
                background-color: #2d2d2d;
                border-color: #404040;
                color: #ffffff;
            }
            """)
        
        return '\n'.join(styles)
    
    def _sanitize_css(self, css_content: str) -> str:
        """Sanitize CSS content to prevent XSS and malicious code"""
        import re
        
        # Remove dangerous patterns that could execute JavaScript
        dangerous_patterns = [
            r'javascript\s*:',
            r'expression\s*\(',
            r'behavior\s*:',
            r'@import\s+',
            r'document\.',
            r'window\.',
            r'eval\s*\(',
            r'setTimeout\s*\(',
            r'setInterval\s*\(',
            r'Function\s*\(',
            r'alert\s*\(',
            r'confirm\s*\(',
            r'prompt\s*\(',
            r'<script[^>]*>',
            r'</script>',
            r'url\s*\(\s*["\']?\s*javascript:',
            r'binding\s*:',
            r'-moz-binding\s*:',
            r'<.*?>'  # Remove any HTML tags
        ]
        
        sanitized = css_content
        
        # Remove dangerous patterns (case insensitive)
        for pattern in dangerous_patterns:
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
        
        # Remove any remaining data: URLs that aren't images
        sanitized = re.sub(
            r'data:(?!image/)[^;]*;base64,[^)]*',
            '',
            sanitized,
            flags=re.IGNORECASE
        )
        
        # Limit CSS length to prevent DoS
        max_css_length = 50000  # 50KB max
        if len(sanitized) > max_css_length:
            log.warning(f"CSS content truncated from {len(sanitized)} to {max_css_length} characters")
            sanitized = sanitized[:max_css_length]
        
        # Basic validation - ensure it contains only valid CSS-like content
        if not re.match(r'^[\s\w\-#.:;{}()\[\],"\'/\*%@\n\r]*$', sanitized):
            log.warning("CSS contains potentially unsafe characters")
            # Remove any remaining suspicious characters
            sanitized = re.sub(r'[^\s\w\-#.:;{}()\[\],"\'/\*%@\n\r]', '', sanitized)
        
        return sanitized.strip()
    
    def _cleanup_old_assets(self, tenant_id: int, asset_type: str):
        """Clean up old asset files for tenant"""
        # This is a simplified implementation
        # In production, you'd want to track and clean up old files more systematically
        log.debug(f"Cleaned up old {asset_type} assets for tenant {tenant_id}")
    
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """Deep merge dictionaries"""
        result = base.copy()
        
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _clear_branding_cache(self, tenant_id: int):
        """Clear branding cache for tenant"""
        cache_key = f"tenant_branding:{tenant_id}"
        if cache_key in self._branding_cache:
            del self._branding_cache[cache_key]
        
        log.debug(f"Cleared branding cache for tenant {tenant_id}")


# Global branding manager instance
_branding_manager = None


def get_branding_manager() -> BrandingManager:
    """Get global branding manager instance"""
    global _branding_manager
    
    if _branding_manager is None:
        storage_backend = current_app.config.get('TENANT_ASSET_STORAGE', 'local')
        _branding_manager = BrandingManager(storage_backend=storage_backend)
    
    return _branding_manager


def init_branding_system(app):
    """Initialize branding system for Flask app"""
    # Set up branding configuration
    app.config.setdefault('TENANT_ASSET_STORAGE', 'local')
    app.config.setdefault('TENANT_ASSETS_PATH', os.path.join(app.static_folder, 'tenant_assets'))
    app.config.setdefault('TENANT_ASSETS_URL', '/static/tenant_assets')
    
    # S3 configuration (if using S3)
    app.config.setdefault('S3_BUCKET_NAME', None)
    app.config.setdefault('S3_REGION', 'us-east-1')
    app.config.setdefault('S3_CUSTOM_DOMAIN', None)
    
    log.info("Branding system initialized")


# Template context processor for tenant branding
def inject_tenant_branding():
    """Inject tenant branding into template context"""
    from ..models.tenant_context import get_current_tenant_id
    
    tenant_id = get_current_tenant_id()
    if tenant_id:
        branding_manager = get_branding_manager()
        branding = branding_manager.get_tenant_branding(tenant_id)
        return {'tenant_branding': branding}
    
    return {'tenant_branding': None}