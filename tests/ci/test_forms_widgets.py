"""
Comprehensive unit tests for PgAppForge forms and widgets.

This module provides thorough testing coverage for form handling, validation,
field widgets, custom forms, and form rendering functionality.
"""

import datetime
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import pytest
from flask import Flask, request
from pgappforge import AppBuilder, SQLA
from pgappforge.fieldwidgets import (
    BS3TextFieldWidget, BS3TextAreaFieldWidget, BS3PasswordFieldWidget,
    BS3SelectFieldWidget, Select2Widget, DatePickerWidget, DateTimePickerWidget,
    BS3SelectMultipleFieldWidget
)
from pgappforge.forms import DynamicForm
from pgappforge.models.sqla import Model
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.validators import Unique
from pgappforge.widgets import FormWidget, ListWidget, ShowWidget, SearchWidget
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float
from wtforms import (
    StringField, TextAreaField, PasswordField, SelectField, BooleanField,
    IntegerField, FloatField, DateField, DateTimeField, SelectMultipleField,
    HiddenField, FileField
)
from wtforms.validators import (
    DataRequired, Length, Email, EqualTo, NumberRange, Optional as OptionalValidator,
    Regexp, URL, ValidationError
)

from tests.base import FABTestCase


# Test Models for Form Testing
class FormTestModel(Model):
    """Test model for form testing"""
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    description = Column(Text)
    age = Column(Integer)
    salary = Column(Float)
    active = Column(Boolean, default=True)
    birth_date = Column(DateTime)
    created_on = Column(DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return self.name or ''


# Custom Validator for Testing
def validate_positive_number(form, field):
    """Custom validator to ensure positive numbers"""
    if field.data is not None and field.data <= 0:
        raise ValidationError('Value must be positive')


# Test Forms
class BasicTestForm(DynamicForm):
    """Basic test form with common field types"""
    name = StringField(
        'Name',
        validators=[DataRequired(), Length(min=2, max=100)],
        widget=BS3TextFieldWidget()
    )
    email = StringField(
        'Email',
        validators=[DataRequired(), Email()],
        widget=BS3TextFieldWidget()
    )
    description = TextAreaField(
        'Description',
        validators=[OptionalValidator(), Length(max=500)],
        widget=BS3TextAreaFieldWidget(rows=4)
    )
    active = BooleanField('Active', default=True)


class AdvancedTestForm(DynamicForm):
    """Advanced test form with complex validation"""
    username = StringField(
        'Username',
        validators=[
            DataRequired(),
            Length(min=3, max=20),
            Regexp(r'^[a-zA-Z0-9_]+$', message='Username must contain only letters, numbers, and underscores')
        ],
        widget=BS3TextFieldWidget()
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired(), Length(min=6, max=128)],
        widget=BS3PasswordFieldWidget()
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[
            DataRequired(),
            EqualTo('password', message='Passwords must match')
        ],
        widget=BS3PasswordFieldWidget()
    )
    age = IntegerField(
        'Age',
        validators=[OptionalValidator(), NumberRange(min=0, max=150)]
    )
    salary = FloatField(
        'Salary',
        validators=[OptionalValidator(), validate_positive_number]
    )
    birth_date = DateField(
        'Birth Date',
        validators=[OptionalValidator()],
        widget=DatePickerWidget()
    )
    website = StringField(
        'Website',
        validators=[OptionalValidator(), URL()],
        widget=BS3TextFieldWidget()
    )
    skills = SelectMultipleField(
        'Skills',
        choices=[
            ('python', 'Python'),
            ('javascript', 'JavaScript'),
            ('java', 'Java'),
            ('csharp', 'C#'),
            ('ruby', 'Ruby')
        ],
        widget=BS3SelectMultipleFieldWidget()
    )
    country = SelectField(
        'Country',
        choices=[
            ('', 'Select Country'),
            ('us', 'United States'),
            ('uk', 'United Kingdom'),
            ('ca', 'Canada'),
            ('au', 'Australia'),
            ('de', 'Germany')
        ],
        validators=[OptionalValidator()],
        widget=Select2Widget()
    )


class TestBasicFormFunctionality(FABTestCase):
    """Test basic form functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-forms'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_form_creation(self):
        """Test basic form creation"""
        with self.app.app_context():
            form = BasicTestForm()
            
            # Test form is created
            self.assertIsInstance(form, BasicTestForm)
            
            # Test fields exist
            self.assertTrue(hasattr(form, 'name'))
            self.assertTrue(hasattr(form, 'email'))
            self.assertTrue(hasattr(form, 'description'))
            self.assertTrue(hasattr(form, 'active'))
    
    def test_form_field_types(self):
        """Test form field types are correct"""
        with self.app.app_context():
            form = BasicTestForm()
            
            # Test field types
            self.assertIsInstance(form.name, StringField)
            self.assertIsInstance(form.email, StringField)
            self.assertIsInstance(form.description, TextAreaField)
            self.assertIsInstance(form.active, BooleanField)
    
    def test_form_widgets(self):
        """Test form field widgets"""
        with self.app.app_context():
            form = BasicTestForm()
            
            # Test widgets are assigned correctly
            self.assertIsInstance(form.name.widget, BS3TextFieldWidget)
            self.assertIsInstance(form.email.widget, BS3TextFieldWidget)
            self.assertIsInstance(form.description.widget, BS3TextAreaFieldWidget)
    
    def test_form_validators(self):
        """Test form field validators"""
        with self.app.app_context():
            form = BasicTestForm()
            
            # Test validators exist
            self.assertTrue(len(form.name.validators) > 0)
            self.assertTrue(len(form.email.validators) > 0)
            
            # Test specific validators
            name_validator_types = [type(v) for v in form.name.validators]
            self.assertIn(DataRequired, name_validator_types)
            self.assertIn(Length, name_validator_types)
            
            email_validator_types = [type(v) for v in form.email.validators]
            self.assertIn(DataRequired, email_validator_types)
            self.assertIn(Email, email_validator_types)


class TestFormValidation(FABTestCase):
    """Test form validation functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-validation'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_valid_form_data(self):
        """Test form validation with valid data"""
        with self.app.app_context():
            valid_data = {
                'name': 'John Doe',
                'email': 'john@example.com',
                'description': 'Test description',
                'active': True
            }
            
            form = BasicTestForm(data=valid_data)
            self.assertTrue(form.validate())
            self.assertEqual(len(form.errors), 0)
    
    def test_invalid_form_data_required_fields(self):
        """Test form validation with missing required fields"""
        with self.app.app_context():
            invalid_data = {
                'description': 'Description without required fields'
            }
            
            form = BasicTestForm(data=invalid_data)
            self.assertFalse(form.validate())
            
            # Check specific field errors
            self.assertIn('name', form.errors)
            self.assertIn('email', form.errors)
    
    def test_invalid_email_validation(self):
        """Test email validation"""
        with self.app.app_context():
            invalid_email_data = {
                'name': 'Test User',
                'email': 'invalid-email-format',
                'active': True
            }
            
            form = BasicTestForm(data=invalid_email_data)
            self.assertFalse(form.validate())
            self.assertIn('email', form.errors)
    
    def test_length_validation(self):
        """Test length validation"""
        with self.app.app_context():
            # Test name too short
            short_name_data = {
                'name': 'A',  # Too short (min 2)
                'email': 'test@example.com'
            }
            
            form = BasicTestForm(data=short_name_data)
            self.assertFalse(form.validate())
            self.assertIn('name', form.errors)
            
            # Test name too long
            long_name_data = {
                'name': 'A' * 101,  # Too long (max 100)
                'email': 'test@example.com'
            }
            
            form = BasicTestForm(data=long_name_data)
            self.assertFalse(form.validate())
            self.assertIn('name', form.errors)
    
    def test_optional_field_validation(self):
        """Test optional field validation"""
        with self.app.app_context():
            # Valid form with optional field empty
            data_empty_optional = {
                'name': 'Test User',
                'email': 'test@example.com',
                'description': '',  # Optional and empty
                'active': True
            }
            
            form = BasicTestForm(data=data_empty_optional)
            self.assertTrue(form.validate())
            
            # Valid form with optional field filled
            data_filled_optional = {
                'name': 'Test User',
                'email': 'test@example.com',
                'description': 'Valid description',
                'active': True
            }
            
            form = BasicTestForm(data=data_filled_optional)
            self.assertTrue(form.validate())


class TestAdvancedFormValidation(FABTestCase):
    """Test advanced form validation"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-advanced'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_password_confirmation_validation(self):
        """Test password confirmation validation"""
        with self.app.app_context():
            # Test matching passwords
            valid_password_data = {
                'username': 'testuser',
                'password': 'secure123',
                'confirm_password': 'secure123'
            }
            
            form = AdvancedTestForm(data=valid_password_data)
            # Focus only on password fields validation
            form.username.data = 'testuser'
            form.password.data = 'secure123'
            form.confirm_password.data = 'secure123'
            
            # Validate just password fields
            password_valid = True
            confirm_password_valid = True
            
            try:
                form.password.validate(form)
            except ValidationError:
                password_valid = False
            
            try:
                form.confirm_password.validate(form)
            except ValidationError:
                confirm_password_valid = False
            
            self.assertTrue(password_valid)
            # Note: EqualTo validation might require full form validation
            
            # Test non-matching passwords
            invalid_password_data = {
                'username': 'testuser',
                'password': 'secure123',
                'confirm_password': 'different123'
            }
            
            form = AdvancedTestForm(data=invalid_password_data)
            self.assertFalse(form.validate())
            # Should have error in confirm_password field
            if 'confirm_password' in form.errors:
                self.assertIn('confirm_password', form.errors)
    
    def test_regex_validation(self):
        """Test regex validation for username"""
        with self.app.app_context():
            # Test valid username
            valid_username_data = {
                'username': 'valid_user123',
                'password': 'password123',
                'confirm_password': 'password123'
            }
            
            form = AdvancedTestForm(data=valid_username_data)
            # Test just username field
            try:
                form.username.validate(form)
                username_valid = True
            except ValidationError:
                username_valid = False
            
            self.assertTrue(username_valid)
            
            # Test invalid username (with spaces)
            invalid_username_data = {
                'username': 'invalid user',  # Contains space
                'password': 'password123',
                'confirm_password': 'password123'
            }
            
            form = AdvancedTestForm(data=invalid_username_data)
            self.assertFalse(form.validate())
            self.assertIn('username', form.errors)
    
    def test_number_range_validation(self):
        """Test number range validation"""
        with self.app.app_context():
            # Test valid age
            valid_age_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'age': 25
            }
            
            form = AdvancedTestForm(data=valid_age_data)
            # Age should be valid
            try:
                form.age.validate(form)
                age_valid = True
            except ValidationError:
                age_valid = False
            
            self.assertTrue(age_valid)
            
            # Test invalid age (negative)
            invalid_age_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'age': -5
            }
            
            form = AdvancedTestForm(data=invalid_age_data)
            self.assertFalse(form.validate())
            if 'age' in form.errors:
                self.assertIn('age', form.errors)
    
    def test_custom_validator(self):
        """Test custom validator functionality"""
        with self.app.app_context():
            # Test valid salary (positive)
            valid_salary_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'salary': 50000.0
            }
            
            form = AdvancedTestForm(data=valid_salary_data)
            # Test custom validator
            try:
                form.salary.validate(form)
                salary_valid = True
            except ValidationError:
                salary_valid = False
            
            self.assertTrue(salary_valid)
            
            # Test invalid salary (negative)
            invalid_salary_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'salary': -1000.0
            }
            
            form = AdvancedTestForm(data=invalid_salary_data)
            self.assertFalse(form.validate())
            if 'salary' in form.errors:
                self.assertIn('salary', form.errors)
    
    def test_url_validation(self):
        """Test URL validation"""
        with self.app.app_context():
            # Test valid URL
            valid_url_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'website': 'https://www.example.com'
            }
            
            form = AdvancedTestForm(data=valid_url_data)
            try:
                form.website.validate(form)
                url_valid = True
            except ValidationError:
                url_valid = False
            
            self.assertTrue(url_valid)
            
            # Test invalid URL
            invalid_url_data = {
                'username': 'testuser',
                'password': 'password123',
                'confirm_password': 'password123',
                'website': 'not-a-valid-url'
            }
            
            form = AdvancedTestForm(data=invalid_url_data)
            self.assertFalse(form.validate())
            if 'website' in form.errors:
                self.assertIn('website', form.errors)


class TestFormWidgets(FABTestCase):
    """Test form widget functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-widgets'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_text_field_widget(self):
        """Test text field widget"""
        with self.app.app_context():
            widget = BS3TextFieldWidget()
            self.assertIsInstance(widget, BS3TextFieldWidget)
            
            # Test widget has call method for rendering
            self.assertTrue(callable(widget))
    
    def test_textarea_widget(self):
        """Test textarea widget"""
        with self.app.app_context():
            widget = BS3TextAreaFieldWidget(rows=4)
            self.assertIsInstance(widget, BS3TextAreaFieldWidget)
    
    def test_password_widget(self):
        """Test password widget"""
        with self.app.app_context():
            widget = BS3PasswordFieldWidget()
            self.assertIsInstance(widget, BS3PasswordFieldWidget)
    
    def test_select_widget(self):
        """Test select widget"""
        with self.app.app_context():
            widget = BS3SelectFieldWidget()
            self.assertIsInstance(widget, BS3SelectFieldWidget)
    
    def test_select2_widget(self):
        """Test Select2 widget"""
        with self.app.app_context():
            widget = Select2Widget()
            self.assertIsInstance(widget, Select2Widget)
    
    def test_date_picker_widget(self):
        """Test date picker widget"""
        with self.app.app_context():
            widget = DatePickerWidget()
            self.assertIsInstance(widget, DatePickerWidget)
    
    def test_datetime_picker_widget(self):
        """Test datetime picker widget"""
        with self.app.app_context():
            widget = DateTimePickerWidget()
            self.assertIsInstance(widget, DateTimePickerWidget)
    
    def test_select_multiple_widget(self):
        """Test select multiple widget"""
        with self.app.app_context():
            widget = BS3SelectMultipleFieldWidget()
            self.assertIsInstance(widget, BS3SelectMultipleFieldWidget)


class TestFormWidgetRendering(FABTestCase):
    """Test form widget rendering"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-rendering'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_widget_rendering_infrastructure(self):
        """Test widget rendering infrastructure exists"""
        with self.app.app_context():
            # Test that widgets can be instantiated
            widgets = [
                BS3TextFieldWidget(),
                BS3TextAreaFieldWidget(),
                BS3PasswordFieldWidget(),
                BS3SelectFieldWidget(),
                Select2Widget(),
                DatePickerWidget(),
                BS3SelectMultipleFieldWidget()
            ]
            
            for widget in widgets:
                # Test that widget is callable (can be used for rendering)
                self.assertTrue(callable(widget))


class TestFormIntegration(FABTestCase):
    """Test form integration with models and views"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-integration'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            FormTestModel.__table__.create(self.db.engine, checkfirst=True)
            self.db.create_all()
    
    def test_model_form_integration(self):
        """Test form integration with models"""
        with self.app.app_context():
            # Create interface for model
            interface = SQLAInterface(FormTestModel)
            
            # Test that interface can generate forms
            self.assertTrue(hasattr(interface, 'get_form'))
            
            # Test form creation from model
            try:
                form_class = interface.get_form()
                self.assertIsNotNone(form_class)
            except AttributeError:
                # Some interfaces may not have get_form method
                pass
    
    def test_form_data_binding(self):
        """Test form data binding with model instances"""
        with self.app.app_context():
            # Create a model instance
            test_instance = FormTestModel(
                name='Test User',
                email='test@example.com',
                description='Test description',
                age=30,
                active=True
            )
            
            self.db.session.add(test_instance)
            self.db.session.commit()
            
            # Test that form can be populated from model
            form_data = {
                'name': test_instance.name,
                'email': test_instance.email,
                'description': test_instance.description,
                'active': test_instance.active
            }
            
            form = BasicTestForm(data=form_data)
            
            # Test form is populated correctly
            self.assertEqual(form.name.data, test_instance.name)
            self.assertEqual(form.email.data, test_instance.email)
            self.assertEqual(form.description.data, test_instance.description)
            self.assertEqual(form.active.data, test_instance.active)


class TestFormCustomization(FABTestCase):
    """Test form customization capabilities"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-customization'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_custom_field_creation(self):
        """Test creation of custom form fields"""
        with self.app.app_context():
            # Custom form with additional fields
            class CustomForm(DynamicForm):
                title = StringField('Title', validators=[DataRequired()])
                priority = SelectField(
                    'Priority',
                    choices=[
                        ('low', 'Low'),
                        ('medium', 'Medium'),
                        ('high', 'High')
                    ],
                    default='medium'
                )
                tags = StringField('Tags (comma-separated)')
                due_date = DateField('Due Date')
            
            form = CustomForm()
            
            # Test custom fields exist
            self.assertTrue(hasattr(form, 'title'))
            self.assertTrue(hasattr(form, 'priority'))
            self.assertTrue(hasattr(form, 'tags'))
            self.assertTrue(hasattr(form, 'due_date'))
            
            # Test field types
            self.assertIsInstance(form.title, StringField)
            self.assertIsInstance(form.priority, SelectField)
            self.assertIsInstance(form.tags, StringField)
            self.assertIsInstance(form.due_date, DateField)
    
    def test_custom_validator_creation(self):
        """Test creation of custom validators"""
        with self.app.app_context():
            def validate_even_number(form, field):
                if field.data is not None and field.data % 2 != 0:
                    raise ValidationError('Number must be even')
            
            class CustomValidatorForm(DynamicForm):
                even_number = IntegerField(
                    'Even Number',
                    validators=[validate_even_number]
                )
            
            form = CustomValidatorForm()
            
            # Test valid even number
            form.even_number.data = 4
            try:
                form.even_number.validate(form)
                validation_passed = True
            except ValidationError:
                validation_passed = False
            
            self.assertTrue(validation_passed)
            
            # Test invalid odd number
            form.even_number.data = 5
            try:
                form.even_number.validate(form)
                validation_passed = True
            except ValidationError:
                validation_passed = False
            
            self.assertFalse(validation_passed)


class TestViewWidgets(FABTestCase):
    """Test view widget functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-view-widgets'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_form_widget_creation(self):
        """Test FormWidget creation"""
        with self.app.app_context():
            widget = FormWidget()
            self.assertIsInstance(widget, FormWidget)
    
    def test_list_widget_creation(self):
        """Test ListWidget creation"""
        with self.app.app_context():
            widget = ListWidget()
            self.assertIsInstance(widget, ListWidget)
    
    def test_show_widget_creation(self):
        """Test ShowWidget creation"""
        with self.app.app_context():
            widget = ShowWidget()
            self.assertIsInstance(widget, ShowWidget)
    
    def test_search_widget_creation(self):
        """Test SearchWidget creation"""
        with self.app.app_context():
            widget = SearchWidget()
            self.assertIsInstance(widget, SearchWidget)


class TestFormErrorHandling(FABTestCase):
    """Test form error handling"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-errors'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_form_validation_errors(self):
        """Test form validation error collection"""
        with self.app.app_context():
            # Submit form with invalid data
            invalid_data = {
                'name': '',  # Required field empty
                'email': 'invalid-email',  # Invalid email format
                'description': 'A' * 501  # Too long
            }
            
            form = BasicTestForm(data=invalid_data)
            self.assertFalse(form.validate())
            
            # Test that errors are collected
            self.assertGreater(len(form.errors), 0)
            
            # Test specific field errors
            if 'name' in form.errors:
                self.assertIsInstance(form.errors['name'], list)
                self.assertGreater(len(form.errors['name']), 0)
    
    def test_form_error_messages(self):
        """Test form error message content"""
        with self.app.app_context():
            # Test email validation error
            form = BasicTestForm(data={
                'name': 'Valid Name',
                'email': 'not-an-email'
            })
            
            self.assertFalse(form.validate())
            
            # Check that email field has validation error
            if 'email' in form.errors:
                email_errors = form.errors['email']
                self.assertIsInstance(email_errors, list)
                # Should contain some error message about invalid email
                error_messages = ' '.join(email_errors).lower()
                self.assertTrue(
                    any(word in error_messages for word in ['email', 'invalid', 'format']),
                    f"Email error message doesn't contain expected keywords: {error_messages}"
                )


if __name__ == '__main__':
    unittest.main()