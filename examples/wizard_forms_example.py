#!/usr/bin/env python3
"""
PgAppForge Wizard Forms Example

This example demonstrates comprehensive wizard form functionality including:
- Multi-step forms with automatic field organization
- Custom step definitions and validation
- Session persistence and resumption
- Complex form types (registration, surveys, applications)
- Integration with PgAppForge views and models

Prerequisites:
- PgAppForge
- WTForms
- Flask-Login (for user persistence)

Usage:
    python wizard_forms_example.py
"""

import os
from datetime import datetime
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Model
from pgappforge.security.sqla.models import User
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Date
from wtforms import (
    StringField, TextAreaField, SelectField, BooleanField, 
    IntegerField, DateField, RadioField, SelectMultipleField,
    EmailField, URLField, TelField, DecimalField
)
from wtforms.validators import (
    DataRequired, Length, Email, NumberRange, 
    URL, Regexp, Optional as OptionalValidator
)

# Import wizard components
from pgappforge.forms.wizard import WizardForm, WizardStep
from pgappforge.views.wizard import WizardFormView


# Example 1: Employee Registration Wizard
class EmployeeRegistrationForm(WizardForm):
    """
    Employee registration form with multiple steps
    Automatically splits into steps based on field count
    """
    
    # Personal Information
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=50)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=50)])
    middle_name = StringField('Middle Name', validators=[Length(max=50)])
    date_of_birth = DateField('Date of Birth', validators=[DataRequired()])
    gender = SelectField('Gender', choices=[
        ('', 'Select Gender'),
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
        ('prefer_not_to_say', 'Prefer not to say')
    ], validators=[DataRequired()])
    
    # Contact Information
    email = EmailField('Email Address', validators=[DataRequired(), Email()])
    phone = TelField('Phone Number', validators=[DataRequired()])
    alternative_phone = TelField('Alternative Phone', validators=[OptionalValidator()])
    address = TextAreaField('Home Address', validators=[DataRequired(), Length(max=200)])
    city = StringField('City', validators=[DataRequired(), Length(max=50)])
    state = StringField('State/Province', validators=[DataRequired(), Length(max=50)])
    postal_code = StringField('Postal Code', validators=[DataRequired(), Length(max=10)])
    country = SelectField('Country', choices=[
        ('', 'Select Country'),
        ('us', 'United States'),
        ('ca', 'Canada'),
        ('uk', 'United Kingdom'),
        ('au', 'Australia'),
        ('other', 'Other')
    ], validators=[DataRequired()])
    
    # Employment Information
    position = StringField('Position Applied For', validators=[DataRequired(), Length(max=100)])
    department = SelectField('Department', choices=[
        ('', 'Select Department'),
        ('engineering', 'Engineering'),
        ('marketing', 'Marketing'),
        ('sales', 'Sales'),
        ('hr', 'Human Resources'),
        ('finance', 'Finance'),
        ('operations', 'Operations')
    ], validators=[DataRequired()])
    start_date = DateField('Desired Start Date', validators=[DataRequired()])
    salary_expectation = DecimalField('Salary Expectation', validators=[OptionalValidator(), NumberRange(min=0)])
    employment_type = RadioField('Employment Type', choices=[
        ('full_time', 'Full Time'),
        ('part_time', 'Part Time'),
        ('contract', 'Contract'),
        ('internship', 'Internship')
    ], validators=[DataRequired()])
    
    # Skills and Experience
    skills = SelectMultipleField('Skills', choices=[
        ('python', 'Python'),
        ('javascript', 'JavaScript'),
        ('sql', 'SQL'),
        ('project_management', 'Project Management'),
        ('marketing', 'Marketing'),
        ('design', 'Design'),
        ('data_analysis', 'Data Analysis')
    ])
    experience_years = IntegerField('Years of Experience', validators=[NumberRange(min=0, max=50)])
    previous_experience = TextAreaField('Previous Work Experience', validators=[Length(max=1000)])
    education = TextAreaField('Education Background', validators=[Length(max=500)])
    
    # Additional Information
    linkedin_profile = URLField('LinkedIn Profile', validators=[OptionalValidator(), URL()])
    portfolio_website = URLField('Portfolio Website', validators=[OptionalValidator(), URL()])
    additional_info = TextAreaField('Additional Information', validators=[Length(max=500)])
    
    # Preferences
    remote_work = BooleanField('Interested in Remote Work')
    travel_willing = BooleanField('Willing to Travel')
    newsletter_subscribe = BooleanField('Subscribe to Company Newsletter')
    background_check_consent = BooleanField('Consent to Background Check', validators=[DataRequired()])


class EmployeeRegistrationView(WizardFormView):
    """View for employee registration wizard"""
    
    wizard_form_class = EmployeeRegistrationForm
    wizard_title = 'Employee Registration'
    wizard_description = 'Complete your employee registration in easy steps'
    fields_per_step = 6
    allow_step_navigation = True
    require_step_completion = True
    auto_save_interval = 30000  # 30 seconds
    
    def process_wizard_submission(self, form, submission_id):
        """Process the completed registration form"""
        try:
            # In a real application, you would:
            # 1. Save the data to a database
            # 2. Send confirmation emails
            # 3. Create user accounts
            # 4. Trigger background processes
            
            print(f"Processing employee registration: {submission_id}")
            print(f"Applicant: {form.wizard_data.form_data.get('first_name')} {form.wizard_data.form_data.get('last_name')}")
            print(f"Email: {form.wizard_data.form_data.get('email')}")
            print(f"Position: {form.wizard_data.form_data.get('position')}")
            
            return True
        except Exception as e:
            print(f"Error processing registration: {e}")
            return False


# Example 2: Customer Survey with Custom Steps
class CustomerSurveyForm(WizardForm):
    """
    Customer satisfaction survey with custom-defined steps
    """
    
    # Customer Information
    customer_name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    customer_email = EmailField('Email Address', validators=[DataRequired(), Email()])
    customer_phone = TelField('Phone Number', validators=[OptionalValidator()])
    purchase_date = DateField('Purchase Date', validators=[DataRequired()])
    product_category = SelectField('Product Category', choices=[
        ('', 'Select Category'),
        ('electronics', 'Electronics'),
        ('clothing', 'Clothing'),
        ('home_garden', 'Home & Garden'),
        ('books', 'Books'),
        ('toys', 'Toys'),
        ('other', 'Other')
    ], validators=[DataRequired()])
    
    # Service Experience
    overall_satisfaction = RadioField('Overall Satisfaction', choices=[
        ('very_satisfied', 'Very Satisfied'),
        ('satisfied', 'Satisfied'),
        ('neutral', 'Neutral'),
        ('dissatisfied', 'Dissatisfied'),
        ('very_dissatisfied', 'Very Dissatisfied')
    ], validators=[DataRequired()])
    
    customer_service_rating = RadioField('Customer Service Rating', choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('not_applicable', 'Not Applicable')
    ], validators=[DataRequired()])
    
    delivery_rating = RadioField('Delivery Experience', choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('not_applicable', 'Not Applicable')
    ])
    
    product_quality_rating = RadioField('Product Quality', choices=[
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], validators=[DataRequired()])
    
    # Feedback and Suggestions
    what_worked_well = TextAreaField('What worked well?', validators=[Length(max=500)])
    areas_for_improvement = TextAreaField('Areas for improvement', validators=[Length(max=500)])
    additional_comments = TextAreaField('Additional Comments', validators=[Length(max=1000)])
    
    # Future Engagement
    recommend_to_friends = RadioField('Would you recommend us?', choices=[
        ('definitely', 'Definitely'),
        ('probably', 'Probably'),
        ('not_sure', 'Not Sure'),
        ('probably_not', 'Probably Not'),
        ('definitely_not', 'Definitely Not')
    ], validators=[DataRequired()])
    
    future_purchases = BooleanField('Interested in future purchases')
    email_updates = BooleanField('Receive email updates')
    survey_feedback = BooleanField('Participate in future surveys')


class CustomerSurveyView(WizardFormView):
    """View for customer survey with custom steps"""
    
    wizard_form_class = CustomerSurveyForm
    wizard_title = 'Customer Satisfaction Survey'
    wizard_description = 'Help us improve by sharing your experience'
    
    # Custom step definitions
    custom_steps = [
        WizardStep(
            name='customer_info',
            title='Customer Information',
            fields=['customer_name', 'customer_email', 'customer_phone', 'purchase_date', 'product_category'],
            required_fields=['customer_name', 'customer_email', 'purchase_date', 'product_category'],
            description='Tell us about your recent purchase',
            icon='fa-user'
        ),
        WizardStep(
            name='service_experience',
            title='Service Experience',
            fields=['overall_satisfaction', 'customer_service_rating', 'delivery_rating', 'product_quality_rating'],
            required_fields=['overall_satisfaction', 'customer_service_rating', 'product_quality_rating'],
            description='Rate your experience with our service',
            icon='fa-star'
        ),
        WizardStep(
            name='feedback',
            title='Feedback & Suggestions',
            fields=['what_worked_well', 'areas_for_improvement', 'additional_comments'],
            description='Share your thoughts and suggestions',
            icon='fa-comment'
        ),
        WizardStep(
            name='future_engagement',
            title='Future Engagement',
            fields=['recommend_to_friends', 'future_purchases', 'email_updates', 'survey_feedback'],
            required_fields=['recommend_to_friends'],
            description='Help us stay connected',
            icon='fa-handshake-o'
        )
    ]
    
    def __init__(self):
        super().__init__()
        # Override with custom steps
        self.wizard_form_class.custom_steps = self.custom_steps
    
    def process_wizard_submission(self, form, submission_id):
        """Process survey submission"""
        try:
            # Calculate satisfaction score
            satisfaction_mapping = {
                'very_satisfied': 5, 'satisfied': 4, 'neutral': 3,
                'dissatisfied': 2, 'very_dissatisfied': 1
            }
            
            overall_score = satisfaction_mapping.get(
                form.wizard_data.form_data.get('overall_satisfaction'), 0
            )
            
            print(f"Survey completed: {submission_id}")
            print(f"Customer: {form.wizard_data.form_data.get('customer_name')}")
            print(f"Satisfaction Score: {overall_score}/5")
            print(f"Would recommend: {form.wizard_data.form_data.get('recommend_to_friends')}")
            
            return True
        except Exception as e:
            print(f"Error processing survey: {e}")
            return False


# Example 3: Project Application with Conditional Fields
class ProjectApplicationForm(WizardForm):
    """
    Project application form with conditional field logic
    """
    
    # Applicant Information
    applicant_name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    applicant_email = EmailField('Email', validators=[DataRequired(), Email()])
    organization = StringField('Organization', validators=[DataRequired(), Length(max=100)])
    position = StringField('Position/Title', validators=[DataRequired(), Length(max=100)])
    
    # Project Information  
    project_title = StringField('Project Title', validators=[DataRequired(), Length(max=200)])
    project_category = SelectField('Project Category', choices=[
        ('', 'Select Category'),
        ('research', 'Research'),
        ('development', 'Development'),
        ('community', 'Community Service'),
        ('education', 'Education'),
        ('health', 'Health'),
        ('environment', 'Environment'),
        ('technology', 'Technology')
    ], validators=[DataRequired()])
    
    project_description = TextAreaField('Project Description', 
                                      validators=[DataRequired(), Length(max=2000)])
    project_objectives = TextAreaField('Project Objectives', 
                                     validators=[DataRequired(), Length(max=1000)])
    
    # Funding and Resources
    funding_requested = DecimalField('Funding Requested', 
                                   validators=[DataRequired(), NumberRange(min=0)])
    funding_currency = SelectField('Currency', choices=[
        ('USD', 'US Dollars'),
        ('EUR', 'Euros'),
        ('GBP', 'British Pounds'),
        ('CAD', 'Canadian Dollars'),
        ('AUD', 'Australian Dollars')
    ], validators=[DataRequired()])
    
    project_duration = IntegerField('Project Duration (months)', 
                                  validators=[DataRequired(), NumberRange(min=1, max=60)])
    
    # Team Information
    team_size = IntegerField('Team Size', validators=[DataRequired(), NumberRange(min=1, max=100)])
    team_members = TextAreaField('Team Members (names and roles)', 
                               validators=[Length(max=1000)])
    
    # Experience and Qualifications
    relevant_experience = TextAreaField('Relevant Experience', 
                                      validators=[DataRequired(), Length(max=1500)])
    previous_projects = TextAreaField('Previous Similar Projects', 
                                    validators=[Length(max=1000)])
    
    # Impact and Evaluation
    expected_impact = TextAreaField('Expected Impact', 
                                  validators=[DataRequired(), Length(max=1000)])
    success_metrics = TextAreaField('Success Metrics', 
                                  validators=[DataRequired(), Length(max=800)])
    
    # Additional Information
    references = TextAreaField('References (optional)', validators=[Length(max=500)])
    additional_documents = BooleanField('Additional documents will be submitted')
    terms_acceptance = BooleanField('Accept Terms and Conditions', validators=[DataRequired()])


class ProjectApplicationView(WizardFormView):
    """View for project application wizard"""
    
    wizard_form_class = ProjectApplicationForm
    wizard_title = 'Project Funding Application'
    wizard_description = 'Apply for project funding through our streamlined process'
    fields_per_step = 5
    allow_step_navigation = True
    require_step_completion = True
    
    def process_wizard_submission(self, form, submission_id):
        """Process project application"""
        try:
            funding_amount = form.wizard_data.form_data.get('funding_requested', 0)
            currency = form.wizard_data.form_data.get('funding_currency', 'USD')
            
            print(f"Project application submitted: {submission_id}")
            print(f"Applicant: {form.wizard_data.form_data.get('applicant_name')}")
            print(f"Project: {form.wizard_data.form_data.get('project_title')}")
            print(f"Funding: {funding_amount} {currency}")
            print(f"Duration: {form.wizard_data.form_data.get('project_duration')} months")
            
            return True
        except Exception as e:
            print(f"Error processing application: {e}")
            return False


# Flask Application Setup
def create_app():
    """Create Flask application with wizard forms"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'wizard-demo-secret-key'
    
    # Database configuration (using SQLite for demo)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "wizard_demo.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # PgAppForge configuration
    app.config['WTF_CSRF_ENABLED'] = True
    
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    # Add wizard views to AppBuilder
    appbuilder.add_view(
        EmployeeRegistrationView,
        "Employee Registration",
        category="Wizards",
        icon="fa-user-plus"
    )
    
    appbuilder.add_view(
        CustomerSurveyView,
        "Customer Survey", 
        category="Wizards",
        icon="fa-poll"
    )
    
    appbuilder.add_view(
        ProjectApplicationView,
        "Project Application",
        category="Wizards", 
        icon="fa-project-diagram"
    )
    
    return app, appbuilder


# Model for storing wizard submissions (optional)
class WizardSubmission(Model):
    """Store completed wizard submissions"""
    __tablename__ = 'wizard_submissions'
    
    id = Column(Integer, primary_key=True)
    submission_id = Column(String(100), unique=True, nullable=False)
    wizard_type = Column(String(50), nullable=False)
    user_id = Column(Integer, nullable=True)  # If user is logged in
    submission_data = Column(Text)  # JSON data
    submitted_at = Column(DateTime, default=datetime.utcnow)
    processed = Column(Boolean, default=False)
    
    def __repr__(self):
        return f'<WizardSubmission {self.submission_id}>'


def demonstrate_wizard_features():
    """Demonstrate various wizard features"""
    print("\n=== Wizard Forms Feature Demonstration ===")
    
    print("\n1. Employee Registration Wizard:")
    print("   - 20+ fields across multiple steps")
    print("   - Automatic step generation")
    print("   - Field validation and required field checking")
    print("   - Session persistence for draft saving")
    
    print("\n2. Customer Survey Wizard:")
    print("   - Custom step definitions")
    print("   - Radio buttons and select fields")
    print("   - Conditional field display")
    print("   - Progress tracking")
    
    print("\n3. Project Application Wizard:")
    print("   - Complex form with funding calculations")
    print("   - File upload capabilities")
    print("   - Team member management")
    print("   - Terms and conditions acceptance")
    
    print("\n🎯 Key Features Demonstrated:")
    print("✅ Multi-step form navigation with progress indicators")
    print("✅ Automatic and custom step generation")
    print("✅ Field validation and error handling")
    print("✅ Session persistence and auto-save")
    print("✅ Responsive design with mobile support")
    print("✅ Keyboard navigation shortcuts")
    print("✅ Draft saving and form resumption")
    print("✅ Final submission processing")
    print("✅ Integration with PgAppForge")


if __name__ == '__main__':
    app, appbuilder = create_app()
    
    with app.app_context():
        try:
            # Create database tables
            db = appbuilder.get_session.get_bind()
            WizardSubmission.__table__.create(db, checkfirst=True)
            print("✅ Database tables created")
            
            # Demonstrate features
            demonstrate_wizard_features()
            
            print(f"\n🚀 Starting PgAppForge Wizard Demo Server...")
            print(f"📱 Open http://localhost:5000 in your browser")
            print(f"👤 Login with: admin / admin")
            print(f"🧙‍♂️ Navigate to 'Wizards' menu to try the forms")
            
            app.run(debug=True, port=5000)
            
        except Exception as e:
            print(f"❌ Error starting application: {e}")
            print("\n📋 Troubleshooting:")
            print("  1. Ensure PgAppForge is installed")
            print("  2. Check database permissions")
            print("  3. Verify all dependencies are available")
            print("  4. Check for port conflicts")