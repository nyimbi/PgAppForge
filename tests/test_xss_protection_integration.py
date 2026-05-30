"""
Integration tests for XSS protection across PgAppForge widgets and templates.

Tests comprehensive XSS protection including:
- Widget rendering safety
- Template escaping
- JSON response protection
- CSP header application
"""

import pytest
from flask import Flask, render_template_string
from pgappforge import AppBuilder
from pgappforge.widgets.xss_security import XSSProtection, init_xss_filters, apply_csp_headers
from pgappforge.widgets.core import ApprovalWidget
from markupsafe import Markup
import json


class TestXSSProtectionIntegration:
    """Integration tests for XSS protection."""

    @pytest.fixture
    def app(self):
        """Create Flask app with XSS protection enabled."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        app.config['ENABLE_CSP_HEADERS'] = True

        # Initialize XSS filters
        init_xss_filters(app)

        return app

    @pytest.fixture
    def appbuilder(self, app):
        """Create AppBuilder instance."""
        return AppBuilder(app)

    def test_html_escaping_basic(self):
        """Test basic HTML escaping functionality."""
        # Test dangerous HTML
        dangerous_html = "<script>alert('xss')</script>"
        escaped = XSSProtection.escape_html(dangerous_html)

        assert "&lt;script&gt;" in escaped
        assert "alert(&#x27;xss&#x27;)" in escaped
        assert "<script>" not in escaped

    def test_json_string_escaping(self):
        """Test JSON string escaping for safe inclusion in responses."""
        dangerous_data = {
            "script": "<script>alert('xss')</script>",
            "quotes": 'He said "Hello" & \'goodbye\'',
            "newlines": "Line 1\nLine 2\r\nLine 3"
        }

        for key, value in dangerous_data.items():
            escaped = XSSProtection.escape_json_string(value)

            # Should not contain raw HTML
            assert "<script>" not in escaped
            assert "</script>" not in escaped

            # Should not contain unescaped quotes
            assert '\"' not in escaped.replace('\\"', '')

            # Should not contain raw newlines
            assert "\n" not in escaped.replace("\\n", "")

    def test_javascript_string_escaping(self):
        """Test JavaScript string escaping for safe inclusion in scripts."""
        dangerous_js = "'; alert('xss'); var x='"
        escaped = XSSProtection.escape_javascript_string(dangerous_js)

        assert "\\'" in escaped  # Single quotes escaped
        assert "alert(" not in escaped  # Should be escaped
        assert "</" not in escaped or "<\\/" in escaped  # Script tags escaped

    def test_html_sanitization(self):
        """Test HTML sanitization with allowed tags."""
        # Test with mixed safe and dangerous content
        mixed_html = """
        <p>Safe paragraph</p>
        <script>alert('dangerous')</script>
        <b>Bold text</b>
        <img src="javascript:alert('xss')" alt="test">
        <a href="https://safe.com">Safe link</a>
        <a href="javascript:alert('xss')">Dangerous link</a>
        """

        sanitized = XSSProtection.sanitize_html(mixed_html)

        # Safe content should remain
        assert "<p>Safe paragraph</p>" in sanitized
        assert "<b>Bold text</b>" in sanitized
        assert 'href="https://safe.com"' in sanitized

        # Dangerous content should be removed/neutralized
        assert "<script>" not in sanitized
        assert "javascript:" not in sanitized
        assert "alert(" not in sanitized

    def test_safe_html_creation(self):
        """Test safe HTML creation with proper escaping."""
        # Test creating safe HTML elements
        safe_html = XSSProtection.create_safe_html(
            'div',
            content="<script>alert('xss')</script>",
            attributes={
                'class': 'test-class',
                'data-value': '"dangerous"'
            }
        )

        html_str = str(safe_html)

        # Content should be escaped
        assert "&lt;script&gt;" in html_str
        assert "<script>" not in html_str

        # Attributes should be escaped
        assert 'data-value="&quot;dangerous&quot;"' in html_str
        assert 'class="test-class"' in html_str

    def test_template_xss_filters(self, app):
        """Test XSS protection filters in Jinja2 templates."""
        dangerous_content = "<script>alert('xss')</script>"

        with app.app_context():
            # Test xss_escape filter
            template = "{{ content | xss_escape }}"
            result = render_template_string(template, content=dangerous_content)
            assert "&lt;script&gt;" in result
            assert "<script>" not in result

            # Test js_escape filter
            template = "var data = '{{ content | js_escape }}';"
            result = render_template_string(template, content=dangerous_content)
            assert "alert(" not in result
            assert "\\u003c" in result or "&lt;" in result

            # Test json_escape filter
            template = '{"data": "{{ content | json_escape }}"}'
            result = render_template_string(template, content=dangerous_content)
            assert "<script>" not in result
            assert "&lt;" in result

    def test_approval_widget_xss_protection(self, app, appbuilder):
        """Test XSS protection in approval widget rendering."""
        with app.app_context():
            # Create approval widget
            widget = ApprovalWidget(approval_required=True)

            # Create mock object with XSS payload
            class MockObject:
                id = 1
                name = "<script>alert('xss')</script>"
                status = "pending_approval"

            # Test status badge generation
            badge_html = widget.get_approval_status_badge(MockObject())
            badge_str = str(badge_html)

            # Should not contain raw script tags
            assert "<script>" not in badge_str
            assert "alert(" not in badge_str

            # Should contain escaped content or safe HTML structure
            assert "Pending Approval" in badge_str
            assert "badge" in badge_str

    def test_csp_header_application(self, app):
        """Test Content Security Policy header application."""
        with app.test_client() as client:
            @app.route('/test')
            def test_route():
                return "Test content"

            # Test CSP headers are applied
            response = client.get('/test')
            response = apply_csp_headers(response)

            assert 'Content-Security-Policy' in response.headers
            assert 'X-Content-Type-Options' in response.headers
            assert 'X-Frame-Options' in response.headers
            assert 'X-XSS-Protection' in response.headers

            csp = response.headers['Content-Security-Policy']
            assert "default-src 'self'" in csp
            assert "object-src 'none'" in csp
            assert "frame-ancestors 'none'" in csp

    def test_widget_gallery_xss_protection(self):
        """Test XSS protection in widget gallery error responses."""
        from pgappforge.widgets.widget_gallery import UnifiedWidgetGalleryView

        # Simulate error with XSS payload
        error_message = "<script>alert('xss')</script>Invalid config"

        # Test error message escaping
        escaped_error = XSSProtection.escape_json_string(error_message)

        # Create JSON response format
        response_data = {
            'error': f'Code generation failed: {escaped_error}'
        }

        json_response = json.dumps(response_data)

        # Should not contain raw script tags in JSON
        assert "<script>" not in json_response
        assert "alert(" not in json_response
        assert "&lt;" in json_response or "\\u003c" in json_response

    def test_safe_format_function(self):
        """Test safe string formatting with XSS protection."""
        template = "Hello {name}, your role is {role}"
        dangerous_data = {
            'name': "<script>alert('xss')</script>",
            'role': "admin' onload='alert(1)'"
        }

        safe_result = XSSProtection.safe_format(template, **dangerous_data)

        # Should not contain dangerous content
        assert "<script>" not in safe_result
        assert "onload=" not in safe_result
        assert "alert(" not in safe_result

        # Should contain escaped content
        assert "&lt;" in safe_result or "\\u003c" in safe_result

    def test_url_validation_in_html(self):
        """Test URL validation in HTML sanitization."""
        dangerous_html = '''
        <a href="javascript:alert('xss')">Click me</a>
        <img src="data:text/html,<script>alert('xss')</script>">
        <a href="https://safe.com">Safe link</a>
        <img src="/safe/image.jpg" alt="Safe image">
        '''

        sanitized = XSSProtection.sanitize_html(dangerous_html)

        # Dangerous URLs should be blocked
        assert "javascript:" not in sanitized
        assert "#blocked-url" in sanitized or "javascript:" not in sanitized

        # Safe URLs should remain
        assert "https://safe.com" in sanitized
        assert "/safe/image.jpg" in sanitized

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "javascript:alert('xss')",
        "onload=alert('xss')",
        "';alert('xss');//",
        "<img src=x onerror=alert('xss')>",
        "data:text/html,<script>alert('xss')</script>",
        "vbscript:alert('xss')",
        "<iframe src='javascript:alert()'></iframe>"
    ])
    def test_comprehensive_xss_payloads(self, xss_payload):
        """Test XSS protection against various attack vectors."""
        # Test HTML escaping
        html_escaped = XSSProtection.escape_html(xss_payload)
        assert not self._contains_executable_content(html_escaped)

        # Test JSON escaping
        json_escaped = XSSProtection.escape_json_string(xss_payload)
        assert not self._contains_executable_content(json_escaped)

        # Test JavaScript escaping
        js_escaped = XSSProtection.escape_javascript_string(xss_payload)
        assert not self._contains_executable_content(js_escaped)

        # Test HTML sanitization
        html_sanitized = XSSProtection.sanitize_html(xss_payload)
        assert not self._contains_executable_content(html_sanitized)

    def _contains_executable_content(self, content):
        """Check if content contains potentially executable script content."""
        dangerous_patterns = [
            "<script",
            "javascript:",
            "vbscript:",
            "onload=",
            "onerror=",
            "onclick=",
            "alert(",
            "eval(",
            "document.write"
        ]

        content_lower = content.lower()
        return any(pattern in content_lower for pattern in dangerous_patterns)

    def test_xss_protection_performance(self):
        """Test XSS protection performance with large content."""
        import time

        # Create large content with mixed safe/dangerous elements
        large_content = """
        <p>Safe paragraph content.</p>
        <script>alert('dangerous')</script>
        """ * 1000

        start_time = time.time()
        sanitized = XSSProtection.sanitize_html(large_content)
        end_time = time.time()

        # Should process within reasonable time (< 1 second for this size)
        processing_time = end_time - start_time
        assert processing_time < 1.0

        # Should still be effective
        assert "<script>" not in sanitized
        assert "Safe paragraph content." in sanitized