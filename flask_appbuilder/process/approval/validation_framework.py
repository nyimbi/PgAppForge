"""
Validation Framework for Approval System

Provides comprehensive input validation, sanitization, and security threat detection
for approval workflow operations.

SECURITY IMPROVEMENTS:
- Input validation and sanitization
- Security threat detection
- Validation context management
"""

import re
import logging
import bleach
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime, timezone

# Removed direct import to prevent circular dependency - using late import pattern

log = logging.getLogger(__name__)


class ValidationType(Enum):
    """Types of validation to perform."""
    APPROVAL_REQUEST = "approval_request"
    USER_INPUT = "user_input"
    CHAIN_CONFIG = "chain_config"
    WORKFLOW_DATA = "workflow_data"


class SanitizationType(Enum):
    """Types of sanitization to apply."""
    HTML_STRIP = "html_strip"
    XSS_CLEAN = "xss_clean"
    SQL_ESCAPE = "sql_escape"
    SCRIPT_REMOVE = "script_remove"


class ValidationContext:
    """Context for validation operations."""
    
    def __init__(self, user_id: int, operation: str, validation_type: ValidationType):
        self.user_id = user_id
        self.operation = operation
        self.validation_type = validation_type
        self.timestamp = datetime.now(tz=timezone.utc)


def validate_approval_request(data: Dict[str, Any], user_id: int, validator=None) -> Dict[str, Any]:
    """
    Validate approval request data.
    
    Args:
        data: Request data to validate
        user_id: ID of requesting user
        validator: Optional ApprovalSecurityValidator instance (prevents circular import)
        
    Returns:
        dict: Validation results with sanitized data
    """
    context = ValidationContext(user_id, "approval_request", ValidationType.APPROVAL_REQUEST)
    
    # Use dependency injection to prevent circular imports
    if validator is None:
        # Late import to prevent circular dependency
        from .security_validator import ApprovalSecurityValidator
        validator = ApprovalSecurityValidator(None)
    
    # Get approval validation schema
    schema = validator.get_approval_validation_schema()
    
    # Validate input data
    result = validator.validate_input_data(data, schema)
    
    # Add context information
    result['context'] = {
        'user_id': user_id,
        'validation_type': ValidationType.APPROVAL_REQUEST.value,
        'timestamp': context.timestamp.isoformat()
    }
    
    return result


def validate_user_input(data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """
    Validate general user input data.
    
    Args:
        data: Input data to validate
        user_id: ID of user providing input
        
    Returns:
        dict: Validation results with sanitized data
    """
    context = ValidationContext(user_id, "user_input", ValidationType.USER_INPUT)
    
    validation_results = {
        'valid': True,
        'sanitized_data': {},
        'errors': [],
        'threats': [],
        'context': {
            'user_id': user_id,
            'validation_type': ValidationType.USER_INPUT.value,
            'timestamp': context.timestamp.isoformat()
        }
    }
    
    try:
        # Basic validation and sanitization
        for field_name, field_value in data.items():
            if isinstance(field_value, str):
                # Sanitize string fields
                sanitized = quick_sanitize(field_value, SanitizationType.XSS_CLEAN)
                validation_results['sanitized_data'][field_name] = sanitized
                
                # Check for threats
                threats = detect_security_threats(field_value)
                if threats:
                    validation_results['threats'].extend(threats)
            else:
                validation_results['sanitized_data'][field_name] = field_value
                
        return validation_results
        
    except Exception as e:
        validation_results['valid'] = False
        validation_results['errors'].append(f"Validation error: {str(e)}")
        return validation_results


def validate_chain_config(config: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """
    Validate approval chain configuration.
    
    Args:
        config: Chain configuration to validate
        user_id: ID of user creating chain
        
    Returns:
        dict: Validation results with sanitized configuration
    """
    context = ValidationContext(user_id, "chain_config", ValidationType.CHAIN_CONFIG)
    
    validation_results = {
        'valid': True,
        'sanitized_data': {},
        'errors': [],
        'threats': [],
        'context': {
            'user_id': user_id,
            'validation_type': ValidationType.CHAIN_CONFIG.value,
            'timestamp': context.timestamp.isoformat()
        }
    }
    
    try:
        # Validate required fields
        required_fields = ['type', 'steps']
        for field in required_fields:
            if field not in config:
                validation_results['errors'].append(f"Required field '{field}' missing")
                validation_results['valid'] = False
        
        # Validate chain type
        if 'type' in config:
            valid_types = ['sequential', 'parallel', 'conditional', 'unanimous', 'majority']
            if config['type'] not in valid_types:
                validation_results['errors'].append(f"Invalid chain type: {config['type']}")
                validation_results['valid'] = False
            else:
                validation_results['sanitized_data']['type'] = config['type']
        
        # Validate steps
        if 'steps' in config:
            if not isinstance(config['steps'], list) or len(config['steps']) == 0:
                validation_results['errors'].append("Steps must be a non-empty list")
                validation_results['valid'] = False
            else:
                validation_results['sanitized_data']['steps'] = config['steps']
        
        # Copy other safe fields
        safe_fields = ['priority', 'timeout', 'escalation', 'notifications']
        for field in safe_fields:
            if field in config:
                validation_results['sanitized_data'][field] = config[field]
        
        return validation_results
        
    except Exception as e:
        validation_results['valid'] = False
        validation_results['errors'].append(f"Chain config validation error: {str(e)}")
        return validation_results


def quick_sanitize(value: str, sanitization_type: SanitizationType) -> str:
    """
    Quick sanitization of string values.
    
    Args:
        value: String to sanitize
        sanitization_type: Type of sanitization to apply
        
    Returns:
        str: Sanitized string
    """
    if not isinstance(value, str):
        return value
    
    try:
        if sanitization_type == SanitizationType.HTML_STRIP:
            # Strip all HTML tags
            return bleach.clean(value, tags=[], attributes={}, strip=True)
        
        elif sanitization_type == SanitizationType.XSS_CLEAN:
            # Clean XSS patterns
            sanitized = bleach.clean(
                value,
                tags=[],
                attributes={},
                protocols=['http', 'https', 'mailto'],
                strip=True
            )
            
            # Remove script-like patterns
            script_patterns = [
                r'<script[^>]*>.*?</script>',
                r'javascript:',
                r'vbscript:',
                r'on\w+\s*=',
                r'data:text/html'
            ]
            
            for pattern in script_patterns:
                sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE | re.DOTALL)
            
            return sanitized.strip()
        
        elif sanitization_type == SanitizationType.SQL_ESCAPE:
            # Basic SQL injection character escaping
            sql_chars = ["'", '"', ';', '--', '/*', '*/', 'xp_', 'sp_']
            sanitized = value
            for char in sql_chars:
                sanitized = sanitized.replace(char, f"\\{char}")
            return sanitized
        
        elif sanitization_type == SanitizationType.SCRIPT_REMOVE:
            # Remove script tags and javascript
            script_patterns = [
                r'<script[^>]*>.*?</script>',
                r'javascript:[^"\']*',
                r'vbscript:[^"\']*'
            ]
            
            sanitized = value
            for pattern in script_patterns:
                sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE | re.DOTALL)
            
            return sanitized.strip()
        
        else:
            # Default: basic cleanup
            return bleach.clean(value, tags=[], attributes={}, strip=True)
            
    except Exception as e:
        log.error(f"Sanitization error: {e}")
        # Return empty string if sanitization fails
        return ""


def detect_security_threats(value: str) -> List[Dict[str, Any]]:
    """
    Detect potential security threats in input.
    
    Args:
        value: String to analyze
        
    Returns:
        list: List of detected threats
    """
    threats = []
    
    if not isinstance(value, str):
        return threats
    
    try:
        value_lower = value.lower()
        
        # XSS patterns
        xss_patterns = [
            (r'<script[^>]*>', 'XSS_SCRIPT_TAG'),
            (r'javascript:', 'XSS_JAVASCRIPT_PROTOCOL'),
            (r'vbscript:', 'XSS_VBSCRIPT_PROTOCOL'),
            (r'on\w+\s*=', 'XSS_EVENT_HANDLER'),
            (r'data:text/html', 'XSS_DATA_URI')
        ]
        
        for pattern, threat_type in xss_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                threats.append({
                    'type': threat_type,
                    'severity': 'HIGH',
                    'pattern': pattern,
                    'description': f'Potential XSS attack pattern detected: {threat_type}'
                })
        
        # SQL injection patterns
        sql_patterns = [
            (r';\s*(drop|delete|insert|update)\s+', 'SQL_INJECTION_DML'),
            (r'union\s+select', 'SQL_INJECTION_UNION'),
            (r'--\s*$', 'SQL_INJECTION_COMMENT'),
            (r'/\*.*?\*/', 'SQL_INJECTION_BLOCK_COMMENT'),
            (r'\'\s*or\s+\S+\s*=\s*\S+', 'SQL_INJECTION_OR_CONDITION')
        ]
        
        for pattern, threat_type in sql_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE | re.DOTALL):
                threats.append({
                    'type': threat_type,
                    'severity': 'CRITICAL',
                    'pattern': pattern,
                    'description': f'Potential SQL injection detected: {threat_type}'
                })
        
        # Command injection patterns
        command_patterns = [
            (r';\s*(rm|del|format)', 'COMMAND_INJECTION_DELETE'),
            (r'`[^`]+`', 'COMMAND_INJECTION_BACKTICK'),
            (r'\$\([^)]+\)', 'COMMAND_INJECTION_SUBSHELL'),
            (r'&&\s*\w+', 'COMMAND_INJECTION_CHAIN')
        ]
        
        for pattern, threat_type in command_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                threats.append({
                    'type': threat_type,
                    'severity': 'HIGH',
                    'pattern': pattern,
                    'description': f'Potential command injection detected: {threat_type}'
                })
        
        return threats
        
    except Exception as e:
        log.error(f"Threat detection error: {e}")
        return []