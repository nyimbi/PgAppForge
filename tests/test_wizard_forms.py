"""
Comprehensive tests for WizardForm functionality

Tests cover form creation, step management, persistence, navigation,
validation, and view integration.
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from flask import Flask, session
from flask_login import UserMixin, login_user

from wtforms import Form, StringField, IntegerField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Length, NumberRange

from pgappforge.forms.wizard import (
    WizardForm, WizardStep, WizardFormData, WizardFormPersistence
)
from pgappforge.views.wizard import WizardFormView, WizardFormWidget


class MockUser(UserMixin):
    """Mock user for testing"""
    def __init__(self, user_id=1):
        self.id = user_id
        self.is_authenticated = True


class TestWizardStep:
    """Test WizardStep class functionality"""
    
    def test_wizard_step_creation(self):
        """Test basic WizardStep creation"""
        step = WizardStep(
            name='personal_info',
            title='Personal Information',
            fields=['first_name', 'last_name', 'email'],
            required_fields=['first_name', 'email'],
            description='Enter your personal details'
        )
        
        assert step.name == 'personal_info'
        assert step.title == 'Personal Information'
        assert step.fields == ['first_name', 'last_name', 'email']
        assert step.required_fields == ['first_name', 'email']
        assert step.description == 'Enter your personal details'
        assert step.icon == 'fa-edit'  # default
    
    def test_step_validation_success(self):
        """Test successful step validation"""
        step = WizardStep(
            name='test_step',
            title='Test Step',
            fields=['name', 'email'],
            required_fields=['name', 'email']
        )
        
        form_data = {'name': 'John Doe', 'email': 'john@example.com'}
        is_valid, errors = step.validate_step(form_data)
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_step_validation_missing_required(self):
        """Test step validation with missing required fields"""
        step = WizardStep(
            name='test_step',
            title='Test Step',
            fields=['name', 'email', 'phone'],
            required_fields=['name', 'email']
        )
        
        form_data = {'name': 'John Doe', 'phone': '123-456-7890'}  # missing email
        is_valid, errors = step.validate_step(form_data)
        
        assert is_valid is False
        assert 'email' in errors
        assert 'email is required' in errors['email']
    
    def test_step_custom_validation_rules(self):
        """Test custom validation rules"""
        def custom_validator(value):
            if len(value) < 5:
                raise ValueError('Value too short')
        
        step = WizardStep(
            name='test_step',
            title='Test Step',
            fields=['username'],
            validation_rules={
                'username': {
                    'min_length': 3,
                    'max_length': 20,
                    'pattern': r'^[a-zA-Z0-9_]+$',
                    'custom': custom_validator
                }
            }
        )
        
        # Test valid data
        is_valid, errors = step.validate_step({'username': 'validuser123'})
        assert is_valid is True
        
        # Test too short
        is_valid, errors = step.validate_step({'username': 'ab'})
        assert is_valid is False
        assert 'username' in errors
        
        # Test invalid pattern
        is_valid, errors = step.validate_step({'username': 'invalid-user!'})
        assert is_valid is False
        assert 'username' in errors
    
    def test_conditional_fields(self):
        """Test conditional field functionality"""
        step = WizardStep(
            name='contact_step',
            title='Contact Information',
            fields=['contact_method', 'email', 'phone'],
            conditional_fields={
                'email': {'contact_method': 'email'},
                'phone': {'contact_method': 'phone'}
            },
            required_fields=['email']  # email is required when shown
        )
        
        # Email should be required when contact_method is 'email'
        form_data = {'contact_method': 'email', 'phone': '123-456-7890'}
        is_valid, errors = step.validate_step(form_data)
        assert is_valid is False
        assert 'email' in errors
        
        # Email should not be required when contact_method is 'phone'
        form_data = {'contact_method': 'phone', 'phone': '123-456-7890'}
        is_valid, errors = step.validate_step(form_data)
        assert is_valid is True
    
    def test_progress_percentage(self):
        """Test progress percentage calculation"""
        step = WizardStep(
            name='test_step',
            title='Test Step',
            fields=['field1', 'field2', 'field3', 'field4']
        )
        
        # No fields completed
        assert step.get_progress_percentage({}) == 0.0
        
        # Half fields completed
        form_data = {'field1': 'value1', 'field2': 'value2'}
        assert step.get_progress_percentage(form_data) == 50.0
        
        # All fields completed
        form_data = {'field1': 'value1', 'field2': 'value2', 'field3': 'value3', 'field4': 'value4'}
        assert step.get_progress_percentage(form_data) == 100.0
    
    def test_step_serialization(self):
        """Test step to_dict method"""
        step = WizardStep(
            name='test_step',
            title='Test Step',
            fields=['field1', 'field2'],
            description='Test description'
        )
        
        step_dict = step.to_dict()
        
        assert step_dict['name'] == 'test_step'
        assert step_dict['title'] == 'Test Step'
        assert step_dict['fields'] == ['field1', 'field2']
        assert step_dict['description'] == 'Test description'
        assert 'is_valid' in step_dict
        assert 'validation_errors' in step_dict


class TestWizardFormData:
    """Test WizardFormData class functionality"""
    
    def test_wizard_data_creation(self):
        """Test WizardFormData creation"""
        wizard_data = WizardFormData('test_wizard_123', 'user_456')
        
        assert wizard_data.wizard_id == 'test_wizard_123'
        assert wizard_data.user_id == 'user_456'
        assert wizard_data.form_data == {}
        assert wizard_data.current_step == 0
        assert wizard_data.completed_steps == set()
        assert wizard_data.is_submitted is False
    
    def test_update_data(self):
        """Test updating wizard data"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        
        step_data = {'name': 'John', 'email': 'john@example.com'}
        wizard_data.update_data(step_data, 0)
        
        assert wizard_data.form_data['name'] == 'John'
        assert wizard_data.form_data['email'] == 'john@example.com'
        assert 0 in wizard_data.completed_steps
        assert wizard_data.updated_at > wizard_data.created_at
    
    def test_step_data_retrieval(self):
        """Test getting step-specific data"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        wizard_data.form_data = {
            'name': 'John',
            'email': 'john@example.com',
            'phone': '123-456-7890',
            'address': '123 Main St'
        }
        
        step_fields = ['name', 'email']
        step_data = wizard_data.get_step_data(step_fields)
        
        assert step_data == {'name': 'John', 'email': 'john@example.com'}
    
    def test_current_step_management(self):
        """Test current step setting"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        
        wizard_data.set_current_step(2)
        assert wizard_data.current_step == 2
        assert wizard_data.updated_at > wizard_data.created_at
    
    def test_submission_marking(self):
        """Test marking wizard as submitted"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        
        submission_id = wizard_data.mark_submitted()
        
        assert wizard_data.is_submitted is True
        assert wizard_data.submission_id is not None
        assert len(wizard_data.submission_id) > 0
    
    def test_expiration_check(self):
        """Test wizard data expiration"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        
        # Should not be expired initially
        assert wizard_data.is_expired() is False
        
        # Manually set expired date
        wizard_data.expires_at = datetime.utcnow() - timedelta(days=1)
        assert wizard_data.is_expired() is True
    
    def test_serialization(self):
        """Test to_dict and from_dict methods"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        wizard_data.form_data = {'name': 'John', 'email': 'john@example.com'}
        wizard_data.completed_steps.add(0)
        wizard_data.current_step = 1
        
        # Serialize
        data_dict = wizard_data.to_dict()
        
        # Deserialize
        restored_data = WizardFormData.from_dict(data_dict)
        
        assert restored_data.wizard_id == wizard_data.wizard_id
        assert restored_data.user_id == wizard_data.user_id
        assert restored_data.form_data == wizard_data.form_data
        assert restored_data.completed_steps == wizard_data.completed_steps
        assert restored_data.current_step == wizard_data.current_step


class TestWizardFormPersistence:
    """Test WizardFormPersistence functionality"""
    
    def setup_method(self):
        """Set up test environment"""
        self.app = Flask(__name__)
        self.app.secret_key = 'test_secret'
        self.persistence = WizardFormPersistence('session')
    
    def test_session_storage(self):
        """Test session-based storage"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        wizard_data.form_data = {'name': 'John', 'email': 'john@example.com'}
        
        with self.app.test_request_context():
            # Save data
            success = self.persistence.save_wizard_data(wizard_data)
            assert success is True
            
            # Load data
            loaded_data = self.persistence.load_wizard_data('test_wizard')
            assert loaded_data is not None
            assert loaded_data.wizard_id == 'test_wizard'
            assert loaded_data.form_data['name'] == 'John'
            
            # Delete data
            success = self.persistence.delete_wizard_data('test_wizard')
            assert success is True
            
            # Verify deletion
            loaded_data = self.persistence.load_wizard_data('test_wizard')
            assert loaded_data is None
    
    def test_expired_data_cleanup(self):
        """Test that expired data is not loaded"""
        wizard_data = WizardFormData('test_wizard', 'user_1')
        wizard_data.expires_at = datetime.utcnow() - timedelta(days=1)  # Expired
        
        with self.app.test_request_context():
            # Save expired data
            self.persistence.save_wizard_data(wizard_data)
            
            # Try to load expired data
            loaded_data = self.persistence.load_wizard_data('test_wizard')
            assert loaded_data is None  # Should return None for expired data


class TestWizardForm:
    """Test WizardForm class functionality"""
    
    def setup_method(self):
        """Set up test forms"""
        self.app = Flask(__name__)
        self.app.secret_key = 'test_secret'
        
        # Create a test form class
        class TestForm(WizardForm):
            first_name = StringField('First Name', validators=[DataRequired()])
            last_name = StringField('Last Name', validators=[DataRequired()])
            email = StringField('Email', validators=[DataRequired()])
            phone = StringField('Phone')
            address = TextAreaField('Address')
            city = StringField('City')
            state = StringField('State')
            zip_code = StringField('ZIP Code')
            age = IntegerField('Age', validators=[NumberRange(min=0, max=120)])
            newsletter = BooleanField('Subscribe to Newsletter')
        
        self.test_form_class = TestForm
    
    def test_wizard_form_creation(self):
        """Test wizard form creation with auto-generated steps"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=3
            )
            
            assert len(form.steps) > 0
            assert form.wizard_id == 'test_wizard'
            assert form.current_step_index == 0
            assert isinstance(form.get_current_step(), WizardStep)
    
    def test_auto_step_generation(self):
        """Test automatic step generation based on field count"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=4  # Should create multiple steps
            )
            
            # Should create multiple steps since we have 10 fields and 4 fields per step
            assert len(form.steps) >= 2
            
            # Check first step
            first_step = form.steps[0]
            assert len(first_step.fields) <= 4
            assert first_step.name.startswith('step_')
    
    def test_custom_steps(self):
        """Test wizard form with custom step definitions"""
        custom_steps = [
            WizardStep(
                name='personal',
                title='Personal Information',
                fields=['first_name', 'last_name', 'email'],
                required_fields=['first_name', 'last_name', 'email']
            ),
            WizardStep(
                name='contact',
                title='Contact Information',
                fields=['phone', 'address', 'city', 'state', 'zip_code']
            ),
            WizardStep(
                name='preferences',
                title='Preferences',
                fields=['age', 'newsletter']
            )
        ]
        
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                custom_steps=custom_steps
            )
            
            assert len(form.steps) == 3
            assert form.steps[0].name == 'personal'
            assert form.steps[1].name == 'contact'
            assert form.steps[2].name == 'preferences'
    
    def test_step_navigation(self):
        """Test step navigation functionality"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=3
            )
            
            # Start at step 0
            assert form.current_step_index == 0
            assert not form.is_final_step()
            
            # Move to next step
            success = form.next_step()
            if len(form.steps) > 1:
                assert success is True
                assert form.current_step_index == 1
            
            # Move to previous step
            if form.current_step_index > 0:
                success = form.previous_step()
                assert success is True
                assert form.current_step_index == 0
    
    def test_step_validation(self):
        """Test step-by-step validation"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=3,
                require_step_completion=True
            )
            
            # Get current step fields
            current_step = form.get_current_step()
            
            # Fill in some required fields
            for field_name in current_step.required_fields:
                if field_name in form._fields:
                    form._fields[field_name].data = f'test_{field_name}'
            
            # Validate current step
            is_valid = form.validate_current_step()
            # Should be valid if we filled required fields
            assert is_valid is True
    
    def test_navigation_permissions(self):
        """Test navigation permission checking"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=3,
                allow_step_navigation=True,
                require_step_completion=True
            )
            
            # Should be able to navigate to current step
            assert form.can_navigate_to_step(0) is True
            
            # Should not be able to navigate to future steps without completion
            if len(form.steps) > 1:
                assert form.can_navigate_to_step(1) is False
    
    def test_progress_calculation(self):
        """Test overall progress percentage calculation"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard',
                fields_per_step=5
            )
            
            # Initial progress should be 0 or based on current step
            initial_progress = form.get_progress_percentage()
            assert 0 <= initial_progress <= 100
            
            # Fill in current step fields
            current_step = form.get_current_step()
            if current_step:
                for field_name in current_step.fields:
                    if field_name in form._fields:
                        form._fields[field_name].data = f'test_{field_name}'
                
                # Progress should increase
                new_progress = form.get_progress_percentage()
                assert new_progress >= initial_progress
    
    def test_wizard_data_persistence(self):
        """Test wizard data saving and loading"""
        with self.app.test_request_context():
            # Create form and fill in data
            form = self.test_form_class(
                wizard_id='test_wizard_persist',
                fields_per_step=3
            )
            
            # Set some field data
            form._fields['first_name'].data = 'John'
            form._fields['last_name'].data = 'Doe'
            form._fields['email'].data = 'john@example.com'
            
            # Save wizard data
            success = form.save_wizard_data()
            assert success is True
            
            # Create new form instance with same wizard_id
            form2 = self.test_form_class(
                wizard_id='test_wizard_persist',
                fields_per_step=3
            )
            
            # Data should be loaded automatically
            assert form2._fields['first_name'].data == 'John'
            assert form2._fields['last_name'].data == 'Doe'
            assert form2._fields['email'].data == 'john@example.com'
    
    def test_final_submission(self):
        """Test final form submission"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard_submit',
                fields_per_step=20  # Single step for testing
            )
            
            # Fill required fields
            form._fields['first_name'].data = 'John'
            form._fields['last_name'].data = 'Doe'
            form._fields['email'].data = 'john@example.com'
            
            # Should be final step
            assert form.is_final_step() is True
            
            # Submit wizard
            submission_id = form.submit_wizard()
            assert submission_id is not None
            assert len(submission_id) > 0
            
            # Check wizard data state
            assert form.wizard_data.is_submitted is True
            assert form.wizard_data.submission_id == submission_id
    
    def test_wizard_serialization(self):
        """Test wizard form to_dict method"""
        with self.app.test_request_context():
            form = self.test_form_class(
                wizard_id='test_wizard_dict',
                wizard_title='Test Wizard',
                wizard_description='A test wizard form'
            )
            
            wizard_dict = form.to_dict()
            
            assert wizard_dict['wizard_id'] == 'test_wizard_dict'
            assert wizard_dict['wizard_title'] == 'Test Wizard'
            assert wizard_dict['wizard_description'] == 'A test wizard form'
            assert 'steps' in wizard_dict
            assert 'current_step_index' in wizard_dict
            assert 'progress_percentage' in wizard_dict


class TestWizardFormView:
    """Test WizardFormView functionality"""
    
    def setup_method(self):
        """Set up test view"""
        self.app = Flask(__name__)
        self.app.secret_key = 'test_secret'
        
        # Create test form
        class TestWizardForm(WizardForm):
            name = StringField('Name', validators=[DataRequired()])
            email = StringField('Email', validators=[DataRequired()])
            message = TextAreaField('Message')
        
        # Create test view
        class TestWizardView(WizardFormView):
            wizard_form_class = TestWizardForm
            wizard_title = 'Test Wizard'
            fields_per_step = 2
            
            def process_wizard_submission(self, form, submission_id):
                # Mock processing
                return True
        
        self.test_view_class = TestWizardView
        self.test_form_class = TestWizardForm
    
    def test_view_initialization(self):
        """Test wizard view initialization"""
        view = self.test_view_class()
        assert view.wizard_form_class == self.test_form_class
        assert view.wizard_title == 'Test Wizard'
        assert view.fields_per_step == 2
    
    def test_wizard_id_generation(self):
        """Test wizard ID handling"""
        view = self.test_view_class()
        
        with self.app.test_request_context():
            wizard_id = view._get_wizard_id()
            assert wizard_id is not None
            assert len(wizard_id) > 0
        
        with self.app.test_request_context('/?wizard_id=custom_wizard_123'):
            wizard_id = view._get_wizard_id()
            assert wizard_id == 'custom_wizard_123'
    
    def test_form_creation(self):
        """Test wizard form creation in view"""
        view = self.test_view_class()
        
        with self.app.test_request_context():
            form = view._create_wizard_form()
            assert isinstance(form, self.test_form_class)
            assert hasattr(form, 'wizard_id')
            assert hasattr(form, 'steps')


class TestWizardFormWidget:
    """Test WizardFormWidget functionality"""
    
    def test_widget_creation(self):
        """Test wizard form widget creation"""
        widget = WizardFormWidget()
        assert widget.template == 'appbuilder/general/widgets/wizard_form.html'
    
    def test_widget_call(self):
        """Test widget rendering call"""
        widget = WizardFormWidget()
        
        # Mock form with wizard capabilities
        mock_form = MagicMock()
        mock_form.steps = []
        mock_form.get_current_step.return_value = None
        mock_form.get_progress_percentage.return_value = 50.0
        mock_form.get_step_status.return_value = 'current'
        
        # This would normally render the template
        # For testing, we just ensure the method can be called
        kwargs = {}
        result_kwargs = widget.__call__(mock_form, **kwargs)
        # The actual rendering would depend on template system being set up


if __name__ == '__main__':
    pytest.main([__file__, '-v'])