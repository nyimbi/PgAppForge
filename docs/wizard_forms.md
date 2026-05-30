# PgAppForge Wizard Forms

Comprehensive multi-step form functionality for handling large forms by breaking them into manageable steps with session persistence and resumption capabilities.

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Installation & Setup](#installation--setup)
4. [Quick Start](#quick-start)
5. [WizardForm Class](#wizardform-class)
6. [WizardStep Configuration](#wizardstep-configuration)
7. [WizardFormView](#wizardformview)
8. [Data Persistence](#data-persistence)
9. [Custom Steps](#custom-steps)
10. [Validation & Navigation](#validation--navigation)
11. [UI Customization](#ui-customization)
12. [JavaScript API](#javascript-api)
13. [Advanced Features](#advanced-features)
14. [Examples](#examples)
15. [Troubleshooting](#troubleshooting)

## Overview

The Wizard Forms system automatically converts large, complex forms into multi-step wizards with:

- **Automatic Step Generation**: Forms with more than N fields are automatically split into steps
- **Session Persistence**: Users can log off and return to complete forms later
- **Progress Tracking**: Visual progress indicators and step navigation
- **Draft Saving**: Auto-save functionality with manual save options
- **Responsive Design**: Mobile-friendly interface with touch support
- **Accessibility**: Keyboard navigation and screen reader support

## Key Features

### 🚀 Core Functionality
- **Multi-Step Navigation**: Previous, Next, and direct step navigation
- **Progress Indicators**: Visual progress bars and step completion status
- **Field Validation**: Per-step validation with real-time feedback
- **Session Persistence**: Redis, Database, or Session storage backends
- **Auto-Save**: Configurable auto-save intervals with visual feedback

### 🎨 User Interface
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Progress Visualization**: Progress bars, step indicators, completion percentages
- **Interactive Navigation**: Click-to-navigate steps (when allowed)
- **Keyboard Shortcuts**: Alt+Left/Right for navigation, Ctrl+S for save
- **Loading States**: Visual feedback during form operations

### 🔧 Developer Features
- **Automatic Configuration**: Minimal setup for basic usage
- **Custom Steps**: Full control over step definitions
- **Conditional Fields**: Show/hide fields based on other field values
- **Validation Rules**: Per-step and per-field validation
- **Extensible**: Easy to extend with custom functionality

## Installation & Setup

### Prerequisites

```bash
pip install PgAppForge>=4.0.0
pip install WTForms>=3.0.0
pip install Flask-Login>=0.6.0
```

### Basic Setup

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.forms.wizard import WizardForm
from pgappforge.views.wizard import WizardFormView
```

### Configuration

Add to your Flask application configuration:

```python
# Enable wizard forms
WIZARD_FORMS_ENABLED = True

# Default configuration
WIZARD_FIELDS_PER_STEP = 10  # Trigger wizard if more than 10 fields
WIZARD_AUTO_SAVE_INTERVAL = 30000  # Auto-save every 30 seconds
WIZARD_SESSION_TIMEOUT = 7  # Days before wizard data expires
WIZARD_STORAGE_BACKEND = 'session'  # 'session', 'database', or 'cache'
```

## Quick Start

### 1. Create a Wizard Form

```python
from wtforms import StringField, EmailField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, Length
from pgappforge.forms.wizard import WizardForm

class CustomerRegistrationForm(WizardForm):
    # Personal Information (Step 1)
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[DataRequired()])
    
    # Address Information (Step 2) 
    address = TextAreaField('Address', validators=[DataRequired()])
    city = StringField('City', validators=[DataRequired()])
    state = StringField('State', validators=[DataRequired()])
    zip_code = StringField('ZIP Code', validators=[DataRequired()])
    
    # Preferences (Step 3)
    contact_method = SelectField('Preferred Contact', choices=[
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('mail', 'Mail')
    ])
    newsletter = BooleanField('Subscribe to Newsletter')
    
    # Additional Information (Step 4)
    comments = TextAreaField('Additional Comments')
    referral_source = SelectField('How did you hear about us?', choices=[
        ('search', 'Search Engine'),
        ('social', 'Social Media'),
        ('friend', 'Friend/Referral'),
        ('advertisement', 'Advertisement')
    ])
```

### 2. Create a Wizard View

```python
from pgappforge.views.wizard import WizardFormView

class CustomerRegistrationView(WizardFormView):
    wizard_form_class = CustomerRegistrationForm
    wizard_title = 'Customer Registration'
    wizard_description = 'Register as a new customer in just a few steps'
    fields_per_step = 4  # 4 fields per step
    
    def process_wizard_submission(self, form, submission_id):
        """Process the completed form"""
        # Save to database
        customer_data = form.wizard_data.form_data
        
        # Create customer record
        customer = Customer(
            first_name=customer_data['first_name'],
            last_name=customer_data['last_name'],
            email=customer_data['email'],
            # ... other fields
        )
        
        db.session.add(customer)
        db.session.commit()
        
        # Send welcome email
        send_welcome_email(customer)
        
        return True  # Success
```

### 3. Register with PgAppForge

```python
# In your app.py
appbuilder.add_view(
    CustomerRegistrationView,
    "Customer Registration",
    category="Forms",
    icon="fa-user-plus"
)
```

### 4. Access the Wizard

Navigate to `/customerregistrationview/` or use the menu link. The form will automatically:

- Split into 4 steps (based on `fields_per_step=4`)
- Show progress indicators
- Enable auto-save every 30 seconds  
- Allow step navigation
- Persist data between sessions

## WizardForm Class

### Basic Configuration

```python
class MyWizardForm(WizardForm):
    # Form fields...
    name = StringField('Name', validators=[DataRequired()])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    
    # Wizard configuration (optional)
    def __init__(self, *args, **kwargs):
        # Override defaults
        kwargs.setdefault('fields_per_step', 5)
        kwargs.setdefault('allow_step_navigation', True)
        kwargs.setdefault('require_step_completion', True)
        kwargs.setdefault('auto_save_interval', 45000)  # 45 seconds
        super().__init__(*args, **kwargs)
```

### Constructor Parameters

```python
form = WizardForm(
    wizard_id='unique_form_id',           # Unique identifier
    wizard_title='My Form',               # Display title
    wizard_description='Form description', # Description text
    fields_per_step=8,                    # Fields per auto-generated step
    allow_step_navigation=True,           # Allow direct step navigation
    require_step_completion=True,         # Require step completion to proceed
    auto_save_interval=30000,             # Auto-save interval in milliseconds
    storage_backend='session',            # 'session', 'database', 'cache'
    expiration_days=7,                    # Days before wizard data expires
    custom_steps=None                     # Custom step definitions
)
```

### Methods

#### Navigation Methods
```python
# Step navigation
form.next_step()           # Move to next step
form.previous_step()       # Move to previous step
form.goto_step(2)         # Jump to specific step
form.can_navigate_to_step(2)  # Check if navigation is allowed

# Status checking
form.is_final_step()      # Check if on final step
form.get_current_step()   # Get current WizardStep object
form.get_progress_percentage()  # Get completion percentage
```

#### Validation Methods
```python
# Validation
form.validate_current_step()  # Validate current step only
form.validate()              # Validate entire form
form.can_proceed_to_next_step()  # Check if can proceed

# Data management
form.save_wizard_data()      # Save current state
form.get_current_step_data()  # Get data for current step
```

#### Submission Methods
```python
# Final submission
submission_id = form.submit_wizard()  # Submit completed form
form.cleanup_wizard_data()   # Clean up after successful submission
```

## WizardStep Configuration

### Basic WizardStep

```python
from pgappforge.forms.wizard import WizardStep

step = WizardStep(
    name='personal_info',                    # Unique step identifier
    title='Personal Information',            # Display title
    fields=['first_name', 'last_name', 'email'],  # Field names in step
    description='Enter your personal details', # Optional description
    required_fields=['first_name', 'email'], # Required fields
    icon='fa-user'                          # Font Awesome icon
)
```

### Advanced WizardStep with Validation

```python
def validate_age(value):
    if int(value) < 18:
        raise ValidationError('Must be 18 or older')

step = WizardStep(
    name='personal_details',
    title='Personal Details',
    fields=['name', 'age', 'phone', 'address'],
    required_fields=['name', 'age'],
    validation_rules={
        'name': {
            'min_length': 2,
            'max_length': 50,
            'pattern': r'^[a-zA-Z\s]+$'
        },
        'age': {
            'custom': validate_age
        },
        'phone': {
            'pattern': r'^\+?[\d\s\-\(\)]+$'
        }
    },
    conditional_fields={
        'address': {'age': '18+'}  # Show address only if age >= 18
    },
    icon='fa-user-circle'
)
```

### Conditional Field Logic

```python
# Show different fields based on user selection
step = WizardStep(
    name='contact_preferences',
    title='Contact Preferences',
    fields=['contact_method', 'email', 'phone', 'mailing_address'],
    conditional_fields={
        'email': {'contact_method': 'email'},
        'phone': {'contact_method': 'phone'},
        'mailing_address': {'contact_method': 'mail'}
    },
    required_fields=['contact_method']
)
```

## WizardFormView

### Basic View Configuration

```python
class MyWizardView(WizardFormView):
    wizard_form_class = MyWizardForm
    wizard_title = 'My Wizard Form'
    wizard_description = 'Complete this form in easy steps'
    
    # Step configuration
    fields_per_step = 6
    allow_step_navigation = True
    require_step_completion = True
    
    # UI configuration
    show_progress_bar = True
    show_step_list = True
    show_navigation_buttons = True
    enable_auto_save = True
    auto_save_interval = 30000
    
    # Storage configuration
    storage_backend = 'session'
    expiration_days = 7
```

### Custom Processing

```python
class AdvancedWizardView(WizardFormView):
    wizard_form_class = MyWizardForm
    
    def process_wizard_submission(self, form, submission_id):
        """Custom submission processing"""
        try:
            data = form.wizard_data.form_data
            
            # Validate business rules
            if not self.validate_business_rules(data):
                return False
            
            # Save to database
            record = self.save_to_database(data)
            
            # Send notifications
            self.send_notifications(record, data)
            
            # Update external systems
            self.update_external_systems(record)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing submission: {e}")
            return False
    
    def validate_business_rules(self, data):
        """Custom business logic validation"""
        # Implement your validation logic
        return True
    
    def save_to_database(self, data):
        """Save form data to database"""
        # Create database records
        pass
    
    def send_notifications(self, record, data):
        """Send email notifications"""
        # Send emails to admins, users, etc.
        pass
```

### View Endpoints

The wizard view automatically provides these endpoints:

- `GET /wizard/` - Main wizard form
- `GET /wizard/<wizard_id>` - Resume specific wizard
- `POST /wizard/` - Process form submissions
- `POST /api/save_draft` - Save draft via AJAX
- `POST /api/validate_step` - Validate step via AJAX
- `GET /api/wizard_status/<wizard_id>` - Get wizard status

### Custom Templates

Override default templates:

```python
class CustomWizardView(WizardFormView):
    wizard_template = 'my_wizard.html'
    wizard_success_template = 'my_success.html'
```

## Data Persistence

### Storage Backends

#### Session Storage (Default)
```python
# Stores data in Flask session
storage_backend = 'session'

# Pros: Simple, no database setup required
# Cons: Limited storage size, lost if session expires
# Best for: Development, simple forms
```

#### Database Storage
```python
# Stores data in database table
storage_backend = 'database'

# Pros: Persistent, unlimited size, queryable
# Cons: Requires database setup
# Best for: Production, complex forms, audit trails
```

#### Cache Storage  
```python
# Stores data in Redis/Memcached
storage_backend = 'cache'

# Pros: Fast access, automatic expiration
# Cons: Requires cache setup, may be volatile  
# Best for: High-performance applications
```

### Persistence Configuration

```python
from pgappforge.forms.wizard import WizardFormPersistence

# Custom persistence setup
persistence = WizardFormPersistence('database')

# Save wizard data
wizard_data = WizardFormData('wizard_123', 'user_456')
wizard_data.form_data = {'name': 'John', 'email': 'john@example.com'}
success = persistence.save_wizard_data(wizard_data)

# Load wizard data
loaded_data = persistence.load_wizard_data('wizard_123', 'user_456')

# Delete wizard data (cleanup after submission)
persistence.delete_wizard_data('wizard_123', 'user_456')
```

### Data Expiration

```python
# Configure data expiration
form = WizardForm(
    expiration_days=14,  # Keep data for 14 days
    wizard_id='long_form_123'
)

# Check if data is expired
if form.wizard_data and form.wizard_data.is_expired():
    print("Wizard data has expired")
    form.cleanup_wizard_data()
```

## Custom Steps

### Define Custom Steps

```python
from pgappforge.forms.wizard import WizardStep

# Define custom steps
custom_steps = [
    WizardStep(
        name='basic_info',
        title='Basic Information',
        fields=['name', 'email', 'phone'],
        required_fields=['name', 'email'],
        description='Enter your basic contact information',
        icon='fa-user'
    ),
    WizardStep(
        name='address',
        title='Address Information', 
        fields=['street', 'city', 'state', 'zip'],
        required_fields=['street', 'city', 'state'],
        description='Provide your mailing address',
        icon='fa-home'
    ),
    WizardStep(
        name='preferences',
        title='Preferences',
        fields=['contact_method', 'newsletter', 'notifications'],
        description='Set your communication preferences',
        icon='fa-cog'
    )
]

# Use custom steps in form
class CustomStepForm(WizardForm):
    # Define all fields...
    name = StringField('Name')
    email = EmailField('Email')
    # ... etc
    
    def __init__(self, *args, **kwargs):
        kwargs['custom_steps'] = custom_steps
        super().__init__(*args, **kwargs)
```

### Step Templates

Create custom step templates:

```python
step = WizardStep(
    name='custom_step',
    title='Custom Step',
    fields=['field1', 'field2'],
    template='custom_step_template.html'  # Custom template
)
```

### Dynamic Steps

Generate steps dynamically:

```python
def generate_dynamic_steps(form_fields, user_role):
    steps = []
    
    # Admin users get additional steps
    if user_role == 'admin':
        steps.append(WizardStep(
            name='admin_fields',
            title='Administrative Fields',
            fields=['admin_notes', 'approval_required'],
            icon='fa-shield-alt'
        ))
    
    # Standard user steps
    field_chunks = [form_fields[i:i+5] for i in range(0, len(form_fields), 5)]
    
    for i, chunk in enumerate(field_chunks):
        steps.append(WizardStep(
            name=f'step_{i+1}',
            title=f'Step {i+1}',
            fields=chunk
        ))
    
    return steps
```

## Validation & Navigation

### Step Validation Rules

```python
# Per-field validation rules
validation_rules = {
    'email': {
        'pattern': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        'custom': lambda value: validate_email_domain(value)
    },
    'phone': {
        'min_length': 10,
        'max_length': 15,
        'pattern': r'^\+?[\d\s\-\(\)]+$'
    },
    'age': {
        'custom': lambda value: int(value) >= 18
    }
}

step = WizardStep(
    name='contact_info',
    title='Contact Information',
    fields=['email', 'phone', 'age'],
    validation_rules=validation_rules
)
```

### Navigation Control

```python
class RestrictedNavigationView(WizardFormView):
    # Require step completion before proceeding
    require_step_completion = True
    
    # Disable free navigation between steps  
    allow_step_navigation = False
    
    def can_navigate_to_step(self, form, target_step):
        """Custom navigation logic"""
        # Only allow forward navigation to next step
        if target_step > form.current_step_index + 1:
            return False
        
        # Require admin role for certain steps
        if target_step >= 3 and not current_user.has_role('admin'):
            return False
            
        return True
```

### Real-time Validation

Enable client-side validation:

```javascript
// Auto-validate fields on blur
$('.wizard-form input, .wizard-form select').on('blur', function() {
    validateField($(this));
});

// Validate entire step before navigation
$('.btn-next').on('click', function(e) {
    if (!validateCurrentStep()) {
        e.preventDefault();
        showValidationErrors();
    }
});
```

## UI Customization

### Custom CSS Styling

```css
/* Override wizard styles */
.wizard-container {
    max-width: 1000px;
    margin: 0 auto;
    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
}

.wizard-progress .progress-bar {
    background: linear-gradient(90deg, #28a745, #20c997);
}

.step-item.current .step-icon {
    background: #007bff;
    box-shadow: 0 0 0 4px rgba(0,123,255,0.3);
}

/* Custom step styling */
.step-content {
    background: linear-gradient(135deg, #f8f9fa, #e9ecef);
    border: none;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
}
```

### Progress Indicator Customization

```python
class CustomProgressView(WizardFormView):
    def get_template_vars(self):
        vars = super().get_template_vars()
        
        # Add custom progress calculation
        vars['custom_progress'] = self.calculate_weighted_progress()
        
        # Add step icons
        vars['step_icons'] = [
            'fa-user', 'fa-home', 'fa-credit-card', 'fa-check'
        ]
        
        return vars
    
    def calculate_weighted_progress(self):
        """Calculate progress with step weights"""
        weights = [0.3, 0.3, 0.3, 0.1]  # Different weights per step
        # Implementation...
        return weighted_progress
```

### Mobile Responsive Design

The wizard automatically includes responsive design, but you can customize:

```css
/* Mobile-specific styling */
@media (max-width: 768px) {
    .wizard-container {
        margin: 10px;
        padding: 15px;
    }
    
    .step-navigation {
        flex-direction: column;
        gap: 10px;
    }
    
    .wizard-navigation {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 15px;
        background: white;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
    }
}
```

## JavaScript API

### Auto-Save Configuration

```javascript
// Configure auto-save
$(document).ready(function() {
    const wizardForm = {
        autoSaveInterval: 30000,  // 30 seconds
        
        init: function() {
            this.setupAutoSave();
        },
        
        setupAutoSave: function() {
            setInterval(() => {
                this.performAutoSave();
            }, this.autoSaveInterval);
        },
        
        performAutoSave: function() {
            const formData = this.serializeFormData();
            
            $.ajax({
                url: '/api/save_draft',
                method: 'POST',
                data: JSON.stringify(formData),
                contentType: 'application/json',
                success: (response) => {
                    this.showSaveIndicator('saved');
                },
                error: () => {
                    this.showSaveIndicator('error');
                }
            });
        }
    };
    
    wizardForm.init();
});
```

### Step Navigation

```javascript
// Custom step navigation
function navigateToStep(stepIndex) {
    // Validate current step before navigation
    if (!validateCurrentStep()) {
        alert('Please complete all required fields');
        return;
    }
    
    // Update form and submit
    $('input[name="current_step"]').val(stepIndex);
    $('input[name="wizard_action"]').val('goto');
    $('#wizardForm').submit();
}

// Keyboard shortcuts
$(document).on('keydown', function(e) {
    // Alt + Left Arrow: Previous step
    if (e.altKey && e.keyCode === 37) {
        e.preventDefault();
        $('.btn-previous').click();
    }
    // Alt + Right Arrow: Next step
    else if (e.altKey && e.keyCode === 39) {
        e.preventDefault();
        $('.btn-next').click();
    }
    // Ctrl + S: Save draft
    else if (e.ctrlKey && e.keyCode === 83) {
        e.preventDefault();
        $('.btn-save-draft').click();
    }
});
```

### Form Validation

```javascript
// Real-time validation
function validateField(field) {
    const value = field.val();
    const fieldName = field.attr('name');
    const validators = getFieldValidators(fieldName);
    
    let isValid = true;
    let errorMessage = '';
    
    // Run validation rules
    validators.forEach(validator => {
        if (!validator.validate(value)) {
            isValid = false;
            errorMessage = validator.message;
            return false;
        }
    });
    
    // Update UI
    field.toggleClass('is-invalid', !isValid);
    field.siblings('.invalid-feedback').text(errorMessage);
    
    return isValid;
}

// Step validation
function validateCurrentStep() {
    let isValid = true;
    
    $('.step-content input, .step-content select, .step-content textarea')
        .each(function() {
            if (!validateField($(this))) {
                isValid = false;
            }
        });
    
    return isValid;
}
```

### Progress Updates

```javascript
// Update progress dynamically
function updateProgress() {
    const totalSteps = parseInt($('[data-total-steps]').data('total-steps'));
    const currentStep = parseInt($('[data-current-step]').data('current-step'));
    
    // Calculate completion
    const completedFields = $('.step-content input:filled').length;
    const totalFields = $('.step-content input').length;
    const stepProgress = (completedFields / totalFields) * 100;
    
    // Update progress bar
    const overallProgress = ((currentStep - 1) / totalSteps * 100) + (stepProgress / totalSteps);
    $('.progress-bar').css('width', overallProgress + '%');
    $('.progress-text').text(`${Math.round(overallProgress)}% complete`);
}

// Update on field changes
$('.step-content input, .step-content select, .step-content textarea')
    .on('input change', updateProgress);
```

## Advanced Features

### Conditional Field Display

```python
# Define conditional logic
conditional_fields = {
    'spouse_name': {'marital_status': 'married'},
    'spouse_email': {'marital_status': 'married'},
    'emergency_contact': {'has_emergency_contact': True},
    'dietary_restrictions': {'has_dietary_needs': True}
}

step = WizardStep(
    name='personal_details',
    title='Personal Details',
    fields=['marital_status', 'spouse_name', 'spouse_email', 
            'has_emergency_contact', 'emergency_contact',
            'has_dietary_needs', 'dietary_restrictions'],
    conditional_fields=conditional_fields
)
```

### File Upload in Wizard

```python
from wtforms import FileField
from wtforms.validators import FileRequired

class DocumentWizardForm(WizardForm):
    # Document upload step
    resume = FileField('Resume', validators=[FileRequired()])
    cover_letter = FileField('Cover Letter')
    portfolio = FileField('Portfolio (Optional)')
    
    # File handling in view
    def process_wizard_submission(self, form, submission_id):
        files = {}
        
        # Save uploaded files
        for field_name, field in form._fields.items():
            if isinstance(field, FileField) and field.data:
                filename = secure_filename(field.data.filename)
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                field.data.save(file_path)
                files[field_name] = file_path
        
        # Process with file paths
        return self.process_with_files(form.wizard_data.form_data, files)
```

### Multi-Language Support

```python
from flask_babel import gettext, lazy_gettext

class MultiLangWizardForm(WizardForm):
    name = StringField(lazy_gettext('Name'), validators=[DataRequired()])
    email = EmailField(lazy_gettext('Email'), validators=[DataRequired(), Email()])
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Localized step titles
        self.custom_steps = [
            WizardStep(
                name='personal',
                title=lazy_gettext('Personal Information'),
                fields=['name', 'email'],
                description=lazy_gettext('Enter your personal details')
            )
        ]
```

### Integration with PgAppForge ModelView

```python
from pgappforge.models.mixins import AuditMixin

class WizardEnabledModelView(ModelView):
    # Enable wizard for forms with many fields
    enable_wizard = True
    wizard_threshold = 8  # Use wizard if more than 8 fields
    
    # Wizard configuration
    wizard_fields_per_step = 5
    wizard_custom_steps = None
    
    def add(self):
        """Override add method to use wizard for large forms"""
        if self.enable_wizard and self._should_use_wizard():
            return redirect(url_for(f'{self.__class__.__name__}.wizard_add'))
        
        return super().add()
    
    def _should_use_wizard(self):
        """Check if wizard should be used"""
        return len(self.add_columns) > self.wizard_threshold
    
    @expose('/wizard_add')
    def wizard_add(self):
        """Wizard-based add form"""
        # Create dynamic wizard form from model
        wizard_form = self._create_model_wizard_form()
        # Render wizard template
        return self._render_wizard(wizard_form)
```

## Examples

### Example 1: Employee Onboarding

```python
class EmployeeOnboardingForm(WizardForm):
    # Personal Information
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = EmailField('Work Email', validators=[DataRequired(), Email()])
    phone = TelField('Phone Number', validators=[DataRequired()])
    emergency_contact = StringField('Emergency Contact', validators=[DataRequired()])
    
    # Employment Details
    employee_id = StringField('Employee ID', validators=[DataRequired()])
    department = SelectField('Department', validators=[DataRequired()])
    position = StringField('Position', validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()])
    manager = SelectField('Direct Manager', validators=[DataRequired()])
    
    # IT Setup
    computer_type = SelectField('Computer Preference', choices=[
        ('laptop', 'Laptop'), ('desktop', 'Desktop')
    ])
    software_requirements = SelectMultipleField('Required Software')
    email_signature = TextAreaField('Email Signature')
    
    # Benefits Enrollment
    health_insurance = BooleanField('Enroll in Health Insurance')
    dental_insurance = BooleanField('Enroll in Dental Insurance')
    retirement_plan = SelectField('Retirement Plan', choices=[
        ('401k', '401(k)'), ('roth', 'Roth IRA'), ('none', 'None')
    ])
    
    # Legal and Compliance
    handbook_acknowledged = BooleanField('Employee Handbook Acknowledged', 
                                       validators=[DataRequired()])
    confidentiality_agreed = BooleanField('Confidentiality Agreement', 
                                        validators=[DataRequired()])
    background_check_consent = BooleanField('Background Check Consent', 
                                          validators=[DataRequired()])

class EmployeeOnboardingView(WizardFormView):
    wizard_form_class = EmployeeOnboardingForm
    wizard_title = 'Employee Onboarding'
    wizard_description = 'Complete your employee onboarding process'
    fields_per_step = 5
    
    # Custom steps with specific grouping
    custom_steps = [
        WizardStep(
            name='personal_info',
            title='Personal Information',
            fields=['first_name', 'last_name', 'email', 'phone', 'emergency_contact'],
            required_fields=['first_name', 'last_name', 'email', 'phone', 'emergency_contact'],
            icon='fa-user'
        ),
        WizardStep(
            name='employment',
            title='Employment Details',
            fields=['employee_id', 'department', 'position', 'start_date', 'manager'],
            required_fields=['employee_id', 'department', 'position', 'start_date', 'manager'],
            icon='fa-briefcase'
        ),
        WizardStep(
            name='it_setup',
            title='IT Setup',
            fields=['computer_type', 'software_requirements', 'email_signature'],
            icon='fa-laptop'
        ),
        WizardStep(
            name='benefits',
            title='Benefits Enrollment',
            fields=['health_insurance', 'dental_insurance', 'retirement_plan'],
            icon='fa-heart'
        ),
        WizardStep(
            name='legal',
            title='Legal & Compliance',
            fields=['handbook_acknowledged', 'confidentiality_agreed', 'background_check_consent'],
            required_fields=['handbook_acknowledged', 'confidentiality_agreed', 'background_check_consent'],
            icon='fa-gavel'
        )
    ]
    
    def process_wizard_submission(self, form, submission_id):
        """Process completed onboarding"""
        data = form.wizard_data.form_data
        
        # Create employee record
        employee = Employee(
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            employee_id=data['employee_id'],
            department=data['department'],
            position=data['position'],
            start_date=data['start_date']
        )
        
        db.session.add(employee)
        db.session.commit()
        
        # Trigger onboarding workflow
        self.trigger_onboarding_workflow(employee, data)
        
        # Send notifications
        self.send_onboarding_notifications(employee, data)
        
        return True
```

### Example 2: Multi-Step Survey

```python
class CustomerSatisfactionSurvey(WizardForm):
    # Customer Information
    customer_id = StringField('Customer ID', validators=[OptionalValidator()])
    name = StringField('Name', validators=[DataRequired()])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    purchase_date = DateField('Purchase Date', validators=[DataRequired()])
    
    # Product Experience
    product_satisfaction = RadioField('Product Satisfaction', choices=[
        ('5', 'Very Satisfied'),
        ('4', 'Satisfied'),
        ('3', 'Neutral'),
        ('2', 'Dissatisfied'),
        ('1', 'Very Dissatisfied')
    ], validators=[DataRequired()])
    
    product_quality = RadioField('Product Quality', choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], validators=[DataRequired()])
    
    # Service Experience
    customer_service_rating = RadioField('Customer Service', choices=[
        ('5', 'Excellent'),
        ('4', 'Good'),
        ('3', 'Average'),
        ('2', 'Below Average'),
        ('1', 'Poor')
    ])
    
    delivery_satisfaction = RadioField('Delivery Experience', choices=[
        ('5', 'Very Satisfied'),
        ('4', 'Satisfied'),
        ('3', 'Neutral'),
        ('2', 'Dissatisfied'),
        ('1', 'Very Dissatisfied')
    ])
    
    # Feedback
    positive_feedback = TextAreaField('What did we do well?')
    improvement_suggestions = TextAreaField('How can we improve?')
    additional_comments = TextAreaField('Additional Comments')
    
    # Future Engagement
    recommend_likelihood = RadioField('Likelihood to Recommend', choices=[
        ('10', '10 - Extremely Likely'),
        ('9', '9'),
        ('8', '8'),
        ('7', '7'),
        ('6', '6'),
        ('5', '5'),
        ('4', '4'),
        ('3', '3'),
        ('2', '2'),
        ('1', '1'),
        ('0', '0 - Not at all Likely')
    ], validators=[DataRequired()])

class SurveyView(WizardFormView):
    wizard_form_class = CustomerSatisfactionSurvey
    wizard_title = 'Customer Satisfaction Survey'
    wizard_description = 'Help us improve by sharing your feedback'
    
    # Custom steps for logical grouping
    def __init__(self):
        super().__init__()
        self.custom_steps = [
            WizardStep(
                name='customer_info',
                title='Customer Information',
                fields=['customer_id', 'name', 'email', 'purchase_date'],
                required_fields=['name', 'email', 'purchase_date'],
                description='Tell us about your recent purchase',
                icon='fa-user'
            ),
            WizardStep(
                name='product_experience',
                title='Product Experience',
                fields=['product_satisfaction', 'product_quality'],
                required_fields=['product_satisfaction', 'product_quality'],
                description='Rate your product experience',
                icon='fa-box'
            ),
            WizardStep(
                name='service_experience',
                title='Service Experience',
                fields=['customer_service_rating', 'delivery_satisfaction'],
                description='Rate our service quality',
                icon='fa-handshake'
            ),
            WizardStep(
                name='feedback',
                title='Your Feedback',
                fields=['positive_feedback', 'improvement_suggestions', 'additional_comments'],
                description='Share your thoughts with us',
                icon='fa-comment'
            ),
            WizardStep(
                name='recommendation',
                title='Recommendation',
                fields=['recommend_likelihood'],
                required_fields=['recommend_likelihood'],
                description='Help us understand your loyalty',
                icon='fa-thumbs-up'
            )
        ]
```

## Troubleshooting

### Common Issues

#### Wizard Not Displaying
```python
# Check form field count
form = MyWizardForm()
print(f"Field count: {len(form._fields)}")
print(f"Fields per step: {form.fields_per_step}")

# Ensure threshold is met
if len(form._fields) <= form.fields_per_step:
    print("Not enough fields to trigger wizard")
```

#### Session Data Not Persisting
```python
# Check session configuration
app.config['SECRET_KEY'] = 'your-secret-key'  # Required
app.config['SESSION_COOKIE_SECURE'] = False   # For development

# Check storage backend
form = WizardForm(storage_backend='session')
success = form.save_wizard_data()
if not success:
    print("Failed to save wizard data")
```

#### Step Navigation Issues
```python
# Check navigation permissions
form = WizardForm(
    allow_step_navigation=True,     # Enable navigation
    require_step_completion=False   # Allow incomplete steps
)

# Debug navigation
print(f"Can navigate to step 2: {form.can_navigate_to_step(2)}")
print(f"Current step: {form.current_step_index}")
print(f"Completed steps: {form.wizard_data.completed_steps}")
```

#### Validation Problems
```python
# Debug validation
current_step = form.get_current_step()
if current_step:
    form_data = form.get_current_step_data()
    is_valid, errors = current_step.validate_step(form_data)
    
    if not is_valid:
        print(f"Validation errors: {errors}")
        for field, field_errors in errors.items():
            print(f"  {field}: {field_errors}")
```

### Performance Optimization

#### Large Forms
```python
# Use pagination for very large forms
class LargeWizardForm(WizardForm):
    def __init__(self, *args, **kwargs):
        kwargs['fields_per_step'] = 8  # Smaller steps
        kwargs['auto_save_interval'] = 60000  # Less frequent saves
        super().__init__(*args, **kwargs)
```

#### Database Storage
```python
# Optimize database storage
class OptimizedPersistence(WizardFormPersistence):
    def save_wizard_data(self, wizard_data):
        # Compress data before storing
        import json, gzip
        
        json_data = json.dumps(wizard_data.to_dict())
        compressed_data = gzip.compress(json_data.encode())
        
        # Store compressed data
        return super().save_wizard_data_compressed(compressed_data)
```

#### Memory Usage
```python
# Clear unused wizard data periodically
from datetime import datetime, timedelta

def cleanup_expired_wizards():
    """Clean up expired wizard data"""
    cutoff_date = datetime.utcnow() - timedelta(days=7)
    
    # Database cleanup
    db.session.query(WizardData)\
        .filter(WizardData.expires_at < cutoff_date)\
        .delete()
    
    db.session.commit()

# Schedule cleanup job
from celery import Celery
from celery.schedules import crontab

@celery.task
def scheduled_cleanup():
    cleanup_expired_wizards()

# Run daily at 2 AM
celery.conf.beat_schedule = {
    'cleanup-wizards': {
        'task': 'scheduled_cleanup',
        'schedule': crontab(hour=2, minute=0),
    },
}
```

### Debugging Tips

#### Enable Debug Logging
```python
import logging

# Enable wizard debug logging
logging.getLogger('pgappforge.forms.wizard').setLevel(logging.DEBUG)
logging.getLogger('pgappforge.views.wizard').setLevel(logging.DEBUG)

# Custom debug information
class DebugWizardView(WizardFormView):
    def _handle_wizard_post(self, form):
        print(f"Debug: Processing wizard action: {request.form.get('wizard_action')}")
        print(f"Debug: Current step: {form.current_step_index}")
        print(f"Debug: Form data: {form.wizard_data.form_data}")
        
        return super()._handle_wizard_post(form)
```

#### Client-Side Debugging
```javascript
// Enable wizard debugging in browser console
window.wizardDebug = true;

// Debug wizard state
console.log('Wizard State:', {
    currentStep: $('[name="current_step"]').val(),
    wizardId: $('[name="wizard_id"]').val(),
    formData: wizardForm.serializeFormData(),
    validationState: wizardForm.getValidationState()
});
```

---

## Conclusion

The PgAppForge Wizard Forms system provides a comprehensive solution for handling large, complex forms by automatically breaking them into manageable steps with session persistence and user-friendly navigation.

### Key Benefits:
- 🚀 **Improved User Experience**: Break complex forms into digestible steps
- 💾 **Data Persistence**: Users can resume forms later without losing progress  
- 📱 **Mobile Responsive**: Works seamlessly across all devices
- ⚡ **Auto-Save**: Prevents data loss with configurable auto-save
- 🎨 **Customizable**: Flexible styling and step configuration
- 🔧 **Developer Friendly**: Minimal configuration for basic usage

### Next Steps:
1. Install the wizard form components
2. Try the examples provided
3. Customize for your specific use cases
4. Implement in your production applications

For more examples and advanced usage, see the `examples/wizard_forms_example.py` file.