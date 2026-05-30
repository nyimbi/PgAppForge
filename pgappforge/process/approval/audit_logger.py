"""
Approval Audit Logger

Focused service class responsible for comprehensive audit logging
and security monitoring of approval workflow operations.
"""

import json
import logging
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from flask import request, session, current_app
from .crypto_config import SecureCryptoConfig, SecureSessionManager

log = logging.getLogger(__name__)


class ApprovalAuditLogger:
    """
    Handles comprehensive audit logging for approval workflows.
    
    Responsibilities:
    - Security event logging with detailed context
    - Cryptographic integrity verification  
    - Approval record integrity hashing
    - Audit trail generation and management
    """
    
    def __init__(self, appbuilder=None):
        self.appbuilder = appbuilder
        self.audit_logger = logging.getLogger('fab.approval.audit')
    
    def log_security_event(self, event_type: str, event_data: Dict):
        """Log security events for audit trail with comprehensive context."""
        audit_record = {
            'event_type': event_type,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'session_id': session.get('_id') if session else None,
            'user_agent': request.user_agent.string if request else None,
            'ip_address': request.remote_addr if request else None,
            **event_data
        }
        
        # Log to dedicated audit logger with structured format
        self.audit_logger.info(json.dumps(audit_record))
        
        # Also log to main application log for immediate visibility
        log.info(f"APPROVAL AUDIT: {event_type} - {json.dumps(event_data)}")
    
    def log_approval_granted(self, user, instance, step_config, workflow_name, comments):
        """Log successful approval with comprehensive context."""
        self.log_security_event('approval_granted', {
            'user_id': user.id,
            'user_name': user.username,
            'instance_id': getattr(instance, 'id', 'unknown'),
            'instance_type': instance.__class__.__name__,
            'step_name': step_config['name'],
            'workflow_name': workflow_name,
            'has_comments': bool(comments),
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'session_id': self._get_secure_session_id(),
            'ip_address': request.remote_addr if request else 'unknown'
        })
        
        # Log to PgForge's security manager
        if self.appbuilder and hasattr(self.appbuilder, 'sm') and hasattr(self.appbuilder.sm, 'log'):
            self.appbuilder.sm.log.info(
                f"SECURE APPROVAL: {user.username} approved {instance.__class__.__name__} "
                f"step ({step_config['name']}) with enhanced security validation"
            )
    
    def log_security_violation(self, violation_type: str, user, instance, details: Dict):
        """Log security violations with enhanced context."""
        self.log_security_event(violation_type, {
            'user_id': user.id if user else None,
            'user_name': user.username if user else 'unknown',
            'instance_id': getattr(instance, 'id', 'unknown'),
            'instance_type': instance.__class__.__name__ if instance else 'unknown',
            'violation_details': details,
            'timestamp': datetime.now(tz=timezone.utc).isoformat()
        })
    
    def calculate_approval_integrity_hash(self, approval_data: Dict) -> str:
        """
        Calculate HMAC integrity hash for approval data using secure cryptography.

        SECURITY IMPROVEMENT: Now uses SecureCryptoConfig for proper key validation
        and secure HMAC calculation, addressing CVE-2024-001.
        """
        # Create data string for hashing (excluding the hash field itself)
        hash_data = {k: v for k, v in approval_data.items() if k != 'integrity_hash'}
        data_string = json.dumps(hash_data, sort_keys=True)

        # Use secure HMAC calculation with validated secret key
        return SecureCryptoConfig.calculate_secure_hmac(
            data_string,
            additional_context="approval_integrity"
        )
    
    def generate_approval_id(self) -> str:
        """
        Generate cryptographically secure, unique approval ID.

        SECURITY IMPROVEMENT: Now uses SecureCryptoConfig for secure token
        generation with proper entropy, addressing CVE-2024-003.
        """
        return SecureCryptoConfig.generate_secure_token("approval")
    
    def verify_approval_record_integrity(self, approval_data: Dict) -> bool:
        """
        Verify the integrity of an approval record using timing-safe comparison.

        SECURITY IMPROVEMENT: Now uses timing-safe comparison to prevent
        timing attacks, addressing CVE-2024-002.
        """
        if 'integrity_hash' not in approval_data:
            log.warning("Approval record missing integrity hash")
            return False

        stored_hash = approval_data['integrity_hash']

        # Create data string for verification (excluding the hash field itself)
        hash_data = {k: v for k, v in approval_data.items() if k != 'integrity_hash'}
        data_string = json.dumps(hash_data, sort_keys=True)

        # Use secure HMAC verification with timing-safe comparison
        return SecureCryptoConfig.verify_secure_hmac(
            data_string,
            stored_hash,
            additional_context="approval_integrity"
        )
    
    def _get_secure_session_id(self) -> Optional[str]:
        """Get secure session identifier for audit logging."""
        if session:
            return session.get('_id')
        return None
    
    def log_transaction_failed(self, user, instance_id, step, error):
        """Log failed approval transactions."""
        self.log_security_event('approval_transaction_failed', {
            'user_id': user.id if user else None,
            'instance_id': instance_id,
            'step': step,
            'error': str(error),
            'error_type': type(error).__name__
        })
    
    def log_workflow_advancement(self, instance, workflow_config, completed_step):
        """Log workflow state advancement for audit purposes."""
        self.log_security_event('workflow_advanced', {
            'instance_id': getattr(instance, 'id', 'unknown'),
            'instance_type': instance.__class__.__name__,
            'completed_step': completed_step,
            'new_state': getattr(instance, 'current_state', 'unknown'),
            'workflow_name': getattr(instance.__class__, '_approval_workflow', 'default'),
            'total_steps': len(workflow_config['steps'])
        })
    
    def create_secure_approval_record(self, user, step: int, step_config: Dict, comments: Optional[str]) -> Dict:
        """Create approval record with cryptographic integrity protection."""
        approval_id = self.generate_approval_id()
        timestamp = datetime.now(tz=timezone.utc)
        
        approval_data = {
            'approval_id': approval_id,
            'user_id': user.id,
            'user_name': user.username,
            'step': step,
            'step_name': step_config['name'],
            'required_role': step_config['required_role'],
            'status': 'approved',
            'comments': comments,
            'timestamp': timestamp.isoformat(),
            'ip_address': request.remote_addr if request else None,
            'user_agent': request.user_agent.string if request else None
        }
        
        # Add cryptographic integrity hash
        approval_data['integrity_hash'] = self.calculate_approval_integrity_hash(approval_data)
        
        return approval_data