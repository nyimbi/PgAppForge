"""
Security Headers Middleware

Provides comprehensive security headers for PgForge applications.
Implements OWASP security header recommendations.
"""

from flask import Flask, request, current_app
from typing import Optional
import logging

log = logging.getLogger(__name__)


class SecurityHeaders:
    """Security headers middleware for Flask applications"""
    
    def __init__(self, app: Optional[Flask] = None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        """Initialize security headers for Flask app"""
        app.after_request(self._add_security_headers)
        
        # Configure secure session settings
        app.config.setdefault('SESSION_COOKIE_SECURE', True)
        app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)  
        app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
        
        # Add security configurations
        app.config.setdefault('SECURITY_HEADERS_FORCE_HTTPS', True)
        app.config.setdefault('SECURITY_HEADERS_HSTS_MAX_AGE', 31536000)  # 1 year
        app.config.setdefault('SECURITY_HEADERS_CSP_ENABLED', True)
        
        log.info("Security headers middleware initialized")
    
    def _add_security_headers(self, response):
        """Add security headers to all responses"""
        try:
            # Prevent MIME type sniffing
            response.headers['X-Content-Type-Options'] = 'nosniff'
            
            # Prevent clickjacking
            response.headers['X-Frame-Options'] = 'DENY'
            
            # XSS protection (legacy but still useful)
            response.headers['X-XSS-Protection'] = '1; mode=block'
            
            # Referrer policy
            response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            
            # HSTS header (only for HTTPS)
            if request.is_secure or current_app.config.get('SECURITY_HEADERS_FORCE_HTTPS'):
                max_age = current_app.config.get('SECURITY_HEADERS_HSTS_MAX_AGE', 31536000)
                response.headers['Strict-Transport-Security'] = f'max-age={max_age}; includeSubDomains'
            
            # Content Security Policy
            if current_app.config.get('SECURITY_HEADERS_CSP_ENABLED', True):
                csp = self._build_csp_header()
                response.headers['Content-Security-Policy'] = csp
            
            # Permissions Policy (Feature Policy successor)
            response.headers['Permissions-Policy'] = (
                "camera=(), microphone=(), geolocation=(), "
                "payment=(), usb=(), magnetometer=(), gyroscope=()"
            )
            
        except Exception as e:
            log.error(f"Error adding security headers: {e}")
        
        return response
    
    def _build_csp_header(self) -> str:
        """Build Content Security Policy header"""
        # Base CSP - restrictive but functional for PgForge
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # TODO: Remove unsafe-* in production
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "upgrade-insecure-requests"
        ]
        
        return '; '.join(csp_directives)


def init_security_headers(app: Flask):
    """Initialize security headers for Flask app"""
    return SecurityHeaders(app)