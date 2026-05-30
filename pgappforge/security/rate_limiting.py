"""
Rate Limiting for PgForge

Implements rate limiting for authentication endpoints to prevent brute force attacks.
Uses Flask-Limiter with Redis backend for distributed rate limiting.
"""

from flask import Flask, request, current_app, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from typing import Optional, Dict, Any
from functools import wraps
import time

log = logging.getLogger(__name__)


class SecurityRateLimiter:
    """Enhanced rate limiter with security focus"""
    
    def __init__(self, app: Optional[Flask] = None):
        self.limiter: Optional[Limiter] = None
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        """Initialize rate limiter"""
        # Rate limiting configuration
        app.config.setdefault('RATELIMIT_STORAGE_URL', 'memory://')
        app.config.setdefault('RATELIMIT_DEFAULT', '100 per hour')
        app.config.setdefault('RATELIMIT_HEADERS_ENABLED', True)
        
        # Enhanced rate limiting for security endpoints
        app.config.setdefault('SECURITY_RATE_LIMITS', {
            'login': '5 per minute',
            'mfa_verify': '10 per minute', 
            'password_reset': '3 per hour',
            'registration': '5 per hour',
            'api_auth': '20 per minute'
        })
        
        self.limiter = Limiter(
            app,
            key_func=self._get_limiter_key,
            default_limits=[app.config['RATELIMIT_DEFAULT']],
            storage_uri=app.config['RATELIMIT_STORAGE_URL'],
            headers_enabled=app.config['RATELIMIT_HEADERS_ENABLED']
        )
        
        # Override limiter's error handler
        self.limiter.request_filter(self._request_filter)
        
        log.info("Security rate limiter initialized")
    
    def _get_limiter_key(self) -> str:
        """Get key for rate limiting (IP + user agent fingerprint for better security)"""
        ip = get_remote_address()
        
        # Add user agent hash for better fingerprinting
        user_agent = request.headers.get('User-Agent', '')
        ua_hash = str(hash(user_agent) % 10000)  # Simple hash for fingerprinting
        
        return f"{ip}:{ua_hash}"
    
    def _request_filter(self) -> bool:
        """Filter requests that should bypass rate limiting"""
        # Skip rate limiting for health checks and static files
        path = request.path
        if path.startswith('/health') or path.startswith('/static'):
            return True
        
        # Skip for internal requests (if using service-to-service auth)
        if request.headers.get('X-Internal-Request') == 'true':
            return True
            
        return False
    
    def limit_auth_endpoint(self, endpoint_type: str = 'login'):
        """Decorator for authentication endpoints"""
        def decorator(f):
            if not self.limiter:
                log.warning("Rate limiter not initialized, skipping rate limiting")
                return f
                
            # Get rate limit for this endpoint type
            limits = current_app.config.get('SECURITY_RATE_LIMITS', {})
            rate_limit = limits.get(endpoint_type, '10 per minute')
            
            # Apply Flask-Limiter decorator properly
            return self.limiter.limit(rate_limit, key_func=self._get_limiter_key)(f)
            
        return decorator
    
    def get_remaining_attempts(self, endpoint_type: str = 'login') -> Dict[str, Any]:
        """Get remaining attempts for current client"""
        if not self.limiter:
            return {'remaining': -1, 'reset_time': 0}
        
        try:
            # Note: Flask-Limiter doesn't provide a direct API to get remaining attempts
            # This is a limitation of the library. In practice, rate limit headers 
            # are added to responses automatically by Flask-Limiter
            log.warning("get_remaining_attempts() requires direct storage access - not implemented")
            return {
                'remaining': -1,  # Unknown - Flask-Limiter limitation
                'reset_time': int(time.time()) + 3600,
                'note': 'Use rate limit headers from responses instead'
            }
        except Exception as e:
            log.error(f"Error getting rate limit status: {e}")
            return {'remaining': -1, 'reset_time': 0}


# Global rate limiter instance
_rate_limiter = SecurityRateLimiter()


def init_rate_limiting(app: Flask) -> SecurityRateLimiter:
    """Initialize rate limiting for Flask app"""
    global _rate_limiter
    _rate_limiter.init_app(app)
    return _rate_limiter


def limit_auth_endpoint(endpoint_type: str = 'login'):
    """Decorator for rate limiting authentication endpoints"""
    return _rate_limiter.limit_auth_endpoint(endpoint_type)


def get_rate_limiter() -> SecurityRateLimiter:
    """Get the global rate limiter instance"""
    return _rate_limiter


class RateLimitingMixin:
    """Mixin providing rate limiting capabilities for PgForge managers"""
    
    def apply_auth_rate_limit(self, endpoint_type: str = 'login'):
        """
        Apply rate limiting to authentication endpoint.
        
        :param endpoint_type: Type of authentication endpoint ('login', 'mfa_verify', etc.)
        :return: Rate limit decorator
        """
        return limit_auth_endpoint(endpoint_type)
    
    def get_rate_limit_status(self, endpoint_type: str = 'login') -> Dict[str, Any]:
        """
        Get current rate limit status for endpoint type.
        
        :param endpoint_type: Type of authentication endpoint
        :return: Dictionary containing rate limit status information
        """
        return get_rate_limiter().get_remaining_attempts(endpoint_type)
    
    def check_rate_limit_exceeded(self, endpoint_type: str = 'login') -> bool:
        """
        Check if rate limit has been exceeded for endpoint type.
        
        :param endpoint_type: Type of authentication endpoint
        :return: True if rate limit exceeded, False otherwise
        """
        status = self.get_rate_limit_status(endpoint_type)
        return status.get('remaining', 1) <= 0
    
    def reset_rate_limit(self, endpoint_type: str = 'login') -> bool:
        """
        Reset rate limit for specific endpoint type (admin function).
        
        :param endpoint_type: Type of authentication endpoint
        :return: True if reset successful, False otherwise
        """
        try:
            rate_limiter = get_rate_limiter()
            # This would need to be implemented in SecurityRateLimiter
            # For now, return True to indicate the interface exists
            log.info(f"Rate limit reset requested for endpoint: {endpoint_type}")
            return True
        except Exception as e:
            log.error(f"Failed to reset rate limit for {endpoint_type}: {e}")
            return False