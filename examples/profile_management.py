#!/usr/bin/env python3
"""
PgAppForge Profile Management Example

This example demonstrates how to use the extensible user profile system
with PgAppForge, including basic and extended profiles, custom fields,
and security features.
"""

import datetime
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Model
from pgappforge.security.sqla.models import User

# Import the profile system
from pgappforge.models.profiles import (
    ProfileMixin,
    ExtendedProfileMixin,
    UserProfile,
    ProfileField,
    ProfileFieldValue,
    ProfileType,
)
from pgappforge.security.profile_views import (
    MyProfileView,
    PublicProfileView,
    UserProfileView,
    ProfileFieldView,
)
from pgappforge.api.profiles import UserProfileApi


# Example 1: Simple User Model with Profile Mixin
class SimpleUserModel(User, ProfileMixin):
    """
    Example of adding basic profile functionality directly to User model.
    This is the simplest approach but requires modifying the User model.
    """
    pass


# Example 2: Extended User Model with Full Profile Features
class ExtendedUserModel(User, ExtendedProfileMixin):
    """
    Example of a User model with comprehensive profile features.
    Includes professional information, skills, and certifications.
    """
    pass


def create_app():
    """Create Flask application with profile management"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'your-secret-key-here'
    
    # Database configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///profile_example.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # PgAppForge configuration
    app.config['FAB_ROLES'] = {
        'Admin': [
            ['.*', 'can_add'],
            ['.*', 'can_edit'],
            ['.*', 'can_delete'],
            ['.*', 'can_list'],
            ['.*', 'can_show'],
        ]
    }
    
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    # Register profile views
    appbuilder.add_view(
        MyProfileView,
        "My Profile",
        icon="fa-user",
        category="Profile"
    )
    
    appbuilder.add_view(
        PublicProfileView,
        "Public Profiles",
        icon="fa-users",
        category="Profile"
    )
    
    # Admin views (requires admin permissions)
    appbuilder.add_view(
        UserProfileView,
        "Manage Profiles",
        icon="fa-user-cog",
        category="Admin",
        category_icon="fa-cog"
    )
    
    appbuilder.add_view(
        ProfileFieldView,
        "Profile Fields",
        icon="fa-list",
        category="Admin"
    )
    
    # Add API endpoints
    appbuilder.add_api(UserProfileApi)
    
    return app, appbuilder


def create_sample_data(appbuilder):
    """Create sample profile data for demonstration"""
    try:
        # Create some dynamic profile fields
        field1 = ProfileField(
            name='department_budget',
            label='Department Budget',
            description='Annual budget for the department',
            field_type='integer',
            field_group='professional',
            admin_only=True
        )
        
        field2 = ProfileField(
            name='security_clearance',
            label='Security Clearance',
            description='Security clearance level',
            field_type='string',
            choices=['None', 'Confidential', 'Secret', 'Top Secret'],
            field_group='professional',
            admin_only=True
        )
        
        field3 = ProfileField(
            name='favorite_color',
            label='Favorite Color',
            description='Your favorite color',
            field_type='string',
            field_group='personal',
            required=False
        )
        
        appbuilder.get_session.add_all([field1, field2, field3])
        
        # Create sample users with profiles
        user1 = appbuilder.sm.add_user(
            'john.doe',
            'John',
            'Doe',
            'john.doe@example.com',
            appbuilder.sm.find_role('Public'),
            'password'
        )
        
        user2 = appbuilder.sm.add_user(
            'jane.smith',
            'Jane',
            'Smith',
            'jane.smith@example.com',
            appbuilder.sm.find_role('Admin'),
            'password'
        )
        
        # Create profiles for the users
        if user1:
            profile1 = UserProfile(
                user_id=user1.id,
                profile_type=ProfileType.EMPLOYEE,
                phone='+1-555-0123',
                mobile='+1-555-0124',
                date_of_birth=datetime.date(1985, 6, 15),
                biography='Software engineer with 8 years of experience in web development.',
                city='San Francisco',
                state='CA',
                country='USA',
                timezone='America/Los_Angeles',
                language='en',
                website='https://johndoe.dev',
                linkedin='https://linkedin.com/in/johndoe',
                github='https://github.com/johndoe',
                job_title='Senior Software Engineer',
                department='Engineering',
                organization='TechCorp Inc.',
                employee_id='ENG001',
                start_date=datetime.date(2020, 3, 1),
                skills=['Python', 'JavaScript', 'React', 'Flask', 'SQL'],
                profile_visibility='public'
            )
            
            profile1.add_certification(
                'AWS Certified Developer',
                'Amazon Web Services',
                datetime.date(2022, 5, 15),
                datetime.date(2025, 5, 15)
            )
            
            appbuilder.get_session.add(profile1)
        
        if user2:
            profile2 = UserProfile(
                user_id=user2.id,
                profile_type=ProfileType.ADMIN,
                phone='+1-555-0125',
                date_of_birth=datetime.date(1982, 10, 22),
                biography='Engineering manager focused on building high-performing teams.',
                city='New York',
                state='NY',
                country='USA',
                timezone='America/New_York',
                language='en',
                linkedin='https://linkedin.com/in/janesmith',
                job_title='Engineering Manager',
                department='Engineering',
                organization='TechCorp Inc.',
                employee_id='MGR001',
                start_date=datetime.date(2018, 1, 15),
                skills=['Leadership', 'Python', 'Architecture', 'Agile'],
                email_notifications=True,
                sms_notifications=False,
                profile_visibility='limited'
            )
            
            profile2.add_certification(
                'PMP Certification',
                'Project Management Institute',
                datetime.date(2021, 8, 10)
            )
            
            appbuilder.get_session.add(profile2)
        
        appbuilder.get_session.commit()
        print("Sample data created successfully!")
        
    except Exception as e:
        print(f"Error creating sample data: {e}")
        appbuilder.get_session.rollback()


def demonstrate_profile_usage(appbuilder):
    """Demonstrate common profile operations"""
    print("\n=== Profile System Demonstration ===")
    
    # Get a user profile
    profile = appbuilder.get_session.query(UserProfile).first()
    if not profile:
        print("No profiles found. Please create sample data first.")
        return
    
    print(f"\nProfile for: {profile.user.username}")
    print(f"Full Name: {profile.full_name}")
    print(f"Initials: {profile.initials}")
    print(f"Profile Type: {profile.profile_type.value}")
    print(f"Completion Rate: {profile.calculate_profile_completion():.1f}%")
    print(f"Profile Completed: {profile.profile_completed}")
    print(f"Is Public: {profile.is_profile_public()}")
    
    # Demonstrate skills management
    if profile.skills:
        print(f"Skills: {', '.join(profile.skills)}")
    
    # Demonstrate certifications
    if profile.certifications:
        print("Certifications:")
        for cert in profile.certifications:
            print(f"  - {cert['name']} by {cert['issuer']}")
    
    # Demonstrate preference management
    profile.set_preference('notification_sound', True)
    profile.set_preference('dark_mode', False)
    print(f"Notification Sound: {profile.get_preference('notification_sound')}")
    print(f"Dark Mode: {profile.get_preference('dark_mode')}")
    
    # Demonstrate address formatting
    if profile.full_address:
        print(f"Address: {profile.full_address}")
    
    # Demonstrate custom fields
    profile.set_custom_field('badge_color', 'blue')
    profile.set_custom_field('parking_spot', 'A15')
    print(f"Badge Color: {profile.get_custom_field('badge_color')}")
    print(f"Parking Spot: {profile.get_custom_field('parking_spot')}")
    
    appbuilder.get_session.commit()
    print("\nProfile demonstration completed!")


if __name__ == '__main__':
    """Run the example application"""
    app, appbuilder = create_app()
    
    with app.app_context():
        # Create database tables
        appbuilder.get_session.get_bind().create_all()
        
        # Create sample data if needed
        if appbuilder.get_session.query(UserProfile).count() == 0:
            create_sample_data(appbuilder)
        
        # Demonstrate profile features
        demonstrate_profile_usage(appbuilder)
    
    print("\n=== Starting Flask Application ===")
    print("Visit http://localhost:5000 to see the profile management system")
    print("Login with:")
    print("  Username: john.doe, Password: password")
    print("  Username: jane.smith, Password: password (Admin)")
    
    app.run(host='0.0.0.0', port=5000, debug=True)