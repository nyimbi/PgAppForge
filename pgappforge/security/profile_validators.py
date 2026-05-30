"""
Profile validation and security utilities for PgAppForge

This module provides comprehensive validation and security features for user profiles,
including data sanitization, permission checks, and audit logging.
"""
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from flask import g
from flask_babel import gettext
from wtforms.validators import ValidationError

from pgappforge.models.profiles import ProfileType, UserProfile


class ProfileSecurityManager:
    """Security manager for profile operations"""
    
    # Sensitive fields that require additional protection
    SENSITIVE_FIELDS = {
        'employee_id', 'manager_email', 'emergency_contact_phone',
        'date_of_birth', 'phone', 'mobile', 'address_line1', 'address_line2'
    }
    
    # Fields that only admins can modify
    ADMIN_ONLY_FIELDS = {
        'profile_verified', 'profile_type', 'employee_id'
    }
    
    # Fields that require email verification to change
    VERIFICATION_REQUIRED_FIELDS = {
        'email', 'phone', 'mobile'
    }
    
    @classmethod
    def can_view_field(cls, field_name: str, profile: UserProfile, viewer_user) -> bool:
        """Check if user can view a specific profile field"""
        # Owner can always view their own fields
        if viewer_user and profile.user_id == viewer_user.id:
            return True
        
        # Check profile visibility
        if profile.profile_visibility == 'private':
            return False
        
        # Sensitive fields are hidden from non-owners
        if field_name in cls.SENSITIVE_FIELDS:
            return False
        
        # Admin users can view most fields
        if viewer_user and hasattr(viewer_user, 'is_admin') and viewer_user.is_admin():
            return True
        
        return profile.profile_visibility == 'public'
    
    @classmethod
    def can_edit_field(cls, field_name: str, profile: UserProfile, editor_user) -> bool:
        """Check if user can edit a specific profile field"""
        if not editor_user:
            return False
        
        # Only profile owner or admin can edit
        is_owner = profile.user_id == editor_user.id
        is_admin = hasattr(editor_user, 'is_admin') and editor_user.is_admin()
        
        if not (is_owner or is_admin):
            return False
        
        # Admin-only fields
        if field_name in cls.ADMIN_ONLY_FIELDS and not is_admin:
            return False
        
        return True
    
    @classmethod
    def sanitize_profile_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize profile data before saving"""
        sanitized = {}
        
        for key, value in data.items():
            if value is None:
                sanitized[key] = None
                continue
            
            # String fields - strip whitespace and normalize
            if isinstance(value, str):
                value = value.strip()
                if not value:  # Empty string becomes None
                    sanitized[key] = None
                    continue
                
                # URL fields - ensure proper format
                if key in ['website', 'linkedin', 'twitter', 'github']:
                    sanitized[key] = cls._sanitize_url(value, key)
                # Email fields
                elif 'email' in key.lower():
                    sanitized[key] = cls._sanitize_email(value)
                # Phone fields
                elif key in ['phone', 'mobile', 'emergency_contact_phone']:
                    sanitized[key] = cls._sanitize_phone(value)
                # Regular text fields
                else:
                    sanitized[key] = cls._sanitize_text(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    @classmethod
    def _sanitize_url(cls, url: str, field_type: str) -> str:
        """Sanitize URL fields"""
        if not url:
            return None
        
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        # Basic URL validation
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        if not url_pattern.match(url):
            raise ValidationError(f"Invalid {field_type} URL format")
        
        return url
    
    @classmethod
    def _sanitize_email(cls, email: str) -> str:
        """Sanitize email fields"""
        if not email:
            return None
        
        email = email.lower().strip()
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        
        if not email_pattern.match(email):
            raise ValidationError("Invalid email format")
        
        return email
    
    @classmethod
    def _sanitize_phone(cls, phone: str) -> str:
        """Sanitize phone number fields"""
        if not phone:
            return None
        
        # Remove all non-digit characters except + and -
        phone = re.sub(r'[^\d+\-\s\(\)]', '', phone).strip()
        
        if not phone:
            return None
        
        # Basic phone validation (10-15 digits)
        digit_count = len(re.sub(r'[^\d]', '', phone))
        if digit_count < 10 or digit_count > 15:
            raise ValidationError("Phone number must be between 10-15 digits")
        
        return phone
    
    @classmethod
    def _sanitize_text(cls, text: str) -> str:
        """Sanitize general text fields"""
        if not text:
            return None
        
        # Remove potentially dangerous characters
        text = re.sub(r'[<>"\']', '', text)
        
        # Normalize whitespace
        text = ' '.join(text.split())
        
        return text if text else None


class ProfileValidator:
    """Validator for profile data integrity and business rules"""
    
    @classmethod
    def validate_profile_data(cls, profile: UserProfile, data: Dict[str, Any]) -> List[str]:
        """Validate profile data and return list of errors"""
        errors = []
        
        # Date validations
        if 'date_of_birth' in data and data['date_of_birth']:
            errors.extend(cls._validate_date_of_birth(data['date_of_birth']))
        
        if 'start_date' in data and data['start_date']:
            errors.extend(cls._validate_start_date(data['start_date']))
        
        # Professional field validations
        if profile.profile_type in [ProfileType.EMPLOYEE, ProfileType.ADMIN]:
            errors.extend(cls._validate_professional_fields(data))
        
        # Skills and certifications
        if 'skills' in data:
            errors.extend(cls._validate_skills(data['skills']))
        
        if 'certifications' in data:
            errors.extend(cls._validate_certifications(data['certifications']))
        
        # Custom field validations
        if 'custom_fields' in data:
            errors.extend(cls._validate_custom_fields(data['custom_fields']))
        
        return errors
    
    @classmethod
    def _validate_date_of_birth(cls, dob: datetime.date) -> List[str]:
        """Validate date of birth"""
        errors = []
        
        if dob > datetime.date.today():
            errors.append("Date of birth cannot be in the future")
        
        # Check reasonable age limits (13-120 years)
        age = (datetime.date.today() - dob).days / 365.25
        if age < 13:
            errors.append("User must be at least 13 years old")
        elif age > 120:
            errors.append("Invalid date of birth (age too high)")
        
        return errors
    
    @classmethod
    def _validate_start_date(cls, start_date: datetime.date) -> List[str]:
        """Validate employment start date"""
        errors = []
        
        if start_date > datetime.date.today():
            errors.append("Start date cannot be in the future")
        
        # Check if start date is reasonable (not more than 50 years ago)
        years_ago = (datetime.date.today() - start_date).days / 365.25
        if years_ago > 50:
            errors.append("Start date seems too far in the past")
        
        return errors
    
    @classmethod
    def _validate_professional_fields(cls, data: Dict[str, Any]) -> List[str]:
        """Validate professional profile fields"""
        errors = []
        
        # Employee ID format validation
        if 'employee_id' in data and data['employee_id']:
            emp_id = data['employee_id']
            if not re.match(r'^[A-Z0-9\-_]{3,20}$', emp_id, re.IGNORECASE):
                errors.append("Employee ID must be 3-20 characters (letters, numbers, hyphens, underscores)")
        
        # Manager email validation
        if 'manager_email' in data and data['manager_email']:
            try:
                ProfileSecurityManager._sanitize_email(data['manager_email'])
            except ValidationError as e:
                errors.append(f"Manager email: {e}")
        
        return errors
    
    @classmethod
    def _validate_skills(cls, skills: List[str]) -> List[str]:
        """Validate skills array"""
        errors = []
        
        if not isinstance(skills, list):
            errors.append("Skills must be a list")
            return errors
        
        if len(skills) > 50:
            errors.append("Maximum 50 skills allowed")
        
        for skill in skills:
            if not isinstance(skill, str) or len(skill.strip()) == 0:
                errors.append("Each skill must be a non-empty string")
            elif len(skill) > 100:
                errors.append("Each skill must be 100 characters or less")
        
        return errors
    
    @classmethod
    def _validate_certifications(cls, certifications: List[Dict[str, Any]]) -> List[str]:
        """Validate certifications array"""
        errors = []
        
        if not isinstance(certifications, list):
            errors.append("Certifications must be a list")
            return errors
        
        if len(certifications) > 20:
            errors.append("Maximum 20 certifications allowed")
        
        for i, cert in enumerate(certifications):
            if not isinstance(cert, dict):
                errors.append(f"Certification {i+1} must be an object")
                continue
            
            if 'name' not in cert or not cert['name']:
                errors.append(f"Certification {i+1} must have a name")
            elif len(cert['name']) > 255:
                errors.append(f"Certification {i+1} name too long (max 255 characters)")
            
            if 'issuer' not in cert or not cert['issuer']:
                errors.append(f"Certification {i+1} must have an issuer")
            elif len(cert['issuer']) > 255:
                errors.append(f"Certification {i+1} issuer too long (max 255 characters)")
        
        return errors
    
    @classmethod
    def _validate_custom_fields(cls, custom_fields: Dict[str, Any]) -> List[str]:
        """Validate custom fields"""
        errors = []
        
        if not isinstance(custom_fields, dict):
            errors.append("Custom fields must be a dictionary")
            return errors
        
        if len(custom_fields) > 50:
            errors.append("Maximum 50 custom fields allowed")
        
        for key, value in custom_fields.items():
            if not isinstance(key, str) or len(key) > 100:
                errors.append("Custom field names must be strings of 100 characters or less")
            
            # Validate value based on type
            if isinstance(value, str) and len(value) > 1000:
                errors.append(f"Custom field '{key}' value too long (max 1000 characters)")
        
        return errors


class ProfileAuditLogger:
    """Audit logger for profile changes"""
    
    @classmethod
    def log_profile_change(cls, profile: UserProfile, changed_fields: Dict[str, Any], 
                          editor_user, action: str = 'update'):
        """Log profile changes for audit trail"""
        # This would integrate with your existing audit system
        # For now, we'll use basic logging
        import logging
        
        audit_log = logging.getLogger('profile_audit')
        
        log_entry = {
            'action': action,
            'profile_id': profile.id,
            'user_id': profile.user_id,
            'editor_id': editor_user.id if editor_user else None,
            'editor_username': editor_user.username if editor_user else None,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'changed_fields': list(changed_fields.keys()),
            'sensitive_fields': [f for f in changed_fields.keys() 
                               if f in ProfileSecurityManager.SENSITIVE_FIELDS]
        }
        
        audit_log.info(f"Profile {action}: {log_entry}")
    
    @classmethod
    def log_profile_access(cls, profile: UserProfile, viewer_user, fields_accessed: List[str]):
        """Log profile access for sensitive fields"""
        sensitive_accessed = [f for f in fields_accessed 
                            if f in ProfileSecurityManager.SENSITIVE_FIELDS]
        
        if sensitive_accessed:
            import logging
            audit_log = logging.getLogger('profile_access')
            
            log_entry = {
                'action': 'view',
                'profile_id': profile.id,
                'profile_user_id': profile.user_id,
                'viewer_id': viewer_user.id if viewer_user else None,
                'viewer_username': viewer_user.username if viewer_user else None,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'sensitive_fields_accessed': sensitive_accessed
            }
            
            audit_log.info(f"Profile access: {log_entry}")