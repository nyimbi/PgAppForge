"""
User Profile API for PgAppForge

This module provides RESTful API endpoints for user profile management,
including profile CRUD operations, profile validation, and profile statistics.
"""
import datetime
import logging
from typing import Any, Dict, List, Optional

from flask import g, request
from pgappforge.api import BaseApi, expose, protect, safe
from pgappforge.const import API_RESULT_RES_KEY
from pgappforge.exceptions import ValidationError
from pgappforge.models.sqla import filters
from flask_babel import gettext
from marshmallow import fields, Schema, validate, validates_schema
from sqlalchemy import and_, func, or_

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

log = logging.getLogger(__name__)


class ProfileSchema(Schema):
    """Schema for user profile serialization"""
    
    id = fields.Integer(dump_only=True)
    user_id = fields.Integer(required=True)
    profile_type = fields.Enum(ProfileType)
    
    # Personal Information
    phone = fields.String(validate=validate.Length(max=50), allow_none=True)
    mobile = fields.String(validate=validate.Length(max=50), allow_none=True)
    date_of_birth = fields.Date(allow_none=True)
    biography = fields.String(allow_none=True)
    
    # Address Information
    address_line1 = fields.String(validate=validate.Length(max=255), allow_none=True)
    address_line2 = fields.String(validate=validate.Length(max=255), allow_none=True)
    city = fields.String(validate=validate.Length(max=100), allow_none=True)
    state = fields.String(validate=validate.Length(max=100), allow_none=True)
    country = fields.String(validate=validate.Length(max=100), allow_none=True)
    postal_code = fields.String(validate=validate.Length(max=20), allow_none=True)
    
    # Settings
    timezone = fields.String(validate=validate.Length(max=50), allow_none=True)
    language = fields.String(validate=validate.Length(max=10), allow_none=True)
    theme = fields.String(validate=validate.Length(max=50), allow_none=True)
    
    # Social Media
    website = fields.Url(allow_none=True)
    linkedin = fields.Url(allow_none=True)
    twitter = fields.Url(allow_none=True)
    github = fields.Url(allow_none=True)
    
    # Professional (for extended profiles)
    job_title = fields.String(validate=validate.Length(max=255), allow_none=True)
    department = fields.String(validate=validate.Length(max=100), allow_none=True)
    organization = fields.String(validate=validate.Length(max=255), allow_none=True)
    employee_id = fields.String(validate=validate.Length(max=50), allow_none=True)
    start_date = fields.Date(allow_none=True)
    
    # Notifications
    email_notifications = fields.Boolean(missing=True)
    sms_notifications = fields.Boolean(missing=False)
    push_notifications = fields.Boolean(missing=True)
    
    # Preferences and custom fields
    preferences = fields.Dict(allow_none=True)
    custom_fields = fields.Dict(allow_none=True)
    
    # Status fields
    profile_completed = fields.Boolean(dump_only=True)
    profile_verified = fields.Boolean(dump_only=True)
    profile_visibility = fields.String(
        validate=validate.OneOf(['public', 'private', 'limited']),
        missing='public'
    )
    
    # Computed fields
    full_name = fields.String(dump_only=True)
    initials = fields.String(dump_only=True)
    completion_rate = fields.Float(dump_only=True)
    
    # Timestamps
    last_profile_update = fields.DateTime(dump_only=True)
    created_on = fields.DateTime(dump_only=True)
    changed_on = fields.DateTime(dump_only=True)
    
    @validates_schema
    def validate_profile_data(self, data, **kwargs):
        """Custom validation for profile data"""
        # Validate date of birth is not in the future
        if 'date_of_birth' in data and data['date_of_birth']:
            if data['date_of_birth'] > datetime.date.today():
                raise ValidationError('Date of birth cannot be in the future')
        
        # Validate start date is reasonable
        if 'start_date' in data and data['start_date']:
            if data['start_date'] > datetime.date.today():
                raise ValidationError('Start date cannot be in the future')


class ProfileSummarySchema(Schema):
    """Lightweight schema for profile summaries"""
    
    id = fields.Integer()
    user_id = fields.Integer()
    full_name = fields.String()
    initials = fields.String()
    profile_type = fields.Enum(ProfileType)
    profile_completed = fields.Boolean()
    profile_verified = fields.Boolean()
    avatar_url = fields.String(allow_none=True)
    last_profile_update = fields.DateTime()


class ProfileFieldSchema(Schema):
    """Schema for dynamic profile fields"""
    
    id = fields.Integer(dump_only=True)
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    label = fields.String(required=True, validate=validate.Length(min=1, max=255))
    description = fields.String(allow_none=True)
    field_type = fields.String(
        required=True,
        validate=validate.OneOf(['string', 'integer', 'date', 'datetime', 'boolean', 'json'])
    )
    
    required = fields.Boolean(missing=False)
    unique = fields.Boolean(missing=False)
    max_length = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    default_value = fields.String(allow_none=True)
    choices = fields.List(fields.String(), allow_none=True)
    
    field_group = fields.String(missing='custom')
    display_order = fields.Integer(missing=0)
    
    visible = fields.Boolean(missing=True)
    editable = fields.Boolean(missing=True)
    admin_only = fields.Boolean(missing=False)
    
    validation_rules = fields.Dict(allow_none=True)


class UserProfileApi(BaseApi):
    """API for user profile management"""
    
    resource_name = 'profiles'
    datamodel = None  # Will be set in manager
    
    allow_browser_login = True
    base_permissions = [
        'can_get',
        'can_post',
        'can_put',
        'can_delete',
        'can_info'
    ]
    
    class_permission_name = 'UserProfile'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'post': 'can_add',
        'put': 'can_edit',
        'delete': 'can_delete',
        'get_my_profile': 'can_show',
        'put_my_profile': 'can_edit',
        'get_public_profile': 'can_show',
    }
    
    list_columns = [
        'id', 'user_id', 'profile_type', 'full_name',
        'profile_completed', 'profile_verified', 'last_profile_update'
    ]
    
    show_columns = [
        'id', 'user_id', 'profile_type', 'phone', 'mobile',
        'date_of_birth', 'biography', 'address_line1', 'address_line2',
        'city', 'state', 'country', 'postal_code', 'timezone',
        'language', 'website', 'linkedin', 'twitter', 'github',
        'job_title', 'department', 'organization', 'employee_id',
        'start_date', 'email_notifications', 'sms_notifications',
        'push_notifications', 'preferences', 'custom_fields',
        'profile_completed', 'profile_verified', 'profile_visibility',
        'full_name', 'initials', 'completion_rate',
        'last_profile_update', 'created_on', 'changed_on'
    ]
    
    add_columns = [
        'user_id', 'profile_type', 'phone', 'mobile',
        'date_of_birth', 'biography', 'address_line1', 'address_line2',
        'city', 'state', 'country', 'postal_code', 'timezone',
        'language', 'website', 'linkedin', 'twitter', 'github',
        'preferences', 'custom_fields', 'profile_visibility'
    ]
    
    edit_columns = [
        'profile_type', 'phone', 'mobile', 'date_of_birth',
        'biography', 'address_line1', 'address_line2', 'city',
        'state', 'country', 'postal_code', 'timezone', 'language',
        'website', 'linkedin', 'twitter', 'github', 'job_title',
        'department', 'organization', 'employee_id', 'start_date',
        'email_notifications', 'sms_notifications', 'push_notifications',
        'preferences', 'custom_fields', 'profile_visibility'
    ]
    
    search_columns = [
        'user.username', 'user.first_name', 'user.last_name',
        'user.email', 'city', 'country', 'job_title', 'department'
    ]
    
    apispec_parameter_schemas = {
        'get_list_schema': ProfileSummarySchema,
        'get_item_schema': ProfileSchema,
        'post_item_schema': ProfileSchema,
        'put_item_schema': ProfileSchema,
    }
    
    def pre_add(self, item: UserProfile) -> None:
        """Pre-process before adding profile"""
        item.last_profile_update = datetime.datetime.now(datetime.timezone.utc)
        item.update_profile_completion()
    
    def pre_update(self, item: UserProfile) -> None:
        """Pre-process before updating profile"""
        item.last_profile_update = datetime.datetime.now(datetime.timezone.utc)
        item.update_profile_completion()
    
    def post_add(self, item: UserProfile) -> None:
        """Post-process after adding profile"""
        log.info(f"Created profile for user {item.user_id}")
    
    def post_update(self, item: UserProfile) -> None:
        """Post-process after updating profile"""
        log.info(f"Updated profile for user {item.user_id}")
    
    @expose('/my-profile', methods=['GET'])
    @protect()
    @safe
    def get_my_profile(self):
        """Get current user's profile"""
        if not g.user:
            return self.response_401()
        
        # Get or create profile for current user
        profile = self.datamodel.session.execute(
            self.datamodel.session.query(UserProfile).filter_by(user_id=g.user.id)
        ).scalar_one_or_none()
        
        if not profile:
            # Create default profile
            profile = UserProfile(user_id=g.user.id)
            self.datamodel.session.add(profile)
            self.datamodel.session.commit()
        
        # Add computed fields
        profile.completion_rate = profile.calculate_profile_completion()
        
        schema = ProfileSchema()
        return self.response(200, **{API_RESULT_RES_KEY: schema.dump(profile)})
    
    @expose('/my-profile', methods=['PUT'])
    @protect()
    @safe
    def put_my_profile(self):
        """Update current user's profile"""
        if not g.user:
            return self.response_401()
        
        # Get or create profile for current user
        profile = self.datamodel.session.execute(
            self.datamodel.session.query(UserProfile).filter_by(user_id=g.user.id)
        ).scalar_one_or_none()
        
        if not profile:
            profile = UserProfile(user_id=g.user.id)
            self.datamodel.session.add(profile)
        
        # Validate and update profile
        schema = ProfileSchema()
        try:
            json_data = request.get_json()
            if not json_data:
                return self.response_400(message="No data provided")
            
            # Don't allow changing user_id
            json_data.pop('user_id', None)
            json_data.pop('id', None)
            
            # Security validation - check permissions for each field
            for field_name in json_data:
                if not ProfileSecurityManager.can_edit_field(field_name, profile, g.user):
                    return self.response_403(message=f"Permission denied for field: {field_name}")
            
            # Sanitize data
            sanitized_data = ProfileSecurityManager.sanitize_profile_data(json_data)
            
            # Validate data
            validation_errors = ProfileValidator.validate_profile_data(profile, sanitized_data)
            if validation_errors:
                return self.response_422(message="; ".join(validation_errors))
            
            # Load and validate schema
            result = schema.load(sanitized_data, partial=True)
            
            # Track changed fields for audit
            changed_fields = {}
            for key, new_value in result.items():
                if hasattr(profile, key):
                    old_value = getattr(profile, key, None)
                    if old_value != new_value:
                        changed_fields[key] = {'old': old_value, 'new': new_value}
                        setattr(profile, key, new_value)
            
            if changed_fields:
                # Log the change
                ProfileAuditLogger.log_profile_change(profile, changed_fields, g.user)
            
            self.pre_update(profile)
            self.datamodel.session.commit()
            self.post_update(profile)
            
            # Add computed fields for response
            profile.completion_rate = profile.calculate_profile_completion()
            
            return self.response(200, **{API_RESULT_RES_KEY: schema.dump(profile)})
            
        except ValidationError as e:
            return self.response_422(message=str(e))
        except Exception as e:
            log.exception("Error updating profile")
            return self.response_500(message=str(e))
    
    @expose('/public/<int:user_id>', methods=['GET'])
    @safe
    def get_public_profile(self, user_id: int):
        """Get public profile for a specific user"""
        profile = self.datamodel.session.execute(
            self.datamodel.session.query(UserProfile).filter_by(user_id=user_id)
        ).scalar_one_or_none()
        
        if not profile:
            return self.response_404()
        
        # Check if profile is viewable
        if not profile.can_view_profile(g.user):
            return self.response_403()
        
        # Log access to public profile
        viewed_fields = ['full_name', 'profile_type', 'profile_completed', 'avatar_url']
        ProfileAuditLogger.log_profile_access(profile, g.user, viewed_fields)
        
        # Return limited public data
        schema = ProfileSummarySchema()
        return self.response(200, **{API_RESULT_RES_KEY: schema.dump(profile)})
    
    @expose('/stats', methods=['GET'])
    @protect()
    @safe
    def get_stats(self):
        """Get profile statistics"""
        # Basic counts
        total = self.datamodel.session.query(UserProfile).count()
        completed = self.datamodel.session.query(UserProfile).filter(
            UserProfile.profile_completed == True
        ).count()
        verified = self.datamodel.session.query(UserProfile).filter(
            UserProfile.profile_verified == True
        ).count()
        
        # Profile types distribution
        type_counts = dict(
            self.datamodel.session.query(
                UserProfile.profile_type, func.count(UserProfile.id)
            ).group_by(UserProfile.profile_type).all()
        )
        
        # Recent activity
        recent_updates = self.datamodel.session.query(UserProfile).filter(
            UserProfile.last_profile_update >= datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
        ).count()
        
        stats = {
            'total_profiles': total,
            'completed_profiles': completed,
            'verified_profiles': verified,
            'completion_rate': (completed / total * 100) if total > 0 else 0,
            'verification_rate': (verified / total * 100) if total > 0 else 0,
            'profile_types': {ptype.value: count for ptype, count in type_counts.items()},
            'recent_updates': recent_updates
        }
        
        return self.response(200, **{API_RESULT_RES_KEY: stats})
    
    @expose('/search', methods=['POST'])
    @protect()
    @safe
    def search_profiles(self):
        """Advanced profile search"""
        json_data = request.get_json()
        if not json_data:
            return self.response_400(message="No search criteria provided")
        
        query = self.datamodel.session.query(UserProfile)
        
        # Apply filters based on search criteria
        if 'profile_type' in json_data:
            query = query.filter(UserProfile.profile_type == ProfileType(json_data['profile_type']))
        
        if 'city' in json_data:
            query = query.filter(UserProfile.city.ilike(f"%{json_data['city']}%"))
        
        if 'country' in json_data:
            query = query.filter(UserProfile.country.ilike(f"%{json_data['country']}%"))
        
        if 'skills' in json_data:
            # Search in skills JSON array
            for skill in json_data['skills']:
                query = query.filter(UserProfile.skills.contains([skill]))
        
        if 'completed_only' in json_data and json_data['completed_only']:
            query = query.filter(UserProfile.profile_completed == True)
        
        if 'verified_only' in json_data and json_data['verified_only']:
            query = query.filter(UserProfile.profile_verified == True)
        
        # Apply pagination
        page = json_data.get('page', 1)
        page_size = min(json_data.get('page_size', 20), 100)  # Max 100 results
        
        profiles = query.offset((page - 1) * page_size).limit(page_size).all()
        total = query.count()
        
        schema = ProfileSummarySchema(many=True)
        return self.response(200, **{
            API_RESULT_RES_KEY: schema.dump(profiles),
            'count': len(profiles),
            'total': total,
            'page': page,
            'page_size': page_size
        })


class ProfileFieldApi(BaseApi):
    """API for managing dynamic profile fields"""
    
    resource_name = 'profile-fields'
    datamodel = None  # Will be set in manager
    
    allow_browser_login = True
    base_permissions = [
        'can_get',
        'can_post',
        'can_put',
        'can_delete'
    ]
    
    class_permission_name = 'ProfileField'
    
    apispec_parameter_schemas = {
        'get_list_schema': ProfileFieldSchema,
        'get_item_schema': ProfileFieldSchema,
        'post_item_schema': ProfileFieldSchema,
        'put_item_schema': ProfileFieldSchema,
    }
    
    list_columns = [
        'id', 'name', 'label', 'field_type', 'required',
        'field_group', 'display_order', 'visible'
    ]
    
    show_columns = [
        'id', 'name', 'label', 'description', 'field_type',
        'required', 'unique', 'max_length', 'default_value',
        'choices', 'field_group', 'display_order',
        'visible', 'editable', 'admin_only', 'validation_rules'
    ]
    
    add_columns = [
        'name', 'label', 'description', 'field_type',
        'required', 'unique', 'max_length', 'default_value',
        'choices', 'field_group', 'display_order',
        'visible', 'editable', 'admin_only', 'validation_rules'
    ]
    
    edit_columns = add_columns
    
    search_columns = ['name', 'label', 'field_type', 'field_group']