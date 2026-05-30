"""
Input Validation Security Module

Provides comprehensive input validation and sanitization for PgForge.
Prevents XSS, SQL injection, and other input-based attacks.
"""

import html
import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Dict, List, Union
from markupsafe import escape
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class InputValidator:
    """Comprehensive input validation and sanitization"""
    
    # Common regex patterns for validation
    PATTERNS = {
        'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
        'phone': re.compile(r'^\+?1?-?\.?\s?\(?([0-9]{3})\)?[-\.\s]?([0-9]{3})[-\.\s]?([0-9]{4})$'),
        'alphanumeric': re.compile(r'^[a-zA-Z0-9]+$'),
        'alphanumeric_space': re.compile(r'^[a-zA-Z0-9\s]+$'),
        'safe_filename': re.compile(r'^[a-zA-Z0-9._-]+$'),
        'uuid': re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'),
        'username': re.compile(r'^[a-zA-Z0-9._-]{3,30}$'),
    }
    
    # Dangerous SQL keywords that should be escaped or rejected
    SQL_INJECTION_PATTERNS = [
        r'\b(?:union|select|insert|update|delete|drop|create|alter|exec|execute)\b',
        r'[;\'"\\]',
        r'--',
        r'/\*.*\*/',
    ]
    
    # XSS patterns
    XSS_PATTERNS = [
        r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe\b',
        r'<object\b',
        r'<embed\b',
    ]
    
    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 1000, allow_html: bool = False) -> str:
        """Sanitize string input"""
        if not isinstance(value, str):
            value = str(value) if value is not None else ""
        
        # Trim whitespace
        value = value.strip()
        
        # Enforce length limits
        if len(value) > max_length:
            log.warning(f"Input truncated from {len(value)} to {max_length} characters")
            value = value[:max_length]
        
        if not allow_html:
            # Escape HTML to prevent XSS
            value = html.escape(value, quote=True)
        else:
            # Limited HTML sanitization (remove dangerous tags)
            value = cls._sanitize_html(value)
        
        return value
    
    @classmethod
    def _sanitize_html(cls, value: str) -> str:
        """Basic HTML sanitization (for when HTML is allowed)"""
        # Remove script tags and dangerous attributes
        for pattern in cls.XSS_PATTERNS:
            value = re.sub(pattern, '', value, flags=re.IGNORECASE)
        
        return value
    
    @classmethod
    def validate_email(cls, email: str) -> bool:
        """Validate email format"""
        if not email or len(email) > 254:
            return False
        return bool(cls.PATTERNS['email'].match(email))
    
    @classmethod
    def validate_phone(cls, phone: str) -> bool:
        """Validate phone number format"""
        if not phone:
            return False
        # Remove common formatting characters
        clean_phone = re.sub(r'[\s\-\.\(\)]', '', phone)
        return bool(cls.PATTERNS['phone'].match(clean_phone))
    
    @classmethod
    def validate_amount(cls, amount: Union[str, float, Decimal], 
                       min_value: Optional[Decimal] = None,
                       max_value: Optional[Decimal] = None,
                       max_decimal_places: int = 2) -> tuple[bool, Optional[Decimal]]:
        """Validate monetary amount"""
        try:
            if isinstance(amount, str):
                # Remove currency symbols and whitespace
                amount = re.sub(r'[$,\s]', '', amount)
                decimal_amount = Decimal(amount)
            elif isinstance(amount, (int, float)):
                decimal_amount = Decimal(str(amount))
            elif isinstance(amount, Decimal):
                decimal_amount = amount
            else:
                return False, None
            
            # Check decimal places
            if decimal_amount.as_tuple().exponent < -max_decimal_places:
                return False, None
            
            # Check range
            if min_value is not None and decimal_amount < min_value:
                return False, None
            if max_value is not None and decimal_amount > max_value:
                return False, None
            
            return True, decimal_amount
            
        except (InvalidOperation, ValueError, TypeError):
            return False, None
    
    @classmethod
    def sanitize_search_query(cls, query: str, max_length: int = 100) -> str:
        """Sanitize search query input"""
        if not query:
            return ""
        
        # Basic sanitization
        query = cls.sanitize_string(query, max_length, allow_html=False)
        
        # Remove potential SQL injection patterns
        for pattern in cls.SQL_INJECTION_PATTERNS:
            query = re.sub(pattern, '', query, flags=re.IGNORECASE)
        
        # Remove multiple spaces
        query = re.sub(r'\s+', ' ', query)
        
        return query.strip()
    
    @classmethod
    def validate_url(cls, url: str, allowed_schemes: List[str] = None) -> bool:
        """Validate URL format and scheme"""
        if not url:
            return False
        
        if allowed_schemes is None:
            allowed_schemes = ['http', 'https']
        
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme in allowed_schemes and 
                parsed.netloc and
                len(url) <= 2048  # Reasonable URL length limit
            )
        except Exception:
            return False
    
    @classmethod
    def validate_filename(cls, filename: str) -> bool:
        """Validate filename for security"""
        if not filename or len(filename) > 255:
            return False
        
        # Check for directory traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            return False
        
        # Check for safe characters only
        return bool(cls.PATTERNS['safe_filename'].match(filename))
    
    @classmethod
    def validate_username(cls, username: str) -> bool:
        """Validate username format"""
        if not username:
            return False
        return bool(cls.PATTERNS['username'].match(username))
    
    @classmethod
    def sanitize_dict(cls, data: Dict[str, Any], 
                     string_fields: List[str] = None,
                     required_fields: List[str] = None) -> Dict[str, Any]:
        """Sanitize dictionary of form data"""
        if not isinstance(data, dict):
            return {}
        
        sanitized = {}
        string_fields = string_fields or []
        required_fields = required_fields or []
        
        # Check required fields
        for field in required_fields:
            if field not in data or data[field] is None:
                raise ValueError(f"Required field missing: {field}")
        
        # Sanitize fields
        for key, value in data.items():
            if key in string_fields and isinstance(value, str):
                sanitized[key] = cls.sanitize_string(value)
            else:
                sanitized[key] = value
        
        return sanitized


class ValidationError(ValueError):
    """Custom exception for validation errors"""
    pass


# Convenience functions
def sanitize_string(value: str, **kwargs) -> str:
    """Sanitize string input"""
    return InputValidator.sanitize_string(value, **kwargs)


def validate_email(email: str) -> bool:
    """Validate email format"""
    return InputValidator.validate_email(email)


def validate_amount(amount: Union[str, float, Decimal], **kwargs) -> tuple[bool, Optional[Decimal]]:
    """Validate monetary amount"""
    return InputValidator.validate_amount(amount, **kwargs)


def sanitize_search_query(query: str, **kwargs) -> str:
    """Sanitize search query"""
    return InputValidator.sanitize_search_query(query, **kwargs)


class InputValidationMixin:
    """Mixin providing input validation capabilities for PgForge managers"""
    
    def validate_form_input(self, form_data: Dict[str, Any], 
                           string_fields: List[str] = None) -> Dict[str, Any]:
        """
        Validate and sanitize form input data.
        
        :param form_data: Dictionary of form field data to validate
        :param string_fields: List of field names that should be treated as strings
        :return: Sanitized form data dictionary
        """
        return InputValidator.sanitize_dict(
            form_data, 
            string_fields=string_fields or []
        )
    
    def validate_search_input(self, query: str) -> str:
        """
        Validate and sanitize search query input.
        
        :param query: Search query string to validate
        :return: Sanitized search query string
        """
        return InputValidator.sanitize_search_query(query)
    
    def validate_user_input(self, username: str, email: str = None) -> Dict[str, bool]:
        """
        Validate user registration input data.
        
        :param username: Username to validate
        :param email: Email address to validate (optional)
        :return: Dictionary with validation results
        """
        results = {
            'username_valid': InputValidator.validate_username(username)
        }
        
        if email:
            results['email_valid'] = InputValidator.validate_email(email)
            
        return results
    
    def sanitize_string_field(self, value: str, allow_html: bool = False) -> str:
        """
        Sanitize a string field value.
        
        :param value: String value to sanitize
        :param allow_html: Whether to allow safe HTML tags
        :return: Sanitized string value
        """
        return InputValidator.sanitize_string(value, allow_html=allow_html)