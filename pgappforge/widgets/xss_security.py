"""
XSS Security utilities for PgForge widgets.

Provides comprehensive protection against Cross-Site Scripting (XSS) attacks
in widget rendering, template generation, and user input handling.
"""

import html
import re
import logging
from typing import Any, Dict, Union, Optional, List
from markupsafe import Markup, escape
from flask import current_app
import bleach

logger = logging.getLogger(__name__)


class XSSProtection:
    """Comprehensive XSS protection utilities for PgForge widgets."""

    # Allowed HTML tags for rich content (very restrictive by default)
    ALLOWED_TAGS = {
        'b', 'i', 'em', 'strong', 'u', 'br', 'p', 'span', 'div',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
        'a', 'img', 'table', 'thead', 'tbody', 'tr', 'td', 'th'
    }

    # Allowed HTML attributes (very restrictive)
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title', 'class', 'id'],
        'img': ['src', 'alt', 'title', 'class', 'id', 'width', 'height'],
        'span': ['class', 'id', 'title'],
        'div': ['class', 'id', 'title'],
        'p': ['class', 'id'],
        'h1': ['class', 'id'],
        'h2': ['class', 'id'],
        'h3': ['class', 'id'],
        'h4': ['class', 'id'],
        'h5': ['class', 'id'],
        'h6': ['class', 'id'],
        'table': ['class', 'id'],
        'td': ['class', 'id', 'colspan', 'rowspan'],
        'th': ['class', 'id', 'colspan', 'rowspan']
    }

    # URL protocols that are allowed
    ALLOWED_PROTOCOLS = ['http', 'https', 'mailto', 'tel']

    @staticmethod
    def escape_html(value: Any) -> str:
        """
        Escape HTML characters to prevent XSS.

        Args:
            value: The value to escape

        Returns:
            HTML-escaped string
        """
        if value is None:
            return ""

        if isinstance(value, Markup):
            # Already marked as safe, but re-escape for security
            return escape(str(value))

        return escape(str(value))

    @staticmethod
    def escape_json_string(value: Any) -> str:
        """
        Escape string for safe inclusion in JSON responses.

        Args:
            value: The value to escape

        Returns:
            JSON-safe escaped string
        """
        if value is None:
            return ""

        # Convert to string and escape HTML first
        escaped = html.escape(str(value), quote=True)

        # Additional JSON escaping
        escaped = escaped.replace('\\', '\\\\')
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace('\n', '\\n')
        escaped = escaped.replace('\r', '\\r')
        escaped = escaped.replace('\t', '\\t')

        return escaped

    @staticmethod
    def escape_javascript_string(value: Any) -> str:
        """
        Escape string for safe inclusion in JavaScript code.

        Args:
            value: The value to escape

        Returns:
            JavaScript-safe escaped string
        """
        if value is None:
            return ""

        # First escape HTML
        escaped = html.escape(str(value), quote=True)

        # JavaScript-specific escaping
        escaped = escaped.replace('\\', '\\\\')
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace('\n', '\\n')
        escaped = escaped.replace('\r', '\\r')
        escaped = escaped.replace('\t', '\\t')
        escaped = escaped.replace('\b', '\\b')
        escaped = escaped.replace('\f', '\\f')
        escaped = escaped.replace('\v', '\\v')
        escaped = escaped.replace('\0', '\\0')

        # Escape potential script tags
        escaped = escaped.replace('</', '<\\/')
        escaped = escaped.replace('<script', '<\\script')
        escaped = escaped.replace('</script', '<\\/script')

        return escaped

    @staticmethod
    def sanitize_html(content: str, allowed_tags: Optional[set] = None,
                     allowed_attributes: Optional[Dict[str, List[str]]] = None) -> str:
        """
        Sanitize HTML content using bleach library.

        Args:
            content: HTML content to sanitize
            allowed_tags: Set of allowed HTML tags
            allowed_attributes: Dict of allowed attributes per tag

        Returns:
            Sanitized HTML content
        """
        if not content:
            return ""

        # Use defaults if not provided
        tags = allowed_tags or XSSProtection.ALLOWED_TAGS
        attributes = allowed_attributes or XSSProtection.ALLOWED_ATTRIBUTES

        try:
            # Sanitize HTML content
            cleaned = bleach.clean(
                content,
                tags=tags,
                attributes=attributes,
                protocols=XSSProtection.ALLOWED_PROTOCOLS,
                strip=True,  # Strip disallowed tags instead of escaping
                strip_comments=True
            )

            # Additional URL validation for href and src attributes
            cleaned = XSSProtection._validate_urls(cleaned)

            return cleaned

        except Exception as e:
            logger.warning(f"HTML sanitization failed: {e}")
            # Fallback to basic HTML escaping
            return html.escape(content, quote=True)

    @staticmethod
    def _validate_urls(html_content: str) -> str:
        """Validate and sanitize URLs in HTML content."""
        # Pattern to find href and src attributes
        url_pattern = re.compile(r'(href|src)=["\']([^"\']*)["\']', re.IGNORECASE)

        def validate_url(match):
            attr_name = match.group(1)
            url = match.group(2)

            # Check for dangerous protocols
            if re.match(r'^(javascript|data|vbscript|file):', url, re.IGNORECASE):
                logger.warning(f"Blocked dangerous URL protocol in {attr_name}: {url}")
                return f'{attr_name}="#blocked-url"'

            # Allow relative URLs and safe protocols
            if url.startswith(('http://', 'https://', 'mailto:', 'tel:', '/', '#')):
                return match.group(0)
            elif not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', url):
                # Relative URL, allow it
                return match.group(0)
            else:
                # Unknown protocol, block it
                logger.warning(f"Blocked unknown URL protocol in {attr_name}: {url}")
                return f'{attr_name}="#blocked-url"'

        return url_pattern.sub(validate_url, html_content)

    @staticmethod
    def safe_format(template: str, **kwargs) -> str:
        """
        Safely format a string template with HTML escaping.

        Args:
            template: String template
            **kwargs: Values to substitute

        Returns:
            Safely formatted string
        """
        # Escape all values before formatting
        safe_kwargs = {
            key: XSSProtection.escape_html(value)
            for key, value in kwargs.items()
        }

        try:
            return template.format(**safe_kwargs)
        except (KeyError, ValueError) as e:
            logger.error(f"Safe format failed: {e}")
            # Return escaped template without substitution
            return XSSProtection.escape_html(template)

    @staticmethod
    def create_safe_html(tag: str, content: str = "", attributes: Optional[Dict[str, str]] = None) -> Markup:
        """
        Create safe HTML with proper escaping.

        Args:
            tag: HTML tag name
            content: Inner content
            attributes: HTML attributes

        Returns:
            Safe HTML markup
        """
        # Validate tag name
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', tag):
            raise ValueError(f"Invalid HTML tag name: {tag}")

        # Escape content
        safe_content = XSSProtection.escape_html(content)

        # Build attributes string
        attrs_str = ""
        if attributes:
            safe_attrs = []
            for key, value in attributes.items():
                # Validate attribute name
                if not re.match(r'^[a-zA-Z][a-zA-Z0-9-]*$', key):
                    continue

                # Escape attribute value
                safe_value = XSSProtection.escape_html(value)
                safe_attrs.append(f'{key}="{safe_value}"')

            if safe_attrs:
                attrs_str = " " + " ".join(safe_attrs)

        # Create safe HTML
        if content:
            html_str = f"<{tag}{attrs_str}>{safe_content}</{tag}>"
        else:
            html_str = f"<{tag}{attrs_str}/>"

        return Markup(html_str)

    @staticmethod
    def get_csp_header() -> str:
        """
        Generate Content Security Policy header for XSS protection.

        Returns:
            CSP header value
        """
        # Base CSP policy - very restrictive
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # May need adjustment
            "style-src 'self' 'unsafe-inline'",  # Bootstrap/CSS frameworks need inline styles
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "media-src 'self'",
            "object-src 'none'",
            "child-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'"
        ]

        return "; ".join(csp_directives)


def apply_csp_headers(response):
    """
    Apply Content Security Policy headers to response.

    Args:
        response: Flask response object

    Returns:
        Response with CSP headers applied
    """
    if current_app.config.get('ENABLE_CSP_HEADERS', True):
        response.headers['Content-Security-Policy'] = XSSProtection.get_csp_header()
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    return response


# Template filters for Jinja2
def init_xss_filters(app):
    """Initialize XSS protection filters for Jinja2 templates."""

    @app.template_filter('xss_escape')
    def xss_escape_filter(value):
        """Filter to escape XSS characters in templates."""
        return XSSProtection.escape_html(value)

    @app.template_filter('xss_sanitize')
    def xss_sanitize_filter(value):
        """Filter to sanitize HTML content in templates."""
        return Markup(XSSProtection.sanitize_html(str(value)))

    @app.template_filter('js_escape')
    def js_escape_filter(value):
        """Filter to escape JavaScript strings in templates."""
        return XSSProtection.escape_javascript_string(value)

    @app.template_filter('json_escape')
    def json_escape_filter(value):
        """Filter to escape JSON strings in templates."""
        return XSSProtection.escape_json_string(value)


# Decorator for views
def xss_protected(f):
    """Decorator to add XSS protection headers to view responses."""
    def wrapper(*args, **kwargs):
        response = f(*args, **kwargs)
        return apply_csp_headers(response)

    wrapper.__name__ = f.__name__
    wrapper.__doc__ = f.__doc__
    return wrapper