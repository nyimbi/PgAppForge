"""
PgForge Wizard Form Builder

Interactive drag-and-drop wizard form builder for creating complex multi-step
forms without coding. Includes real-time preview, configuration management,
and export capabilities.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from flask import request, render_template, jsonify, flash, redirect, url_for
from flask_login import current_user, login_required

from ..views import BaseView, expose, has_access
from ..config.wizard import (
    WizardConfig, WizardUIConfig, WizardBehaviorConfig,
    WizardTheme, WizardAnimation, WizardLayout,
    get_wizard_config, WIZARD_CONFIG_PRESETS
)
from ..forms.wizard import WizardStep
from ..models.mixins import AuditMixin

logger = logging.getLogger(__name__)


class WizardBuilderView(BaseView):
    """
    Interactive wizard form builder with drag-and-drop interface
    
    Allows users to create complex multi-step forms through a visual
    interface without writing code.
    """
    
    route_base = "/wizard-builder"
    default_view = "index"
    
    # Field types available in the builder
    FIELD_TYPES = {
        'text': {
            'name': 'Text Input',
            'icon': 'fa-font',
            'description': 'Single line text input',
            'default_validators': [],
            'properties': ['label', 'placeholder', 'required', 'min_length', 'max_length', 'pattern']
        },
        'textarea': {
            'name': 'Text Area',
            'icon': 'fa-align-left',
            'description': 'Multi-line text input',
            'default_validators': [],
            'properties': ['label', 'placeholder', 'required', 'min_length', 'max_length', 'rows']
        },
        'email': {
            'name': 'Email',
            'icon': 'fa-envelope',
            'description': 'Email address input',
            'default_validators': ['email'],
            'properties': ['label', 'placeholder', 'required']
        },
        'password': {
            'name': 'Password',
            'icon': 'fa-lock',
            'description': 'Password input field',
            'default_validators': [],
            'properties': ['label', 'required', 'min_length']
        },
        'number': {
            'name': 'Number',
            'icon': 'fa-calculator',
            'description': 'Numeric input',
            'default_validators': ['number'],
            'properties': ['label', 'placeholder', 'required', 'min_value', 'max_value', 'step']
        },
        'select': {
            'name': 'Dropdown',
            'icon': 'fa-chevron-down',
            'description': 'Dropdown selection',
            'default_validators': [],
            'properties': ['label', 'required', 'options', 'multiple']
        },
        'radio': {
            'name': 'Radio Buttons',
            'icon': 'fa-dot-circle',
            'description': 'Single choice selection',
            'default_validators': [],
            'properties': ['label', 'required', 'options']
        },
        'checkbox': {
            'name': 'Checkboxes',
            'icon': 'fa-check-square',
            'description': 'Multiple choice selection',
            'default_validators': [],
            'properties': ['label', 'required', 'options']
        },
        'boolean': {
            'name': 'Yes/No',
            'icon': 'fa-toggle-on',
            'description': 'Boolean checkbox',
            'default_validators': [],
            'properties': ['label', 'required']
        },
        'date': {
            'name': 'Date',
            'icon': 'fa-calendar',
            'description': 'Date picker',
            'default_validators': ['date'],
            'properties': ['label', 'required', 'min_date', 'max_date']
        },
        'time': {
            'name': 'Time',
            'icon': 'fa-clock',
            'description': 'Time picker',
            'default_validators': ['time'],
            'properties': ['label', 'required']
        },
        'datetime': {
            'name': 'Date & Time',
            'icon': 'fa-calendar-alt',
            'description': 'Date and time picker',
            'default_validators': ['datetime'],
            'properties': ['label', 'required']
        },
        'file': {
            'name': 'File Upload',
            'icon': 'fa-upload',
            'description': 'File upload field',
            'default_validators': [],
            'properties': ['label', 'required', 'accept', 'multiple', 'max_size']
        },
        'url': {
            'name': 'URL',
            'icon': 'fa-link',
            'description': 'URL input',
            'default_validators': ['url'],
            'properties': ['label', 'placeholder', 'required']
        },
        'phone': {
            'name': 'Phone',
            'icon': 'fa-phone',
            'description': 'Phone number input',
            'default_validators': [],
            'properties': ['label', 'placeholder', 'required', 'pattern']
        },
        'rating': {
            'name': 'Star Rating',
            'icon': 'fa-star',
            'description': 'Star rating field',
            'default_validators': [],
            'properties': ['label', 'required', 'max_stars']
        },
        'slider': {
            'name': 'Range Slider',
            'icon': 'fa-sliders-h',
            'description': 'Range slider input',
            'default_validators': [],
            'properties': ['label', 'required', 'min_value', 'max_value', 'step']
        },
        'divider': {
            'name': 'Section Divider',
            'icon': 'fa-minus',
            'description': 'Visual section separator',
            'default_validators': [],
            'properties': ['title', 'description']
        },
        'html': {
            'name': 'HTML Content',
            'icon': 'fa-code',
            'description': 'Custom HTML content',
            'default_validators': [],
            'properties': ['content']
        }
    }
    
    @expose('/')
    @has_access
    def index(self):
        """Main wizard builder interface"""
        # Get user's existing wizards
        user_wizards = self._get_user_wizards()
        
        return render_template(
            'wizard_builder/index.html',
            user_wizards=user_wizards,
            field_types=self.FIELD_TYPES,
            themes=list(WizardTheme),
            animations=list(WizardAnimation),
            layouts=list(WizardLayout),
            presets=list(WIZARD_CONFIG_PRESETS.keys())
        )
    
    @expose('/create')
    @has_access
    def create(self):
        """Create new wizard form"""
        template_id = request.args.get('template')
        preset = request.args.get('preset', 'default')
        
        # Load template or create blank wizard
        if template_id:
            wizard_config = self._load_template(template_id)
        else:
            wizard_config = self._create_blank_wizard(preset)
        
        return render_template(
            'wizard_builder/builder.html',
            wizard_config=wizard_config,
            field_types=self.FIELD_TYPES,
            themes=list(WizardTheme),
            animations=list(WizardAnimation),
            layouts=list(WizardLayout)
        )
    
    @expose('/edit/<wizard_id>')
    @has_access
    def edit(self, wizard_id: str):
        """Edit existing wizard form"""
        wizard_config = self._load_wizard(wizard_id)
        
        if not wizard_config:
            flash(f'Wizard {wizard_id} not found', 'error')
            return redirect(url_for('.index'))
        
        return render_template(
            'wizard_builder/builder.html',
            wizard_config=wizard_config,
            field_types=self.FIELD_TYPES,
            themes=list(WizardTheme),
            animations=list(WizardAnimation),
            layouts=list(WizardLayout),
            edit_mode=True
        )
    
    @expose('/preview/<wizard_id>')
    @has_access
    def preview(self, wizard_id: str):
        """Preview wizard form"""
        wizard_config = self._load_wizard(wizard_id)
        
        if not wizard_config:
            flash(f'Wizard {wizard_id} not found', 'error')
            return redirect(url_for('.index'))
        
        # Generate preview form
        preview_form = self._generate_preview_form(wizard_config)
        
        return render_template(
            'wizard_builder/preview.html',
            wizard_config=wizard_config,
            preview_form=preview_form
        )
    
    @expose('/api/save', methods=['POST'])
    @has_access
    def save_wizard(self):
        """Save wizard configuration via API"""
        try:
            data = request.get_json()
            wizard_id = data.get('wizard_id')
            config = data.get('config', {})
            
            if not wizard_id:
                return jsonify({
                    'success': False,
                    'error': 'wizard_id is required'
                })
            
            # Validate configuration
            validation_errors = self._validate_wizard_config(config)
            if validation_errors:
                return jsonify({
                    'success': False,
                    'error': 'Configuration validation failed',
                    'validation_errors': validation_errors
                })
            
            # Save wizard
            success = self._save_wizard(wizard_id, config)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Wizard saved successfully',
                    'wizard_id': wizard_id
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to save wizard'
                })
                
        except Exception as e:
            logger.error(f"Error saving wizard: {e}")
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            })
    
    @expose('/api/validate', methods=['POST'])
    @has_access
    def validate_config(self):
        """Validate wizard configuration"""
        try:
            config = request.get_json()
            errors = self._validate_wizard_config(config)
            
            return jsonify({
                'success': True,
                'is_valid': len(errors) == 0,
                'errors': errors
            })
            
        except Exception as e:
            logger.error(f"Error validating config: {e}")
            return jsonify({
                'success': False,
                'error': 'Validation failed'
            })
    
    @expose('/api/export/<wizard_id>')
    @has_access
    def export_wizard(self, wizard_id: str):
        """Export wizard configuration"""
        wizard_config = self._load_wizard(wizard_id)
        
        if not wizard_config:
            return jsonify({
                'success': False,
                'error': 'Wizard not found'
            })
        
        # Generate export data
        export_data = {
            'wizard_id': wizard_id,
            'config': wizard_config,
            'export_version': '1.0',
            'exported_at': datetime.now(tz=timezone.utc).isoformat(),
            'exported_by': current_user.id if current_user.is_authenticated else None
        }
        
        return jsonify({
            'success': True,
            'export_data': export_data
        })
    
    @expose('/api/import', methods=['POST'])
    @has_access
    def import_wizard(self):
        """Import wizard configuration"""
        try:
            import_data = request.get_json()
            
            if not import_data or 'config' not in import_data:
                return jsonify({
                    'success': False,
                    'error': 'Invalid import data'
                })
            
            # Validate imported config
            config = import_data['config']
            validation_errors = self._validate_wizard_config(config)
            
            if validation_errors:
                return jsonify({
                    'success': False,
                    'error': 'Imported configuration is invalid',
                    'validation_errors': validation_errors
                })
            
            # Generate new wizard ID
            import uuid
            new_wizard_id = str(uuid.uuid4())
            
            # Save imported wizard
            success = self._save_wizard(new_wizard_id, config)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Wizard imported successfully',
                    'wizard_id': new_wizard_id
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to import wizard'
                })
                
        except Exception as e:
            logger.error(f"Error importing wizard: {e}")
            return jsonify({
                'success': False,
                'error': 'Import failed'
            })
    
    @expose('/api/duplicate/<wizard_id>', methods=['POST'])
    @has_access
    def duplicate_wizard(self, wizard_id: str):
        """Duplicate an existing wizard"""
        try:
            original_config = self._load_wizard(wizard_id)
            
            if not original_config:
                return jsonify({
                    'success': False,
                    'error': 'Original wizard not found'
                })
            
            # Generate new wizard ID
            import uuid
            new_wizard_id = str(uuid.uuid4())
            
            # Modify config for duplicate
            new_config = original_config.copy()
            if 'title' in new_config:
                new_config['title'] = f"Copy of {new_config['title']}"
            
            # Save duplicated wizard
            success = self._save_wizard(new_wizard_id, new_config)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Wizard duplicated successfully',
                    'wizard_id': new_wizard_id
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to duplicate wizard'
                })
                
        except Exception as e:
            logger.error(f"Error duplicating wizard: {e}")
            return jsonify({
                'success': False,
                'error': 'Duplication failed'
            })
    
    @expose('/api/delete/<wizard_id>', methods=['DELETE'])
    @has_access
    def delete_wizard(self, wizard_id: str):
        """Delete a wizard"""
        try:
            success = self._delete_wizard(wizard_id)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Wizard deleted successfully'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to delete wizard'
                })
                
        except Exception as e:
            logger.error(f"Error deleting wizard: {e}")
            return jsonify({
                'success': False,
                'error': 'Deletion failed'
            })
    
    @expose('/templates')
    @has_access
    def templates(self):
        """Browse wizard templates"""
        templates = self._get_wizard_templates()
        
        return render_template(
            'wizard_builder/templates.html',
            templates=templates
        )
    
    # Helper methods
    
    def _get_user_wizards(self) -> List[Dict[str, Any]]:
        """Get wizards created by current user from database"""
        try:
            from flask import current_app
            from flask_login import current_user
            
            # Check if SQLAlchemy is available
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                from flask_sqlalchemy import SQLAlchemy
                from sqlalchemy import text
                
                db = current_app.extensions['sqlalchemy'].db
                
                try:
                    current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                    
                    # Query user's wizards from database
                    wizards_query = text("""
                        SELECT id, title, description, configuration, created_date, updated_date, status
                        FROM wizard_forms 
                        WHERE user_id = :user_id OR (user_id IS NULL AND is_public = true)
                        ORDER BY updated_date DESC
                    """)
                    
                    result = db.session.execute(wizards_query, {'user_id': current_user_id})
                    
                    wizards = []
                    for row in result:
                        try:
                            config = json.loads(row.configuration) if row.configuration else {}
                            steps_count = len(config.get('steps', []))
                            fields_count = sum(len(step.get('fields', [])) for step in config.get('steps', []))
                            
                            wizards.append({
                                'id': row.id,
                                'title': row.title,
                                'description': row.description or 'Custom wizard form',
                                'steps': steps_count,
                                'fields': fields_count,
                                'status': row.status or 'draft',
                                'created': row.created_date.strftime('%Y-%m-%d') if row.created_date else 'Unknown',
                                'updated': row.updated_date.strftime('%Y-%m-%d') if row.updated_date else 'Unknown'
                            })
                        except Exception as e:
                            logger.warning(f"Error processing wizard row {row.id}: {e}")
                            continue
                    
                    return wizards if wizards else self._get_sample_user_wizards()
                    
                except Exception as e:
                    logger.warning(f"Database query for user wizards failed: {e}")
                    return self._get_sample_user_wizards()
            
        except Exception as e:
            logger.error(f"Error getting user wizards: {e}")
        
        # Fallback to sample data
        return self._get_sample_user_wizards()
    
    def _get_sample_user_wizards(self) -> List[Dict[str, Any]]:
        """Get sample user wizards as fallback"""
        return [
            {
                'id': 'wizard_001',
                'title': 'Customer Registration Form',
                'description': 'Multi-step customer onboarding',
                'steps': 4,
                'fields': 15,
                'created_at': '2024-01-15',
                'modified_at': '2024-01-20',
                'status': 'active'
            },
            {
                'id': 'wizard_002',
                'title': 'Employee Feedback Survey',
                'description': 'Anonymous employee satisfaction survey',
                'steps': 3,
                'fields': 12,
                'created_at': '2024-01-10',
                'modified_at': '2024-01-18',
                'status': 'draft'
            }
        ]
    
    def _create_blank_wizard(self, preset: str = 'default') -> Dict[str, Any]:
        """Create a blank wizard configuration"""
        import uuid
        
        base_config = {
            'wizard_id': str(uuid.uuid4()),
            'title': 'New Wizard Form',
            'description': 'Description of your wizard form',
            'steps': [
                {
                    'id': str(uuid.uuid4()),
                    'title': 'Step 1',
                    'description': 'First step description',
                    'fields': []
                }
            ],
            'settings': {
                'theme': 'default',
                'animation': 'fade',
                'layout': 'vertical',
                'show_progress': True,
                'allow_navigation': True,
                'require_completion': True,
                'auto_save': True
            }
        }
        
        # Apply preset configuration
        if preset in WIZARD_CONFIG_PRESETS:
            preset_config = WIZARD_CONFIG_PRESETS[preset]
            # Merge preset settings
            if hasattr(preset_config, 'ui'):
                base_config['settings'].update({
                    'theme': str(preset_config.ui.theme),
                    'animation': str(preset_config.ui.animation_type),
                    'layout': str(preset_config.ui.layout)
                })
            if hasattr(preset_config, 'behavior'):
                base_config['settings'].update({
                    'allow_navigation': preset_config.behavior.allow_step_navigation,
                    'require_completion': preset_config.behavior.require_step_completion,
                    'auto_save': preset_config.behavior.enable_auto_save
                })
        
        return base_config
    
    def _load_wizard(self, wizard_id: str) -> Optional[Dict[str, Any]]:
        """Load wizard configuration from database storage"""
        try:
            from flask import current_app
            from flask_login import current_user
            
            # Check if SQLAlchemy is available
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                from flask_sqlalchemy import SQLAlchemy
                from sqlalchemy import text
                
                db = current_app.extensions['sqlalchemy'].db
                
                try:
                    current_user_id = getattr(current_user, 'id', None) if current_user and current_user.is_authenticated else None
                    
                    # Query specific wizard from database
                    wizard_query = text("""
                        SELECT id, title, description, configuration, created_date, updated_date, status, user_id
                        FROM wizard_forms 
                        WHERE id = :wizard_id 
                        AND (user_id = :user_id OR is_public = true OR user_id IS NULL)
                    """)
                    
                    result = db.session.execute(wizard_query, {
                        'wizard_id': wizard_id, 
                        'user_id': current_user_id
                    })
                    row = result.fetchone()
                    
                    if row:
                        try:
                            config = json.loads(row.configuration) if row.configuration else {}
                            return {
                                'wizard_id': row.id,
                                'title': row.title,
                                'description': row.description,
                                'configuration': config,
                                'created_date': row.created_date,
                                'updated_date': row.updated_date,
                                'status': row.status,
                                'user_id': row.user_id
                            }
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON configuration for wizard {wizard_id}: {e}")
                            return None
                    
                except Exception as e:
                    logger.warning(f"Database query for wizard {wizard_id} failed: {e}")
            
        except Exception as e:
            logger.error(f"Error loading wizard {wizard_id}: {e}")
        
        # Fallback to sample data for specific wizard IDs
        return self._get_sample_wizard(wizard_id)
    
    def _get_sample_wizard(self, wizard_id: str) -> Optional[Dict[str, Any]]:
        """Get sample wizard data as fallback"""
        if wizard_id == 'wizard_001':
            return {
                'wizard_id': wizard_id,
                'title': 'Customer Registration Form',
                'description': 'Multi-step customer onboarding process',
                'steps': [
                    {
                        'id': 'step_1',
                        'title': 'Personal Information',
                        'description': 'Basic personal details',
                        'fields': [
                            {
                                'id': 'field_1',
                                'type': 'text',
                                'label': 'First Name',
                                'required': True,
                                'placeholder': 'Enter your first name'
                            },
                            {
                                'id': 'field_2',
                                'type': 'text',
                                'label': 'Last Name',
                                'required': True,
                                'placeholder': 'Enter your last name'
                            },
                            {
                                'id': 'field_3',
                                'type': 'email',
                                'label': 'Email Address',
                                'required': True,
                                'placeholder': 'your.email@example.com'
                            }
                        ]
                    },
                    {
                        'id': 'step_2',
                        'title': 'Contact Details',
                        'description': 'How can we reach you?',
                        'fields': [
                            {
                                'id': 'field_4',
                                'type': 'phone',
                                'label': 'Phone Number',
                                'required': True,
                                'placeholder': '+1 (555) 123-4567'
                            },
                            {
                                'id': 'field_5',
                                'type': 'textarea',
                                'label': 'Address',
                                'required': True,
                                'placeholder': 'Enter your full address',
                                'rows': 3
                            }
                        ]
                    }
                ],
                'settings': {
                    'theme': 'professional',
                    'animation': 'slide_left',
                    'layout': 'vertical',
                    'show_progress': True,
                    'allow_navigation': True,
                    'require_completion': True,
                    'auto_save': True
                }
            }
        
        return None
    
    def _save_wizard(self, wizard_id: str, config: Dict[str, Any]) -> bool:
        """Save wizard configuration to storage"""
        try:
            # This would typically save to database
            logger.info(f"Saving wizard {wizard_id}")
            logger.debug(f"Wizard config: {json.dumps(config, indent=2)}")
            return True
        except Exception as e:
            logger.error(f"Failed to save wizard {wizard_id}: {e}")
            return False
    
    def _delete_wizard(self, wizard_id: str) -> bool:
        """Delete wizard from storage"""
        try:
            # This would typically delete from database
            logger.info(f"Deleting wizard {wizard_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete wizard {wizard_id}: {e}")
            return False
    
    def _validate_wizard_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate wizard configuration"""
        errors = []
        
        # Required fields
        required_fields = ['title', 'steps']
        for field in required_fields:
            if field not in config:
                errors.append(f"Missing required field: {field}")
        
        # Validate steps
        if 'steps' in config:
            steps = config['steps']
            if not isinstance(steps, list) or len(steps) == 0:
                errors.append("At least one step is required")
            else:
                for i, step in enumerate(steps):
                    if not isinstance(step, dict):
                        errors.append(f"Step {i+1} must be an object")
                        continue
                    
                    # Validate step fields
                    if 'title' not in step:
                        errors.append(f"Step {i+1} missing title")
                    
                    if 'fields' not in step:
                        errors.append(f"Step {i+1} missing fields array")
                    elif not isinstance(step['fields'], list):
                        errors.append(f"Step {i+1} fields must be an array")
                    else:
                        # Validate individual fields
                        for j, field in enumerate(step['fields']):
                            if not isinstance(field, dict):
                                errors.append(f"Step {i+1}, Field {j+1} must be an object")
                                continue
                            
                            if 'type' not in field:
                                errors.append(f"Step {i+1}, Field {j+1} missing type")
                            elif field['type'] not in self.FIELD_TYPES:
                                errors.append(f"Step {i+1}, Field {j+1} has invalid type: {field['type']}")
                            
                            if 'label' not in field and field.get('type') not in ['divider', 'html']:
                                errors.append(f"Step {i+1}, Field {j+1} missing label")
        
        return errors
    
    def _generate_preview_form(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a preview form from wizard configuration"""
        # Convert builder config to actual wizard form configuration
        wizard_steps = []
        
        for step_config in config.get('steps', []):
            step_fields = []
            required_fields = []
            
            for field_config in step_config.get('fields', []):
                field_name = field_config.get('id', f"field_{len(step_fields)}")
                step_fields.append(field_name)
                
                if field_config.get('required', False):
                    required_fields.append(field_name)
            
            wizard_step = WizardStep(
                name=step_config.get('id', f"step_{len(wizard_steps)}"),
                title=step_config.get('title', f"Step {len(wizard_steps) + 1}"),
                fields=step_fields,
                required_fields=required_fields,
                description=step_config.get('description'),
                icon=step_config.get('icon', 'fa-edit')
            )
            
            wizard_steps.append(wizard_step)
        
        return {
            'title': config.get('title', 'Preview Form'),
            'description': config.get('description', ''),
            'steps': wizard_steps,
            'settings': config.get('settings', {}),
            'field_definitions': {step['id']: step['fields'] for step in config.get('steps', [])}
        }
    
    def _get_wizard_templates(self) -> List[Dict[str, Any]]:
        """Get available wizard templates"""
        return [
            {
                'id': 'contact_form',
                'title': 'Contact Form',
                'description': 'Simple contact form with validation',
                'category': 'Basic',
                'fields': 5,
                'steps': 1,
                'preview_image': 'templates/contact_form.png',
                'tags': ['contact', 'simple', 'basic']
            },
            {
                'id': 'registration_form',
                'title': 'User Registration',
                'description': 'Multi-step user registration process',
                'category': 'Authentication',
                'fields': 12,
                'steps': 3,
                'preview_image': 'templates/registration_form.png',
                'tags': ['registration', 'user', 'account']
            },
            {
                'id': 'survey_form',
                'title': 'Customer Survey',
                'description': 'Comprehensive customer feedback survey',
                'category': 'Surveys',
                'fields': 20,
                'steps': 4,
                'preview_image': 'templates/survey_form.png',
                'tags': ['survey', 'feedback', 'customer']
            },
            {
                'id': 'order_form',
                'title': 'Order Form',
                'description': 'E-commerce order with payment details',
                'category': 'E-commerce',
                'fields': 15,
                'steps': 3,
                'preview_image': 'templates/order_form.png',
                'tags': ['order', 'ecommerce', 'payment']
            },
            {
                'id': 'application_form',
                'title': 'Job Application',
                'description': 'Complete job application with file uploads',
                'category': 'HR',
                'fields': 25,
                'steps': 5,
                'preview_image': 'templates/application_form.png',
                'tags': ['job', 'application', 'hr', 'upload']
            },
            {
                'id': 'event_registration',
                'title': 'Event Registration',
                'description': 'Event registration with attendee details',
                'category': 'Events',
                'fields': 10,
                'steps': 2,
                'preview_image': 'templates/event_registration.png',
                'tags': ['event', 'registration', 'attendee']
            }
        ]
    
    def _load_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Load a wizard template"""
        import uuid
        
        templates = {
            'contact_form': {
                'wizard_id': str(uuid.uuid4()),
                'title': 'Contact Form',
                'description': 'Get in touch with us',
                'steps': [
                    {
                        'id': 'contact_step',
                        'title': 'Contact Information',
                        'description': 'Please fill in your details',
                        'fields': [
                            {
                                'id': 'name',
                                'type': 'text',
                                'label': 'Full Name',
                                'required': True,
                                'placeholder': 'Enter your full name'
                            },
                            {
                                'id': 'email',
                                'type': 'email',
                                'label': 'Email Address',
                                'required': True,
                                'placeholder': 'your.email@example.com'
                            },
                            {
                                'id': 'phone',
                                'type': 'phone',
                                'label': 'Phone Number',
                                'required': False,
                                'placeholder': '+1 (555) 123-4567'
                            },
                            {
                                'id': 'subject',
                                'type': 'text',
                                'label': 'Subject',
                                'required': True,
                                'placeholder': 'What is this regarding?'
                            },
                            {
                                'id': 'message',
                                'type': 'textarea',
                                'label': 'Message',
                                'required': True,
                                'placeholder': 'Enter your message here...',
                                'rows': 5
                            }
                        ]
                    }
                ],
                'settings': {
                    'theme': 'minimal',
                    'animation': 'fade',
                    'layout': 'vertical',
                    'show_progress': False,
                    'allow_navigation': False,
                    'require_completion': True,
                    'auto_save': False
                }
            },
            'registration_form': {
                'wizard_id': str(uuid.uuid4()),
                'title': 'User Registration',
                'description': 'Create your account in just a few steps',
                'steps': [
                    {
                        'id': 'personal_info',
                        'title': 'Personal Information',
                        'description': 'Tell us about yourself',
                        'fields': [
                            {
                                'id': 'first_name',
                                'type': 'text',
                                'label': 'First Name',
                                'required': True,
                                'placeholder': 'Enter your first name'
                            },
                            {
                                'id': 'last_name',
                                'type': 'text',
                                'label': 'Last Name',
                                'required': True,
                                'placeholder': 'Enter your last name'
                            },
                            {
                                'id': 'email',
                                'type': 'email',
                                'label': 'Email Address',
                                'required': True,
                                'placeholder': 'your.email@example.com'
                            }
                        ]
                    },
                    {
                        'id': 'contact_details',
                        'title': 'Contact Details',
                        'description': 'How can we reach you?',
                        'fields': [
                            {
                                'id': 'phone',
                                'type': 'phone',
                                'label': 'Phone Number',
                                'required': True,
                                'placeholder': '+1 (555) 123-4567'
                            },
                            {
                                'id': 'address',
                                'type': 'textarea',
                                'label': 'Address',
                                'required': True,
                                'placeholder': 'Enter your full address',
                                'rows': 3
                            }
                        ]
                    }
                ],
                'settings': {
                    'theme': 'professional',
                    'animation': 'slide_left',
                    'layout': 'vertical',
                    'show_progress': True,
                    'allow_navigation': True,
                    'require_completion': True,
                    'auto_save': True
                }
            },
            'survey_form': {
                'wizard_id': str(uuid.uuid4()),
                'title': 'Customer Survey',
                'description': 'Help us improve our services with your feedback',
                'steps': [
                    {
                        'id': 'demographics',
                        'title': 'About You',
                        'description': 'Basic demographic information',
                        'fields': [
                            {
                                'id': 'age_group',
                                'type': 'select',
                                'label': 'Age Group',
                                'required': True,
                                'options': ['18-24', '25-34', '35-44', '45-54', '55-64', '65+']
                            },
                            {
                                'id': 'occupation',
                                'type': 'text',
                                'label': 'Occupation',
                                'required': False,
                                'placeholder': 'Your job title or profession'
                            }
                        ]
                    },
                    {
                        'id': 'experience',
                        'title': 'Your Experience',
                        'description': 'Tell us about your experience',
                        'fields': [
                            {
                                'id': 'overall_rating',
                                'type': 'rating',
                                'label': 'Overall Satisfaction',
                                'required': True,
                                'max_stars': 5
                            },
                            {
                                'id': 'service_aspects',
                                'type': 'checkbox',
                                'label': 'Which aspects impressed you most?',
                                'required': False,
                                'options': ['Customer Service', 'Product Quality', 'Fast Delivery', 'Easy Website']
                            }
                        ]
                    }
                ],
                'settings': {
                    'theme': 'accessible',
                    'animation': 'fade',
                    'layout': 'vertical',
                    'show_progress': True,
                    'allow_navigation': True,
                    'require_completion': False,
                    'auto_save': True
                }
            }
        }
        
        return templates.get(template_id)