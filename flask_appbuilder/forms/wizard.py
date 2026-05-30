"""
Flask-AppBuilder Wizard Form Implementation

Provides multi-step form functionality for handling large forms by breaking them
into manageable steps/tabs with session persistence and resumption capabilities.

Features:
- Multi-step form with configurable fields per step
- Session persistence for incomplete forms
- Progress tracking and navigation
- Client-side and server-side validation
- Draft saving and auto-save
- Responsive design with progress indicators
- Support for complex field types
"""

import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Type, Union, Tuple
from collections import OrderedDict

from flask import session, request, current_app, g
from flask_login import current_user
from wtforms import Form, ValidationError, Field
from wtforms.fields import HiddenField, StringField
from wtforms.validators import DataRequired, Optional as OptionalValidator

from flask_appbuilder.models.mixins import AuditMixin
from flask_appbuilder._compat import as_unicode

# Set up logging
logger = logging.getLogger(__name__)


class WizardStep:
    """
    Represents a single step in a wizard form
    
    Each step contains a subset of form fields and can have its own
    validation, title, description, and conditional logic.
    """
    
    def __init__(self, 
                 name: str,
                 title: str,
                 fields: List[str],
                 description: Optional[str] = None,
                 required_fields: Optional[List[str]] = None,
                 conditional_fields: Optional[Dict[str, Any]] = None,
                 validation_rules: Optional[Dict[str, Any]] = None,
                 icon: Optional[str] = None,
                 template: Optional[str] = None):
        """
        Initialize a wizard step
        
        Args:
            name: Unique step identifier
            title: Display title for the step
            fields: List of field names included in this step
            description: Optional description text
            required_fields: Fields that must be completed to proceed
            conditional_fields: Fields shown based on other field values
            validation_rules: Custom validation rules for this step
            icon: Icon class for step indicator
            template: Custom template for this step
        """
        self.name = name
        self.title = title
        self.fields = fields or []
        self.description = description
        self.required_fields = required_fields or []
        self.conditional_fields = conditional_fields or {}
        self.validation_rules = validation_rules or {}
        self.icon = icon or 'fa-edit'
        self.template = template
        
        # Runtime state
        self.is_valid = False
        self.is_completed = False
        self.validation_errors = {}
    
    def validate_step(self, form_data: Dict[str, Any]) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Validate all fields in this step
        
        Args:
            form_data: Form data to validate
            
        Returns:
            Tuple of (is_valid, errors_dict)
        """
        logger.debug(f"Validating step '{self.name}' with data: {list(form_data.keys())}")
        errors = {}
        
        # Check required fields
        for field_name in self.required_fields:
            if field_name not in form_data or not form_data[field_name]:
                if field_name not in errors:
                    errors[field_name] = []
                errors[field_name].append(f'{field_name} is required')
        
        # Apply custom validation rules
        for field_name, rules in self.validation_rules.items():
            if field_name in form_data:
                field_value = form_data[field_name]
                field_errors = self._validate_field(field_name, field_value, rules)
                if field_errors:
                    errors[field_name] = field_errors
        
        # Check conditional field requirements
        for field_name, conditions in self.conditional_fields.items():
            if self._should_show_field(field_name, form_data, conditions):
                if field_name in self.required_fields and not form_data.get(field_name):
                    if field_name not in errors:
                        errors[field_name] = []
                    errors[field_name].append(f'{field_name} is required')
        
        self.validation_errors = errors
        self.is_valid = len(errors) == 0
        
        if not self.is_valid:
            logger.warning(f"Step '{self.name}' validation failed with errors: {errors}")
        else:
            logger.debug(f"Step '{self.name}' validation passed")
            
        return self.is_valid, errors
    
    def _validate_field(self, field_name: str, value: Any, rules: Dict[str, Any]) -> List[str]:
        """Apply custom validation rules to a field"""
        errors = []
        
        if 'min_length' in rules and len(str(value)) < rules['min_length']:
            errors.append(f'{field_name} must be at least {rules["min_length"]} characters')
        
        if 'max_length' in rules and len(str(value)) > rules['max_length']:
            errors.append(f'{field_name} must be no more than {rules["max_length"]} characters')
        
        if 'pattern' in rules:
            import re
            if not re.match(rules['pattern'], str(value)):
                errors.append(f'{field_name} format is invalid')
        
        if 'custom' in rules and callable(rules['custom']):
            try:
                rules['custom'](value)
            except ValidationError as e:
                errors.append(str(e))
        
        return errors
    
    def _should_show_field(self, field_name: str, form_data: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
        """Check if a conditional field should be shown based on form data"""
        for condition_field, expected_value in conditions.items():
            actual_value = form_data.get(condition_field)
            if actual_value != expected_value:
                return False
        return True
    
    def get_progress_percentage(self, form_data: Dict[str, Any]) -> float:
        """Calculate completion percentage for this step"""
        if not self.fields:
            return 100.0
        
        completed_fields = sum(1 for field in self.fields if form_data.get(field))
        return (completed_fields / len(self.fields)) * 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for serialization"""
        return {
            'name': self.name,
            'title': self.title,
            'fields': self.fields,
            'description': self.description,
            'required_fields': self.required_fields,
            'conditional_fields': self.conditional_fields,
            'validation_rules': self.validation_rules,
            'icon': self.icon,
            'template': self.template,
            'is_valid': self.is_valid,
            'is_completed': self.is_completed,
            'validation_errors': self.validation_errors
        }


class WizardFormData:
    """
    Manages wizard form data persistence and state
    
    Handles storing partial form data in session, database, or cache
    for later retrieval when user returns to continue the form.
    """
    
    def __init__(self, wizard_id: str, user_id: Optional[str] = None):
        self.wizard_id = wizard_id
        self.user_id = user_id or (str(current_user.id) if current_user and current_user.is_authenticated else None)
        self.form_data = {}
        self.current_step = 0
        self.completed_steps = set()
        self.created_at = datetime.now(tz=timezone.utc)
        self.updated_at = datetime.now(tz=timezone.utc)
        self.expires_at = datetime.now(tz=timezone.utc) + timedelta(days=7)  # Default 7-day expiration
        self.is_submitted = False
        self.submission_id = None
    
    def update_data(self, step_data: Dict[str, Any], step_index: int):
        """Update form data for a specific step"""
        self.form_data.update(step_data)
        if step_index not in self.completed_steps:
            self.completed_steps.add(step_index)
        self.updated_at = datetime.now(tz=timezone.utc)
    
    def get_step_data(self, step_fields: List[str]) -> Dict[str, Any]:
        """Get form data for specific step fields"""
        return {field: self.form_data.get(field) for field in step_fields}
    
    def set_current_step(self, step_index: int):
        """Set the current active step"""
        self.current_step = step_index
        self.updated_at = datetime.now(tz=timezone.utc)
    
    def mark_submitted(self, submission_id: Optional[str] = None):
        """Mark the wizard as submitted"""
        self.is_submitted = True
        self.submission_id = submission_id or str(uuid.uuid4())
        self.updated_at = datetime.now(tz=timezone.utc)
    
    def is_expired(self) -> bool:
        """Check if the wizard data has expired"""
        return datetime.now(tz=timezone.utc) > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'wizard_id': self.wizard_id,
            'user_id': self.user_id,
            'form_data': self.form_data,
            'current_step': self.current_step,
            'completed_steps': list(self.completed_steps),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'is_submitted': self.is_submitted,
            'submission_id': self.submission_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WizardFormData':
        """Create instance from dictionary"""
        instance = cls(data['wizard_id'], data.get('user_id'))
        instance.form_data = data.get('form_data', {})
        instance.current_step = data.get('current_step', 0)
        instance.completed_steps = set(data.get('completed_steps', []))
        instance.created_at = datetime.fromisoformat(data['created_at'])
        instance.updated_at = datetime.fromisoformat(data['updated_at'])
        instance.expires_at = datetime.fromisoformat(data['expires_at'])
        instance.is_submitted = data.get('is_submitted', False)
        instance.submission_id = data.get('submission_id')
        return instance


class WizardFormManager:
    """Manager for creating and handling wizard forms"""
    
    def __init__(self):
        self.wizards: Dict[str, 'WizardForm'] = {}
        
    def create_wizard(self, config: Dict[str, Any]) -> str:
        """Create a new wizard form"""
        import uuid
        wizard_id = str(uuid.uuid4())
        wizard = WizardForm(config=config)
        self.wizards[wizard_id] = wizard
        return wizard_id
        
    def get_wizard(self, wizard_id: str) -> Optional['WizardForm']:
        """Get a wizard by ID"""
        return self.wizards.get(wizard_id)


class WizardFormPersistence:
    """
    Handles persistence of wizard form data
    
    Supports multiple storage backends: session, database, cache
    """
    
    def __init__(self, storage_backend: str = 'session'):
        """
        Initialize persistence handler
        
        Args:
            storage_backend: 'session', 'database', or 'cache'
        """
        self.storage_backend = storage_backend
    
    def save_wizard_data(self, wizard_data: WizardFormData) -> bool:
        """Save wizard data to configured backend"""
        try:
            if self.storage_backend == 'session':
                return self._save_to_session(wizard_data)
            elif self.storage_backend == 'database':
                return self._save_to_database(wizard_data)
            elif self.storage_backend == 'cache':
                return self._save_to_cache(wizard_data)
            else:
                raise ValueError(f"Unsupported storage backend: {self.storage_backend}")
        except Exception as e:
            current_app.logger.error(f"Failed to save wizard data: {e}")
            return False
    
    def load_wizard_data(self, wizard_id: str, user_id: Optional[str] = None) -> Optional[WizardFormData]:
        """Load wizard data from configured backend"""
        try:
            if self.storage_backend == 'session':
                return self._load_from_session(wizard_id)
            elif self.storage_backend == 'database':
                return self._load_from_database(wizard_id, user_id)
            elif self.storage_backend == 'cache':
                return self._load_from_cache(wizard_id, user_id)
            else:
                raise ValueError(f"Unsupported storage backend: {self.storage_backend}")
        except Exception as e:
            current_app.logger.error(f"Failed to load wizard data: {e}")
            return None
    
    def delete_wizard_data(self, wizard_id: str, user_id: Optional[str] = None) -> bool:
        """Delete wizard data from configured backend"""
        try:
            if self.storage_backend == 'session':
                return self._delete_from_session(wizard_id)
            elif self.storage_backend == 'database':
                return self._delete_from_database(wizard_id, user_id)
            elif self.storage_backend == 'cache':
                return self._delete_from_cache(wizard_id, user_id)
            else:
                raise ValueError(f"Unsupported storage backend: {self.storage_backend}")
        except Exception as e:
            current_app.logger.error(f"Failed to delete wizard data: {e}")
            return False
    
    def _save_to_session(self, wizard_data: WizardFormData) -> bool:
        """Save to Flask session"""
        session_key = f'wizard_{wizard_data.wizard_id}'
        session[session_key] = wizard_data.to_dict()
        return True
    
    def _load_from_session(self, wizard_id: str) -> Optional[WizardFormData]:
        """Load from Flask session"""
        session_key = f'wizard_{wizard_id}'
        data = session.get(session_key)
        if data:
            wizard_data = WizardFormData.from_dict(data)
            if not wizard_data.is_expired():
                return wizard_data
            else:
                self._delete_from_session(wizard_id)
        return None
    
    def _delete_from_session(self, wizard_id: str) -> bool:
        """Delete from Flask session"""
        session_key = f'wizard_{wizard_id}'
        if session_key in session:
            del session[session_key]
        return True
    
    def _save_to_database(self, wizard_data: WizardFormData) -> bool:
        """Save to database - implementation depends on your database setup"""
        # This would require a WizardFormData model
        # Implementation would vary based on your ORM (SQLAlchemy, etc.)
        # For now, fall back to session storage
        return self._save_to_session(wizard_data)
    
    def _load_from_database(self, wizard_id: str, user_id: Optional[str]) -> Optional[WizardFormData]:
        """Load from database - implementation depends on your database setup"""
        # This would query the WizardFormData model
        # For now, fall back to session storage
        return self._load_from_session(wizard_id)
    
    def _delete_from_database(self, wizard_id: str, user_id: Optional[str]) -> bool:
        """Delete from database - implementation depends on your database setup"""
        # This would delete the WizardFormData model instance
        # For now, fall back to session storage
        return self._delete_from_session(wizard_id)
    
    def _save_to_cache(self, wizard_data: WizardFormData) -> bool:
        """Save to cache (Redis, Memcached, etc.)"""
        # This would use Flask-Cache or similar
        # For now, fall back to session storage
        return self._save_to_session(wizard_data)
    
    def _load_from_cache(self, wizard_id: str, user_id: Optional[str]) -> Optional[WizardFormData]:
        """Load from cache"""
        # This would use Flask-Cache or similar
        # For now, fall back to session storage
        return self._load_from_session(wizard_id)
    
    def _delete_from_cache(self, wizard_id: str, user_id: Optional[str]) -> bool:
        """Delete from cache"""
        try:
            # Try to use Flask-Caching if available
            cache = None
            if hasattr(current_app, 'cache'):
                cache = current_app.cache
            elif hasattr(current_app, 'extensions') and 'cache' in current_app.extensions:
                cache = current_app.extensions['cache']
            
            if not cache:
                # Fall back to session storage if no cache available
                return self._delete_from_session(wizard_id)
            
            # Create cache key
            cache_key = f"wizard_{wizard_id}_{user_id or 'anonymous'}"
            
            # Delete from cache
            cache.delete(cache_key)
            return True
            
        except Exception as e:
            current_app.logger.error(f"Failed to delete wizard data from cache: {e}")
            # Fall back to session storage
            return self._delete_from_session(wizard_id)
    
    def _get_or_create_wizard_model(self):
        """Get or create the SQLAlchemy model for wizard data storage"""
        try:
            from flask_appbuilder import Model
            from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
            
            # Check if WizardData model already exists
            if hasattr(current_app, '_wizard_data_model'):
                return current_app._wizard_data_model
            
            # Create the model class dynamically
            class WizardData(Model):
                __tablename__ = 'ab_wizard_form_data'
                
                id = Column(Integer, primary_key=True)
                wizard_id = Column(String(100), nullable=False, index=True)
                user_id = Column(String(50), nullable=True, index=True)
                form_data = Column(Text, nullable=True)
                current_step = Column(Integer, default=0)
                completed_steps = Column(Text, nullable=True)  # JSON array
                created_at = Column(DateTime, nullable=False)
                updated_at = Column(DateTime, nullable=False)
                expires_at = Column(DateTime, nullable=False, index=True)
                is_submitted = Column(Boolean, default=False)
                submission_id = Column(String(100), nullable=True, unique=True)
                
                def __repr__(self):
                    return f'<WizardData {self.wizard_id}>'
            
            # Try to create the table if it doesn't exist
            try:
                if hasattr(current_app, 'appbuilder') and hasattr(current_app.appbuilder, 'get_session'):
                    engine = current_app.appbuilder.get_session.get_bind()
                    WizardData.__table__.create(engine, checkfirst=True)
            except Exception as table_error:
                current_app.logger.warning(f"Could not create wizard_form_data table: {table_error}")
                return None
            
            # Cache the model class
            current_app._wizard_data_model = WizardData
            return WizardData
            
        except Exception as e:
            current_app.logger.error(f"Failed to create wizard data model: {e}")
            return None
    
    def cleanup_expired_data(self) -> int:
        """Clean up expired wizard data entries"""
        """Returns number of cleaned up entries"""
        try:
            if self.storage_backend == 'database':
                return self._cleanup_expired_database_data()
            elif self.storage_backend == 'cache':
                # Cache entries expire automatically
                return 0
            else:
                # Session data cleanup is handled by Flask
                return 0
                
        except Exception as e:
            current_app.logger.error(f"Failed to cleanup expired wizard data: {e}")
            return 0
    
    def _cleanup_expired_database_data(self) -> int:
        """Clean up expired database entries"""
        try:
            if hasattr(current_app, 'appbuilder') and hasattr(current_app.appbuilder, 'get_session'):
                session = current_app.appbuilder.get_session
            else:
                return 0
            
            wizard_model = self._get_or_create_wizard_model()
            if not wizard_model:
                return 0
            
            # Delete expired records
            expired_count = session.query(wizard_model).filter(
                wizard_model.expires_at < datetime.now(tz=timezone.utc)
            ).count()
            
            session.query(wizard_model).filter(
                wizard_model.expires_at < datetime.now(tz=timezone.utc)
            ).delete()
            
            session.commit()
            return expired_count
            
        except Exception as e:
            current_app.logger.error(f"Failed to cleanup expired database data: {e}")
            if 'session' in locals():
                session.rollback()
            return 0


class WizardForm(Form):
    """
    Multi-step wizard form with session persistence
    
    Automatically splits large forms into manageable steps and provides
    navigation, validation, and data persistence capabilities.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize wizard form"""
        # Extract wizard-specific parameters
        self.fields_per_step = kwargs.pop('fields_per_step', 10)
        self.wizard_id = kwargs.pop('wizard_id', str(uuid.uuid4()))
        self.wizard_title = kwargs.pop('wizard_title', 'Form Wizard')
        self.wizard_description = kwargs.pop('wizard_description', '')
        self.auto_save_interval = kwargs.pop('auto_save_interval', 30000)  # 30 seconds
        self.allow_step_navigation = kwargs.pop('allow_step_navigation', True)
        self.require_step_completion = kwargs.pop('require_step_completion', True)
        self.custom_steps = kwargs.pop('custom_steps', None)
        self.storage_backend = kwargs.pop('storage_backend', 'session')
        self.expiration_days = kwargs.pop('expiration_days', 7)
        
        super().__init__(*args, **kwargs)
        
        # Initialize wizard components
        self.persistence = WizardFormPersistence(self.storage_backend)
        self.steps = []
        self.current_step_index = 0
        self.wizard_data = None
        
        # Add wizard control fields
        self.wizard_id_field = HiddenField('wizard_id', default=self.wizard_id)
        self.current_step_field = HiddenField('current_step', default='0')
        self.wizard_action = HiddenField('wizard_action', default='next')
        
        # Initialize steps and load existing data
        self._initialize_steps()
        self._load_wizard_data()
    
    def _initialize_steps(self):
        """Initialize wizard steps based on form fields"""
        if self.custom_steps:
            # Use custom step definitions
            self.steps = self.custom_steps
        else:
            # Auto-generate steps based on field count
            self.steps = self._auto_generate_steps()
        
        # Ensure steps are properly configured
        for i, step in enumerate(self.steps):
            if not isinstance(step, WizardStep):
                # Convert dictionary to WizardStep if needed
                if isinstance(step, dict):
                    self.steps[i] = WizardStep(**step)
    
    def _auto_generate_steps(self) -> List[WizardStep]:
        """Automatically generate steps based on form fields"""
        steps = []
        field_names = [name for name, field in self._fields.items() 
                      if not name.startswith('wizard_') and not isinstance(field, HiddenField)]
        
        # Group fields into steps
        for i in range(0, len(field_names), self.fields_per_step):
            step_fields = field_names[i:i + self.fields_per_step]
            step_name = f'step_{i // self.fields_per_step + 1}'
            step_title = f'Step {i // self.fields_per_step + 1}'
            
            # Determine required fields for this step
            required_fields = []
            for field_name in step_fields:
                field = self._fields.get(field_name)
                if field and hasattr(field, 'validators'):
                    for validator in field.validators:
                        if isinstance(validator, DataRequired):
                            required_fields.append(field_name)
                            break
            
            step = WizardStep(
                name=step_name,
                title=step_title,
                fields=step_fields,
                required_fields=required_fields,
                description=f'Complete fields {i + 1} to {min(i + self.fields_per_step, len(field_names))}'
            )
            steps.append(step)
        
        return steps
    
    def _load_wizard_data(self):
        """Load existing wizard data if available"""
        user_id = str(current_user.id) if current_user and current_user.is_authenticated else None
        logger.debug(f"Loading wizard data for wizard_id: {self.wizard_id}, user_id: {user_id}")
        
        self.wizard_data = self.persistence.load_wizard_data(self.wizard_id, user_id)
        
        if self.wizard_data:
            logger.info(f"Loaded existing wizard data with {len(self.wizard_data.form_data)} fields, current step: {self.wizard_data.current_step}")
            # Populate form with existing data
            for field_name, value in self.wizard_data.form_data.items():
                if field_name in self._fields:
                    self._fields[field_name].data = value
            
            self.current_step_index = self.wizard_data.current_step
            self.current_step_field.data = str(self.current_step_index)
        else:
            logger.debug(f"Creating new wizard data for wizard_id: {self.wizard_id}")
            # Initialize new wizard data
            user_id = str(current_user.id) if current_user and current_user.is_authenticated else None
            self.wizard_data = WizardFormData(self.wizard_id, user_id)
    
    def save_wizard_data(self) -> bool:
        """Save current wizard state"""
        if not self.wizard_data:
            logger.error("Cannot save wizard data: wizard_data is None")
            return False
        
        logger.debug(f"Saving wizard data for step {self.current_step_index}")
        
        # Update wizard data with current form data
        current_step_data = self.get_current_step_data()
        self.wizard_data.update_data(current_step_data, self.current_step_index)
        self.wizard_data.set_current_step(self.current_step_index)
        
        # Save to persistence backend
        success = self.persistence.save_wizard_data(self.wizard_data)
        
        if success:
            logger.debug(f"Successfully saved wizard data for {self.wizard_id}")
        else:
            logger.error(f"Failed to save wizard data for {self.wizard_id}")
            
        return success
    
    def get_current_step(self) -> Optional[WizardStep]:
        """Get the current wizard step"""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None
    
    def get_current_step_data(self) -> Dict[str, Any]:
        """Get form data for the current step"""
        current_step = self.get_current_step()
        if not current_step:
            return {}
        
        step_data = {}
        for field_name in current_step.fields:
            if field_name in self._fields:
                field = self._fields[field_name]
                step_data[field_name] = field.data
        
        return step_data
    
    def validate_current_step(self) -> bool:
        """Validate the current step"""
        current_step = self.get_current_step()
        if not current_step:
            return False
        
        # Get current step data
        step_data = self.get_current_step_data()
        
        # Validate step
        is_valid, errors = current_step.validate_step(step_data)
        
        # Apply errors to form fields
        for field_name, field_errors in errors.items():
            if field_name in self._fields:
                field = self._fields[field_name]
                field.errors.extend(field_errors)
        
        return is_valid
    
    def can_proceed_to_next_step(self) -> bool:
        """Check if user can proceed to the next step"""
        if not self.require_step_completion:
            return True
        
        return self.validate_current_step()
    
    def can_go_to_previous_step(self) -> bool:
        """Check if user can go to the previous step"""
        return self.current_step_index > 0
    
    def can_navigate_to_step(self, step_index: int) -> bool:
        """Check if user can navigate directly to a specific step"""
        if not self.allow_step_navigation:
            return False
        
        # Can always go to previous steps
        if step_index <= self.current_step_index:
            return True
        
        # For future steps, check if all previous steps are completed
        if self.require_step_completion:
            for i in range(step_index):
                if i not in self.wizard_data.completed_steps:
                    return False
        
        return True
    
    def next_step(self) -> bool:
        """Move to the next step"""
        if self.current_step_index < len(self.steps) - 1:
            if self.can_proceed_to_next_step():
                self.current_step_index += 1
                self.current_step_field.data = str(self.current_step_index)
                self.save_wizard_data()
                return True
        return False
    
    def previous_step(self) -> bool:
        """Move to the previous step"""
        if self.can_go_to_previous_step():
            self.current_step_index -= 1
            self.current_step_field.data = str(self.current_step_index)
            self.save_wizard_data()
            return True
        return False
    
    def goto_step(self, step_index: int) -> bool:
        """Navigate directly to a specific step"""
        if self.can_navigate_to_step(step_index):
            self.current_step_index = step_index
            self.current_step_field.data = str(self.current_step_index)
            self.save_wizard_data()
            return True
        return False
    
    def is_final_step(self) -> bool:
        """Check if this is the final step"""
        return self.current_step_index == len(self.steps) - 1
    
    def get_progress_percentage(self) -> float:
        """Calculate overall wizard completion percentage"""
        if not self.steps:
            return 0.0
        
        total_progress = 0.0
        for i, step in enumerate(self.steps):
            step_data = {}
            if self.wizard_data:
                step_data = self.wizard_data.get_step_data(step.fields)
            
            step_progress = step.get_progress_percentage(step_data)
            
            # Weight current and future steps appropriately
            if i < self.current_step_index:
                # Completed steps count as 100%
                total_progress += 100.0
            elif i == self.current_step_index:
                # Current step uses actual progress
                total_progress += step_progress
            # Future steps count as 0%
        
        return total_progress / len(self.steps)
    
    def get_step_status(self, step_index: int) -> str:
        """Get the status of a specific step"""
        if step_index < self.current_step_index:
            return 'completed'
        elif step_index == self.current_step_index:
            return 'current'
        elif self.wizard_data and step_index in self.wizard_data.completed_steps:
            return 'completed'
        else:
            return 'pending'
    
    def validate(self) -> bool:
        """Validate the entire wizard form"""
        if self.is_final_step():
            # On final step, validate all steps
            all_valid = True
            for step in self.steps:
                step_data = self.wizard_data.get_step_data(step.fields) if self.wizard_data else {}
                is_valid, _ = step.validate_step(step_data)
                if not is_valid:
                    all_valid = False
            return all_valid
        else:
            # Validate only current step
            return self.validate_current_step()
    
    def submit_wizard(self) -> Optional[str]:
        """Submit the completed wizard"""
        if not self.is_final_step():
            logger.warning(f"Attempted to submit wizard on non-final step {self.current_step_index}")
            return None
        
        if not self.validate():
            logger.warning(f"Wizard validation failed during submission")
            return None
        
        logger.info(f"Submitting wizard {self.wizard_id}")
        
        # Mark as submitted
        submission_id = str(uuid.uuid4())
        self.wizard_data.mark_submitted(submission_id)
        
        if self.persistence.save_wizard_data(self.wizard_data):
            logger.info(f"Wizard {self.wizard_id} submitted successfully with ID {submission_id}")
            return submission_id
        else:
            logger.error(f"Failed to save submitted wizard data for {self.wizard_id}")
            return None
    
    def cleanup_wizard_data(self):
        """Clean up wizard data after successful submission"""
        if self.wizard_data and self.wizard_data.is_submitted:
            user_id = str(current_user.id) if current_user and current_user.is_authenticated else None
            self.persistence.delete_wizard_data(self.wizard_id, user_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert wizard form to dictionary for API/serialization"""
        return {
            'wizard_id': self.wizard_id,
            'wizard_title': self.wizard_title,
            'wizard_description': self.wizard_description,
            'current_step_index': self.current_step_index,
            'total_steps': len(self.steps),
            'steps': [step.to_dict() for step in self.steps],
            'progress_percentage': self.get_progress_percentage(),
            'is_final_step': self.is_final_step(),
            'can_navigate': self.allow_step_navigation,
            'require_completion': self.require_step_completion,
            'auto_save_interval': self.auto_save_interval,
            'wizard_data': self.wizard_data.to_dict() if self.wizard_data else None
        }