"""
Test suite for PgAppForge Profile Management System

Tests cover models, views, API endpoints, validation, and security features.
"""
import datetime
import json
from unittest.mock import patch

import pytest
from flask import g, url_for
from pgappforge import SQLA
from pgappforge.const import API_RESULT_RES_KEY

from pgappforge.models.profiles import (
    ProfileField,
    ProfileFieldValue,
    ProfileType,
    UserProfile,
)
from pgappforge.security.profile_validators import (
    ProfileAuditLogger,
    ProfileSecurityManager,
    ProfileValidator,
)


class TestUserProfileModel:
    """Test UserProfile model functionality"""
    
    def test_profile_creation(self, app, appbuilder):
        """Test creating a user profile"""
        with app.app_context():
            # Create a user first
            user = appbuilder.sm.add_user(
                'testuser', 'Test', 'User', 'test@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            # Create profile
            profile = UserProfile(
                user_id=user.id,
                profile_type=ProfileType.BASIC,
                phone='+1-555-0123',
                city='San Francisco',
                country='USA'
            )
            
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Verify profile
            assert profile.id is not None
            assert profile.user_id == user.id
            assert profile.profile_type == ProfileType.BASIC
            assert profile.phone == '+1-555-0123'
    
    def test_full_name_property(self, app, appbuilder):
        """Test full name computed property"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'jane.doe', 'Jane', 'Doe', 'jane@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            assert profile.full_name == 'Jane Doe'
    
    def test_initials_property(self, app, appbuilder):
        """Test initials computed property"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'john.smith', 'John', 'Smith', 'john@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            assert profile.initials == 'JS'
    
    def test_full_address_property(self, app, appbuilder):
        """Test full address formatting"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'testuser2', 'Test', 'User2', 'test2@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(
                user_id=user.id,
                address_line1='123 Main St',
                address_line2='Apt 4B',
                city='New York',
                state='NY',
                postal_code='10001',
                country='USA'
            )
            
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            expected = '123 Main St, Apt 4B, New York, NY, 10001, USA'
            assert profile.full_address == expected
    
    def test_profile_completion_calculation(self, app, appbuilder):
        """Test profile completion percentage calculation"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'testuser3', 'Test', 'User3', 'test3@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            # Empty profile
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            completion = profile.calculate_profile_completion()
            # Should have first_name, last_name, email from user
            expected = (3 / 7) * 100  # 3 out of 7 required fields
            assert completion == expected
            
            # Add more fields
            profile.phone = '+1-555-0123'
            profile.date_of_birth = datetime.date(1990, 1, 1)
            profile.city = 'San Francisco'
            profile.country = 'USA'
            
            completion = profile.calculate_profile_completion()
            expected = (7 / 7) * 100  # All required fields filled
            assert completion == expected
    
    def test_skills_management(self, app, appbuilder):
        """Test skills add/remove functionality"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'skilluser', 'Skill', 'User', 'skill@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Add skills
            profile.add_skill('Python')
            profile.add_skill('JavaScript')
            profile.add_skill('Python')  # Duplicate should not be added
            
            assert len(profile.skills) == 2
            assert 'Python' in profile.skills
            assert 'JavaScript' in profile.skills
            
            # Remove skill
            profile.remove_skill('Python')
            assert len(profile.skills) == 1
            assert 'Python' not in profile.skills
            assert 'JavaScript' in profile.skills
    
    def test_certifications_management(self, app, appbuilder):
        """Test certifications add functionality"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'certuser', 'Cert', 'User', 'cert@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Add certification
            profile.add_certification(
                'AWS Certified Developer',
                'Amazon Web Services',
                datetime.date(2022, 1, 1),
                datetime.date(2025, 1, 1)
            )
            
            assert len(profile.certifications) == 1
            cert = profile.certifications[0]
            assert cert['name'] == 'AWS Certified Developer'
            assert cert['issuer'] == 'Amazon Web Services'
            assert cert['date_obtained'] == '2022-01-01'
            assert cert['expiry_date'] == '2025-01-01'
    
    def test_custom_fields(self, app, appbuilder):
        """Test custom field management"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'customuser', 'Custom', 'User', 'custom@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Set custom fields
            profile.set_custom_field('badge_color', 'blue')
            profile.set_custom_field('parking_spot', 'A15')
            
            assert profile.get_custom_field('badge_color') == 'blue'
            assert profile.get_custom_field('parking_spot') == 'A15'
            assert profile.get_custom_field('nonexistent') is None
            assert profile.get_custom_field('nonexistent', 'default') == 'default'
    
    def test_profile_visibility(self, app, appbuilder):
        """Test profile visibility controls"""
        with app.app_context():
            user1 = appbuilder.sm.add_user(
                'user1', 'User', 'One', 'user1@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            user2 = appbuilder.sm.add_user(
                'user2', 'User', 'Two', 'user2@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(
                user_id=user1.id,
                profile_visibility='public'
            )
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Public profile should be viewable by anyone
            assert profile.can_view_profile(user2) is True
            assert profile.can_view_profile(None) is True
            
            # Private profile
            profile.profile_visibility = 'private'
            assert profile.can_view_profile(user2) is False
            assert profile.can_view_profile(user1) is True  # Owner can view


class TestProfileSecurityManager:
    """Test ProfileSecurityManager functionality"""
    
    def test_can_view_field(self, app, appbuilder):
        """Test field-level view permissions"""
        with app.app_context():
            owner = appbuilder.sm.add_user(
                'owner', 'Owner', 'User', 'owner@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            viewer = appbuilder.sm.add_user(
                'viewer', 'Viewer', 'User', 'viewer@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(
                user_id=owner.id,
                profile_visibility='public'
            )
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Owner can view all fields
            assert ProfileSecurityManager.can_view_field('phone', profile, owner) is True
            assert ProfileSecurityManager.can_view_field('biography', profile, owner) is True
            
            # Non-owner cannot view sensitive fields
            assert ProfileSecurityManager.can_view_field('phone', profile, viewer) is False
            assert ProfileSecurityManager.can_view_field('biography', profile, viewer) is True
    
    def test_can_edit_field(self, app, appbuilder):
        """Test field-level edit permissions"""
        with app.app_context():
            owner = appbuilder.sm.add_user(
                'owner2', 'Owner2', 'User', 'owner2@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            other_user = appbuilder.sm.add_user(
                'other', 'Other', 'User', 'other@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=owner.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Owner can edit most fields
            assert ProfileSecurityManager.can_edit_field('phone', profile, owner) is True
            
            # Owner cannot edit admin-only fields
            assert ProfileSecurityManager.can_edit_field('profile_verified', profile, owner) is False
            
            # Other users cannot edit
            assert ProfileSecurityManager.can_edit_field('phone', profile, other_user) is False
    
    def test_sanitize_profile_data(self):
        """Test data sanitization"""
        data = {
            'phone': '  +1-555-0123  ',
            'website': 'example.com',
            'email': '  TEST@EXAMPLE.COM  ',
            'biography': 'This is a <script>alert("xss")</script> test',
            'empty_field': '   ',
            'null_field': None
        }
        
        sanitized = ProfileSecurityManager.sanitize_profile_data(data)
        
        assert sanitized['phone'] == '+1-555-0123'
        assert sanitized['website'] == 'https://example.com'
        assert sanitized['email'] == 'test@example.com'
        assert 'script' not in sanitized['biography']
        assert sanitized['empty_field'] is None
        assert sanitized['null_field'] is None


class TestProfileValidator:
    """Test ProfileValidator functionality"""
    
    def test_validate_date_of_birth(self, app, appbuilder):
        """Test date of birth validation"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'dobuser', 'DOB', 'User', 'dob@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Future date should fail
            future_date = datetime.date.today() + datetime.timedelta(days=1)
            errors = ProfileValidator.validate_profile_data(profile, {
                'date_of_birth': future_date
            })
            assert any('future' in error.lower() for error in errors)
            
            # Too young should fail
            too_young = datetime.date.today() - datetime.timedelta(days=365 * 10)  # 10 years old
            errors = ProfileValidator.validate_profile_data(profile, {
                'date_of_birth': too_young
            })
            assert any('13 years' in error for error in errors)
            
            # Valid date should pass
            valid_date = datetime.date(1990, 1, 1)
            errors = ProfileValidator.validate_profile_data(profile, {
                'date_of_birth': valid_date
            })
            dob_errors = [e for e in errors if 'birth' in e.lower()]
            assert len(dob_errors) == 0
    
    def test_validate_skills(self, app, appbuilder):
        """Test skills validation"""
        with app.app_context():
            user = appbuilder.sm.add_user(
                'skillsuser', 'Skills', 'User', 'skills@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            appbuilder.get_session.commit()
            
            # Valid skills
            errors = ProfileValidator.validate_profile_data(profile, {
                'skills': ['Python', 'JavaScript', 'React']
            })
            skill_errors = [e for e in errors if 'skill' in e.lower()]
            assert len(skill_errors) == 0
            
            # Too many skills
            too_many_skills = [f'Skill{i}' for i in range(51)]
            errors = ProfileValidator.validate_profile_data(profile, {
                'skills': too_many_skills
            })
            assert any('50 skills' in error for error in errors)
            
            # Invalid skill format
            errors = ProfileValidator.validate_profile_data(profile, {
                'skills': ['Valid Skill', '', 'Another Valid']
            })
            assert any('non-empty string' in error for error in errors)


class TestProfileAPI:
    """Test Profile API endpoints"""
    
    def test_get_my_profile_authenticated(self, app, appbuilder, client):
        """Test getting current user's profile"""
        with app.app_context():
            # Create user and login
            user = appbuilder.sm.add_user(
                'apiuser', 'API', 'User', 'api@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            # Login
            client.post('/login/', data={
                'username': 'apiuser',
                'password': 'password'
            }, follow_redirects=True)
            
            # Get profile (should create one if it doesn't exist)
            response = client.get('/api/v1/profiles/my-profile')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert API_RESULT_RES_KEY in data
            profile_data = data[API_RESULT_RES_KEY]
            assert profile_data['user_id'] == user.id
    
    def test_update_my_profile_authenticated(self, app, appbuilder, client):
        """Test updating current user's profile"""
        with app.app_context():
            # Create user and login
            user = appbuilder.sm.add_user(
                'updateuser', 'Update', 'User', 'update@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            client.post('/login/', data={
                'username': 'updateuser',
                'password': 'password'
            }, follow_redirects=True)
            
            # Update profile
            profile_data = {
                'phone': '+1-555-0123',
                'city': 'San Francisco',
                'biography': 'Test biography'
            }
            
            response = client.put('/api/v1/profiles/my-profile',
                                data=json.dumps(profile_data),
                                content_type='application/json')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            result = data[API_RESULT_RES_KEY]
            assert result['phone'] == '+1-555-0123'
            assert result['city'] == 'San Francisco'
    
    def test_get_my_profile_unauthenticated(self, app, client):
        """Test getting profile without authentication"""
        with app.app_context():
            response = client.get('/api/v1/profiles/my-profile')
            assert response.status_code == 401
    
    def test_profile_stats_authenticated(self, app, appbuilder, client):
        """Test getting profile statistics"""
        with app.app_context():
            # Create admin user
            admin_user = appbuilder.sm.add_user(
                'admin', 'Admin', 'User', 'admin@example.com',
                appbuilder.sm.find_role('Admin'), 'password'
            )
            
            client.post('/login/', data={
                'username': 'admin',
                'password': 'password'
            }, follow_redirects=True)
            
            response = client.get('/api/v1/profiles/stats')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            result = data[API_RESULT_RES_KEY]
            assert 'total_profiles' in result
            assert 'completed_profiles' in result
            assert 'verification_rate' in result


class TestDynamicProfileFields:
    """Test dynamic profile field functionality"""
    
    def test_create_profile_field(self, app, appbuilder):
        """Test creating a dynamic profile field"""
        with app.app_context():
            field = ProfileField(
                name='security_clearance',
                label='Security Clearance',
                field_type='string',
                choices=['None', 'Confidential', 'Secret'],
                required=False,
                admin_only=True
            )
            
            appbuilder.get_session.add(field)
            appbuilder.get_session.commit()
            
            assert field.id is not None
            assert field.name == 'security_clearance'
            assert field.admin_only is True
    
    def test_profile_field_value(self, app, appbuilder):
        """Test storing values for dynamic fields"""
        with app.app_context():
            # Create user and profile
            user = appbuilder.sm.add_user(
                'fielduser', 'Field', 'User', 'field@example.com',
                appbuilder.sm.find_role('Public'), 'password'
            )
            
            profile = UserProfile(user_id=user.id)
            appbuilder.get_session.add(profile)
            
            # Create field
            field = ProfileField(
                name='department_code',
                label='Department Code',
                field_type='string'
            )
            appbuilder.get_session.add(field)
            appbuilder.get_session.commit()
            
            # Create field value
            field_value = ProfileFieldValue(
                profile_id=profile.id,
                field_id=field.id,
                value='ENG001'
            )
            appbuilder.get_session.add(field_value)
            appbuilder.get_session.commit()
            
            assert field_value.get_typed_value() == 'ENG001'
    
    def test_typed_field_values(self, app, appbuilder):
        """Test type conversion for field values"""
        with app.app_context():
            # Integer field
            int_field = ProfileField(
                name='age',
                label='Age',
                field_type='integer'
            )
            
            # Boolean field
            bool_field = ProfileField(
                name='is_active',
                label='Is Active',
                field_type='boolean'
            )
            
            appbuilder.get_session.add_all([int_field, bool_field])
            appbuilder.get_session.commit()
            
            # Test integer conversion
            int_value = ProfileFieldValue(field=int_field, value=25)
            assert int_value.get_typed_value() == 25
            
            # Test boolean conversion  
            bool_value = ProfileFieldValue(field=bool_field, value=True)
            assert bool_value.get_typed_value() is True


@pytest.fixture
def app():
    """Create Flask app for testing"""
    from flask import Flask
    from pgappforge import AppBuilder, SQLA
    
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = False
    
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    with app.app_context():
        db.create_all()
        # Create default roles if they don't exist
        appbuilder.sm.sync_role_definitions()
    
    yield app


@pytest.fixture
def appbuilder(app):
    """Get AppBuilder instance"""
    return app.appbuilder


@pytest.fixture
def client(app):
    """Get test client"""
    return app.test_client()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])