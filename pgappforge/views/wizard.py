"""
PgAppForge Wizard Form Views

Provides view classes and mixins for implementing wizard forms in PgAppForge
with step navigation, validation, and persistence capabilities.
"""

import json
import logging
from typing import Dict, Any, Optional, Type, Union, List
from flask import request, flash, redirect, url_for, jsonify, render_template
from flask_login import current_user
from werkzeug.exceptions import NotFound

# Set up logging
logger = logging.getLogger(__name__)

from pgappforge.views import BaseView, expose, has_access
from pgappforge.actions import action
from pgappforge.models.mixins import AuditMixin
from pgappforge.security.decorators import protect
from pgappforge import ModelView
from pgappforge.widgets import FormWidget

from ..forms.wizard import WizardForm, WizardStep, WizardFormData


class WizardFormWidget(FormWidget):
    """
    Custom widget for rendering wizard forms with step navigation
    """
    template = 'appbuilder/general/widgets/wizard_form.html'
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wizard_form = None
        self.extra_args = kwargs
    
    def __call__(self, form, **kwargs):
        """Render the wizard form widget"""
        kwargs.update(self.extra_args)
        
        # Store wizard form reference for template access
        if hasattr(form, 'steps'):
            self.wizard_form = form
            kwargs['wizard_form'] = form
            kwargs['current_step'] = form.get_current_step()
            kwargs['steps'] = form.steps
            kwargs['progress_percentage'] = form.get_progress_percentage()
            kwargs['step_statuses'] = [form.get_step_status(i) for i in range(len(form.steps))]
        
        return super().__call__(form, **kwargs)


class WizardFormView(BaseView):
    """
    Base view class for wizard forms
    
    Provides navigation endpoints and step management functionality
    """
    
    # View configuration
    wizard_form_class = None
    wizard_template = 'wizard/wizard_form.html'
    wizard_success_template = 'wizard/wizard_success.html'
    wizard_title = 'Form Wizard'
    wizard_description = ''
    fields_per_step = 10
    allow_step_navigation = True
    require_step_completion = True
    auto_save_interval = 30000  # 30 seconds
    storage_backend = 'session'
    expiration_days = 7
    
    # Navigation settings
    show_progress_bar = True
    show_step_list = True
    show_navigation_buttons = True
    enable_auto_save = True
    
    def __init__(self):
        super().__init__()
        if not self.wizard_form_class:
            raise ValueError("wizard_form_class must be specified")
    
    def _get_wizard_id(self) -> str:
        """Generate or retrieve wizard ID"""
        wizard_id = request.args.get('wizard_id') or request.form.get('wizard_id')
        if not wizard_id:
            import uuid
            wizard_id = str(uuid.uuid4())
        return wizard_id
    
    def _create_wizard_form(self, **kwargs) -> WizardForm:
        """Create a wizard form instance"""
        form_kwargs = {
            'wizard_id': self._get_wizard_id(),
            'wizard_title': self.wizard_title,
            'wizard_description': self.wizard_description,
            'fields_per_step': self.fields_per_step,
            'allow_step_navigation': self.allow_step_navigation,
            'require_step_completion': self.require_step_completion,
            'auto_save_interval': self.auto_save_interval,
            'storage_backend': self.storage_backend,
            'expiration_days': self.expiration_days,
        }
        form_kwargs.update(kwargs)
        
        if request.method == 'POST':
            return self.wizard_form_class(request.form, **form_kwargs)
        else:
            return self.wizard_form_class(**form_kwargs)
    
    @expose('/')
    @expose('/<string:wizard_id>')
    @has_access
    def wizard(self, wizard_id: Optional[str] = None):
        """Main wizard form endpoint"""
        # Handle wizard ID from URL
        if wizard_id:
            form = self._create_wizard_form(wizard_id=wizard_id)
        else:
            form = self._create_wizard_form()
        
        # Handle form submission
        if request.method == 'POST':
            return self._handle_wizard_post(form)
        
        # Render wizard form
        return self._render_wizard_form(form)
    
    def _handle_wizard_post(self, form: WizardForm) -> str:
        """Handle wizard form POST requests"""
        wizard_action = request.form.get('wizard_action', 'next')
        current_step = int(request.form.get('current_step', '0'))
        
        logger.debug(f"Processing wizard action: {wizard_action}, step: {current_step}")
        
        # Update form's current step
        form.current_step_index = current_step
        
        # Process action
        if wizard_action == 'next':
            return self._handle_next_step(form)
        elif wizard_action == 'previous':
            return self._handle_previous_step(form)
        elif wizard_action == 'goto':
            target_step = int(request.form.get('target_step', current_step))
            return self._handle_goto_step(form, target_step)
        elif wizard_action == 'save_draft':
            return self._handle_save_draft(form)
        elif wizard_action == 'submit':
            return self._handle_final_submission(form)
        else:
            # Default to next step
            return self._handle_next_step(form)
    
    def _handle_next_step(self, form: WizardForm) -> str:
        """Handle next step navigation"""
        logger.debug(f"Handling next step from step {form.current_step_index}")
        
        # Save current step data
        if not form.save_wizard_data():
            logger.error("Failed to save wizard data before proceeding to next step")
            flash('Failed to save progress', 'error')
            return self._render_wizard_form(form)
        
        # Validate current step if required
        if form.require_step_completion and not form.validate_current_step():
            flash('Please complete all required fields before proceeding', 'error')
            return self._render_wizard_form(form)
        
        # Move to next step
        if form.is_final_step():
            # This is the final step, handle submission
            return self._handle_final_submission(form)
        else:
            # Move to next step
            if form.next_step():
                flash('Progress saved', 'success')
            return redirect(url_for(f'{self.__class__.__name__}.wizard', wizard_id=form.wizard_id))
    
    def _handle_previous_step(self, form: WizardForm) -> str:
        """Handle previous step navigation"""
        # Save current step data (no validation required)
        form.save_wizard_data()
        
        # Move to previous step
        if form.previous_step():
            flash('Progress saved', 'info')
        
        return redirect(url_for(f'{self.__class__.__name__}.wizard', wizard_id=form.wizard_id))
    
    def _handle_goto_step(self, form: WizardForm, target_step: int) -> str:
        """Handle direct step navigation"""
        # Save current step data
        form.save_wizard_data()
        
        # Navigate to target step
        if form.goto_step(target_step):
            flash('Progress saved', 'info')
            return redirect(url_for(f'{self.__class__.__name__}.wizard', wizard_id=form.wizard_id))
        else:
            flash('Cannot navigate to that step', 'warning')
            return self._render_wizard_form(form)
    
    def _handle_save_draft(self, form: WizardForm) -> str:
        """Handle draft saving"""
        if form.save_wizard_data():
            flash('Draft saved successfully', 'success')
        else:
            flash('Failed to save draft', 'error')
        
        return self._render_wizard_form(form)
    
    def _handle_final_submission(self, form: WizardForm) -> str:
        """Handle final form submission"""
        logger.info(f"Processing final submission for wizard {form.wizard_id}")
        
        # Validate entire form
        if not form.validate():
            logger.warning(f"Final validation failed for wizard {form.wizard_id}")
            flash('Please complete all required fields', 'error')
            return self._render_wizard_form(form)
        
        # Process the submission
        try:
            submission_id = form.submit_wizard()
            if submission_id:
                logger.info(f"Wizard submitted with ID: {submission_id}")
                # Call the form processing method
                result = self.process_wizard_submission(form, submission_id)
                
                if result:
                    logger.info(f"Successfully processed wizard submission {submission_id}")
                    # Clean up wizard data after successful processing
                    form.cleanup_wizard_data()
                    flash('Form submitted successfully!', 'success')
                    return self._render_success_page(form, submission_id)
                else:
                    logger.error(f"Failed to process wizard submission {submission_id}")
                    flash('Failed to process form submission', 'error')
                    return self._render_wizard_form(form)
            else:
                logger.error(f"Failed to submit wizard {form.wizard_id}")
                flash('Failed to submit form', 'error')
                return self._render_wizard_form(form)
                
        except Exception as e:
            logger.exception(f"Exception during wizard submission for {form.wizard_id}: {str(e)}")
            flash(f'Error processing submission: {str(e)}', 'error')
            return self._render_wizard_form(form)
    
    def _render_wizard_form(self, form: WizardForm) -> str:
        """Render the wizard form template"""
        widget = WizardFormWidget()
        
        template_vars = {
            'form': form,
            'widget': widget,
            'wizard_form': form,
            'current_step': form.get_current_step(),
            'steps': form.steps,
            'current_step_index': form.current_step_index,
            'total_steps': len(form.steps),
            'progress_percentage': form.get_progress_percentage(),
            'step_statuses': [form.get_step_status(i) for i in range(len(form.steps))],
            'is_final_step': form.is_final_step(),
            'wizard_title': form.wizard_title,
            'wizard_description': form.wizard_description,
            'show_progress_bar': self.show_progress_bar,
            'show_step_list': self.show_step_list,
            'show_navigation_buttons': self.show_navigation_buttons,
            'enable_auto_save': self.enable_auto_save,
            'auto_save_interval': form.auto_save_interval,
        }
        
        return render_template(self.wizard_template, **template_vars)
    
    def _render_success_page(self, form: WizardForm, submission_id: str) -> str:
        """Render the success page after form submission"""
        template_vars = {
            'wizard_title': form.wizard_title,
            'submission_id': submission_id,
            'form_data': form.wizard_data.form_data if form.wizard_data else {},
        }
        
        return render_template(self.wizard_success_template, **template_vars)
    
    def process_wizard_submission(self, form: WizardForm, submission_id: str) -> bool:
        """
        Process the completed wizard form
        
        Override this method to handle the actual form processing logic.
        
        Args:
            form: The completed wizard form
            submission_id: Unique submission identifier
            
        Returns:
            True if processing was successful, False otherwise
        """
        # Default implementation - override in subclasses
        logger.info(f"Using default wizard submission processing for {submission_id}")
        logger.warning("process_wizard_submission should be overridden in subclasses for custom processing")
        return True
    
    @expose('/api/save_draft', methods=['POST'])
    @has_access
    def save_draft_api(self):
        """API endpoint for saving draft data"""
        try:
            wizard_id = request.json.get('wizard_id')
            form_data = request.json.get('form_data', {})
            current_step = request.json.get('current_step', 0)
            
            if not wizard_id:
                return jsonify({'success': False, 'error': 'wizard_id required'})
            
            # Create minimal form for data saving
            form = self._create_wizard_form(wizard_id=wizard_id)
            
            # Update form data
            for field_name, value in form_data.items():
                if field_name in form._fields:
                    form._fields[field_name].data = value
            
            form.current_step_index = current_step
            
            # Save data
            if form.save_wizard_data():
                return jsonify({
                    'success': True,
                    'message': 'Draft saved successfully',
                    'timestamp': form.wizard_data.updated_at.isoformat() if form.wizard_data else None
                })
            else:
                return jsonify({'success': False, 'error': 'Failed to save draft'})
                
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @expose('/api/validate_step', methods=['POST'])
    @has_access
    def validate_step_api(self):
        """API endpoint for step validation"""
        try:
            wizard_id = request.json.get('wizard_id')
            step_index = request.json.get('step_index', 0)
            form_data = request.json.get('form_data', {})
            
            if not wizard_id:
                return jsonify({'success': False, 'error': 'wizard_id required'})
            
            # Create form for validation
            form = self._create_wizard_form(wizard_id=wizard_id)
            
            # Update form data
            for field_name, value in form_data.items():
                if field_name in form._fields:
                    form._fields[field_name].data = value
            
            form.current_step_index = step_index
            
            # Validate step
            is_valid = form.validate_current_step()
            
            # Get validation errors
            current_step = form.get_current_step()
            errors = current_step.validation_errors if current_step else {}
            
            return jsonify({
                'success': True,
                'is_valid': is_valid,
                'errors': errors,
                'step_index': step_index
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @expose('/api/wizard_status/<string:wizard_id>')
    @has_access
    def wizard_status_api(self, wizard_id: str):
        """API endpoint for getting wizard status"""
        try:
            form = self._create_wizard_form(wizard_id=wizard_id)
            
            return jsonify({
                'success': True,
                'wizard_data': form.to_dict()
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})


class WizardModelView(ModelView):
    """
    Model view with wizard form support
    
    Automatically creates wizard forms for models with many fields
    """
    
    # Wizard configuration
    enable_wizard_form = True
    wizard_fields_threshold = 10  # Enable wizard if more than N fields
    wizard_fields_per_step = 8
    wizard_exclude_fields = ['id', 'created_on', 'changed_on', 'created_by', 'changed_by']
    wizard_custom_steps = None
    wizard_step_titles = None
    wizard_allow_navigation = True
    wizard_require_completion = True
    wizard_auto_save_interval = 30000
    wizard_storage_backend = 'session'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Determine if wizard should be enabled
        if self.enable_wizard_form and self._should_use_wizard():
            self._setup_wizard_form()
    
    def _should_use_wizard(self) -> bool:
        """Determine if wizard form should be used"""
        # Count editable fields
        editable_fields = []
        for field_name in self.add_columns or self.edit_columns or []:
            if field_name not in self.wizard_exclude_fields:
                editable_fields.append(field_name)
        
        return len(editable_fields) >= self.wizard_fields_threshold
    
    def _setup_wizard_form(self):
        """Set up wizard form configuration"""
        # Create wizard steps for this model
        self._wizard_steps = self._create_wizard_steps()
        
        # Override form widget to use wizard widget
        if not hasattr(self, 'add_widget'):
            self.add_widget = WizardFormWidget()
        if not hasattr(self, 'edit_widget'):
            self.edit_widget = WizardFormWidget()
    
    def _create_wizard_steps(self) -> List[WizardStep]:
        """Create wizard steps for the model"""
        if self.wizard_custom_steps:
            return self.wizard_custom_steps
        
        # Get editable fields
        fields = []
        if hasattr(self, 'add_columns') and self.add_columns:
            fields = [f for f in self.add_columns if f not in self.wizard_exclude_fields]
        elif hasattr(self, 'edit_columns') and self.edit_columns:
            fields = [f for f in self.edit_columns if f not in self.wizard_exclude_fields]
        
        # Create steps
        steps = []
        for i in range(0, len(fields), self.wizard_fields_per_step):
            step_fields = fields[i:i + self.wizard_fields_per_step]
            step_index = i // self.wizard_fields_per_step
            
            # Get step title
            if self.wizard_step_titles and len(self.wizard_step_titles) > step_index:
                step_title = self.wizard_step_titles[step_index]
            else:
                step_title = f'Step {step_index + 1}'
            
            # Create step
            step = WizardStep(
                name=f'step_{step_index + 1}',
                title=step_title,
                fields=step_fields,
                description=f'Complete the following fields'
            )
            steps.append(step)
        
        return steps
    
    def _create_model_wizard_form_class(self):
        """Create a WizardForm class from the model"""
        from wtforms_sqlalchemy import model_form
        from wtforms import Form
        
        # Get base form class from model
        base_form_class = model_form(
            self.datamodel.obj,
            base_class=Form,
            exclude=self.wizard_exclude_fields
        )
        
        # Create wizard form class
        class ModelWizardForm(WizardForm, base_form_class):
            def __init__(self, *args, **kwargs):
                # Set custom steps if available
                if hasattr(self, 'wizard_custom_steps') and self.wizard_custom_steps:
                    kwargs['custom_steps'] = self.wizard_custom_steps
                else:
                    kwargs['custom_steps'] = self._create_wizard_steps()
                
                super().__init__(*args, **kwargs)
        
        return ModelWizardForm
    
    def _create_wizard_view_for_model(self, form_class, edit_item=None):
        """Create a wizard view for the model form"""
        model_view = self
        
        class ModelWizardView(WizardFormView):
            wizard_form_class = form_class
            wizard_title = f"{model_view.datamodel.obj.__name__} {'Edit' if edit_item else 'Add'}"
            wizard_description = f"{'Update' if edit_item else 'Create'} {model_view.datamodel.obj.__name__.lower()} record"
            fields_per_step = model_view.wizard_fields_per_step
            allow_step_navigation = model_view.wizard_allow_navigation
            require_step_completion = model_view.wizard_require_completion
            auto_save_interval = model_view.wizard_auto_save_interval
            storage_backend = model_view.wizard_storage_backend
            
            def __init__(self):
                super().__init__()
                self.model_view = model_view
                self.edit_item = edit_item
            
            def _create_wizard_form(self, **kwargs):
                """Override to pre-populate with model data if editing"""
                form = super()._create_wizard_form(**kwargs)
                
                if self.edit_item and request.method == 'GET':
                    # Pre-populate form with existing data
                    self._populate_form_from_model(form, self.edit_item)
                
                return form
            
            def _populate_form_from_model(self, form, item):
                """Populate form fields with data from model instance"""
                for field_name, field in form._fields.items():
                    if hasattr(item, field_name):
                        field.data = getattr(item, field_name)
            
            def process_wizard_submission(self, form, submission_id):
                """Process the wizard form submission"""
                try:
                    if self.edit_item:
                        # Update existing record
                        return self._update_model_record(form, self.edit_item)
                    else:
                        # Create new record
                        return self._create_model_record(form)
                        
                except Exception as e:
                    current_app.logger.error(f"Error processing model wizard submission: {e}")
                    return False
            
            def _create_model_record(self, form):
                """Create new model record from form data"""
                try:
                    # Create new instance
                    item = self.model_view.datamodel.obj()
                    
                    # Populate with form data
                    for field_name, value in form.wizard_data.form_data.items():
                        if hasattr(item, field_name):
                            setattr(item, field_name, value)
                    
                    # Save to database
                    self.model_view.datamodel.add(item)
                    
                    flash(f"New {self.model_view.datamodel.obj.__name__} created successfully", "success")
                    return True
                    
                except Exception as e:
                    self.model_view.datamodel.session.rollback()
                    flash(f"Error creating record: {str(e)}", "error")
                    return False
            
            def _update_model_record(self, form, item):
                """Update existing model record from form data"""
                try:
                    # Update with form data
                    for field_name, value in form.wizard_data.form_data.items():
                        if hasattr(item, field_name):
                            setattr(item, field_name, value)
                    
                    # Save to database
                    self.model_view.datamodel.edit(item)
                    
                    flash(f"{self.model_view.datamodel.obj.__name__} updated successfully", "success")
                    return True
                    
                except Exception as e:
                    self.model_view.datamodel.session.rollback()
                    flash(f"Error updating record: {str(e)}", "error")
                    return False
        
        return ModelWizardView()
    
    @expose('/wizard_add')
    @has_access
    def wizard_add(self):
        """Wizard form for adding new records"""
        if not self.enable_wizard_form or not self._should_use_wizard():
            return redirect(url_for(f'{self.__class__.__name__}.add'))
        
        # Create wizard form from model
        form_class = self._create_model_wizard_form_class()
        
        wizard_view = self._create_wizard_view_for_model(form_class)
        
        # Delegate to the wizard view
        return wizard_view.wizard()
    
    @expose('/wizard_edit/<pk>')
    @has_access
    def wizard_edit(self, pk):
        """Wizard form for editing existing records"""
        if not self.enable_wizard_form or not self._should_use_wizard():
            return redirect(url_for(f'{self.__class__.__name__}.edit', pk=pk))
        
        # Get the record to edit
        item = self.datamodel.get(pk)
        if not item:
            flash(f"Record not found", "error")
            return redirect(url_for(f'{self.__class__.__name__}.list'))
        
        # Create wizard form from model
        form_class = self._create_model_wizard_form_class()
        
        wizard_view = self._create_wizard_view_for_model(form_class, edit_item=item)
        
        # Delegate to the wizard view
        return wizard_view.wizard()


class WizardFormMixin:
    """
    Mixin for adding wizard form capabilities to existing views
    """
    
    def create_wizard_form(self, form_class: Type, **kwargs) -> WizardForm:
        """Create a wizard form from a regular form class"""
        # Convert regular form to wizard form
        class WizardFormClass(WizardForm, form_class):
            pass
        
        return WizardFormClass(**kwargs)
    
    def render_wizard_template(self, template: str, wizard_form: WizardForm, **kwargs):
        """Render template with wizard form context"""
        template_vars = {
            'wizard_form': wizard_form,
            'current_step': wizard_form.get_current_step(),
            'steps': wizard_form.steps,
            'progress_percentage': wizard_form.get_progress_percentage(),
        }
        template_vars.update(kwargs)
        
        return render_template(template, **template_vars)