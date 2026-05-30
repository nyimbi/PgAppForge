"""
User Profile Views for Flask-AppBuilder

This module provides comprehensive user profile management views including
profile editing, viewing, and administration functionality.
"""

import datetime
import logging
from typing import Any, Dict, List, Optional

from flask import flash, g, redirect, request, url_for
from flask_appbuilder.actions import action
from flask_appbuilder.baseviews import expose
from flask_appbuilder.exceptions import ValidationError
from flask_appbuilder.fieldwidgets import (
    BS3TextAreaFieldWidget,
    BS3TextFieldWidget,
    Select2Widget,
)
from flask_appbuilder.forms import DynamicForm
from flask_appbuilder.models.sqla import filters
from flask_appbuilder.security.decorators import has_access
from flask_appbuilder.views import ModelView, SimpleFormView
from flask_appbuilder.widgets import FormWidget, ListWidget, ShowWidget
from flask_babel import lazy_gettext, gettext
from wtforms import (
    BooleanField,
    DateField,
    SelectField,
    StringField,
    TextAreaField,
    validators,
)
from wtforms.validators import DataRequired, Email, Length, Optional as OptionalValidator

from flask_appbuilder.models.profiles import (
    ProfileField,
    ProfileFieldValue,
    ProfileType,
    UserProfile,
)
from flask_appbuilder.security.profile_validators import (
    ProfileAuditLogger,
    ProfileSecurityManager,
    ProfileValidator,
)

log = logging.getLogger(__name__)


class ProfileFormMixin:
    """Mixin for common profile form functionality"""
    
    def get_profile_form_fields(self) -> Dict[str, Any]:
        """
        Get standard profile form fields
        """
        return {
            'phone': StringField(
                lazy_gettext('Phone'),
                validators=[OptionalValidator(), Length(max=50)],
                widget=BS3TextFieldWidget()
            ),
            'mobile': StringField(
                lazy_gettext('Mobile'),
                validators=[OptionalValidator(), Length(max=50)],
                widget=BS3TextFieldWidget()
            ),
            'date_of_birth': DateField(
                lazy_gettext('Date of Birth'),
                validators=[OptionalValidator()]
            ),
            'biography': TextAreaField(
                lazy_gettext('Biography'),
                validators=[OptionalValidator()],
                widget=BS3TextAreaFieldWidget(rows=4)
            ),
            'address_line1': StringField(
                lazy_gettext('Address Line 1'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'address_line2': StringField(
                lazy_gettext('Address Line 2'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'city': StringField(
                lazy_gettext('City'),
                validators=[OptionalValidator(), Length(max=100)],
                widget=BS3TextFieldWidget()
            ),
            'state': StringField(
                lazy_gettext('State/Province'),
                validators=[OptionalValidator(), Length(max=100)],
                widget=BS3TextFieldWidget()
            ),
            'country': StringField(
                lazy_gettext('Country'),
                validators=[OptionalValidator(), Length(max=100)],
                widget=BS3TextFieldWidget()
            ),
            'postal_code': StringField(
                lazy_gettext('Postal Code'),
                validators=[OptionalValidator(), Length(max=20)],
                widget=BS3TextFieldWidget()
            ),
            'timezone': SelectField(
                lazy_gettext('Timezone'),
                choices=[
                    ('UTC', 'UTC'),
                    ('America/New_York', 'Eastern Time'),
                    ('America/Chicago', 'Central Time'),
                    ('America/Denver', 'Mountain Time'),
                    ('America/Los_Angeles', 'Pacific Time'),
                    ('Europe/London', 'GMT'),
                    ('Europe/Paris', 'Central European Time'),
                    ('Asia/Tokyo', 'Japan Standard Time'),
                    ('Asia/Shanghai', 'China Standard Time'),
                ],
                default='UTC',
                widget=Select2Widget()
            ),
            'language': SelectField(
                lazy_gettext('Language'),
                choices=[
                    ('en', 'English'),
                    ('es', 'Español'),
                    ('fr', 'Français'),
                    ('de', 'Deutsch'),
                    ('pt', 'Português'),
                    ('it', 'Italiano'),
                ],
                default='en',
                widget=Select2Widget()
            ),
            'website': StringField(
                lazy_gettext('Website'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'linkedin': StringField(
                lazy_gettext('LinkedIn'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'twitter': StringField(
                lazy_gettext('Twitter'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'github': StringField(
                lazy_gettext('GitHub'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
        }
    
    def get_professional_form_fields(self) -> Dict[str, Any]:
        """
        Get professional profile form fields
        """
        return {
            'job_title': StringField(
                lazy_gettext('Job Title'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'department': StringField(
                lazy_gettext('Department'),
                validators=[OptionalValidator(), Length(max=100)],
                widget=BS3TextFieldWidget()
            ),
            'organization': StringField(
                lazy_gettext('Organization'),
                validators=[OptionalValidator(), Length(max=255)],
                widget=BS3TextFieldWidget()
            ),
            'employee_id': StringField(
                lazy_gettext('Employee ID'),
                validators=[OptionalValidator(), Length(max=50)],
                widget=BS3TextFieldWidget()
            ),
            'start_date': DateField(
                lazy_gettext('Start Date'),
                validators=[OptionalValidator()]
            ),
            'email_notifications': BooleanField(
                lazy_gettext('Email Notifications'),
                default=True
            ),
            'sms_notifications': BooleanField(
                lazy_gettext('SMS Notifications'),
                default=False
            ),
            'push_notifications': BooleanField(
                lazy_gettext('Push Notifications'),
                default=True
            ),
        }


class UserProfileView(ModelView, ProfileFormMixin):
    """
    Administrative view for managing user profiles
    """
    
    datamodel = None  # Will be set in manager
    route_base = '/userprofiles'
    
    # List configuration
    list_title = lazy_gettext('User Profiles')
    list_columns = [
        'user.username', 'user.first_name', 'user.last_name',
        'user.email', 'profile_type', 'profile_completed',
        'last_profile_update'
    ]
    
    search_columns = [
        'user.username', 'user.first_name', 'user.last_name',
        'user.email', 'city', 'country'
    ]
    
    # Show configuration
    show_title = lazy_gettext('User Profile Details')
    show_columns = [
        'user.username', 'user.first_name', 'user.last_name',
        'user.email', 'profile_type', 'phone', 'mobile',
        'date_of_birth', 'biography', 'address_line1', 'address_line2',
        'city', 'state', 'country', 'postal_code', 'timezone',
        'language', 'website', 'linkedin', 'twitter', 'github',
        'profile_completed', 'profile_verified', 'last_profile_update',
        'created_on', 'changed_on'
    ]
    
    # Edit configuration
    edit_title = lazy_gettext('Edit User Profile')
    edit_columns = [
        'profile_type', 'phone', 'mobile', 'date_of_birth',
        'biography', 'address_line1', 'address_line2', 'city',
        'state', 'country', 'postal_code', 'timezone', 'language',
        'website', 'linkedin', 'twitter', 'github',
        'profile_visibility', 'profile_verified'
    ]
    
    # Add configuration
    add_title = lazy_gettext('Create User Profile')
    add_columns = ['user', 'profile_type']
    
    # Filtering - profiles that have associated users
    base_filters = []
    
    # Permissions
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    # Custom actions
    @action(
        "mark_verified",
        lazy_gettext("Mark as Verified"),
        lazy_gettext("Mark selected profiles as verified?"),
        "fa-check-circle",
        multiple=True
    )
    def mark_verified(self, profiles):
        """Mark selected profiles as verified"""
        pass
        count = 0
        for profile in profiles:
            profile.profile_verified = True
            count += 1
        
        try:
            self.datamodel.session.commit()
            flash(gettext(f"Successfully verified {count} profiles"), "info")
        except Exception as e:
            flash(gettext(f"Error verifying profiles: {e}"), "danger")
            self.datamodel.session.rollback()
        
        return redirect(self.get_redirect())
    
    @action(
        "update_completion",
        lazy_gettext("Update Completion"),
        lazy_gettext("Update completion status for selected profiles?"),
        "fa-refresh",
        multiple=True
    )
    def update_completion(self, profiles):
        """Update profile completion status"""
        pass
        count = 0
        for profile in profiles:
            profile.calculate_completion_status()
            count += 1
        
        try:
            self.datamodel.session.commit()
            flash(gettext(f"Successfully updated {count} profiles"), "info")
        except Exception as e:
            flash(gettext(f"Error updating profiles: {e}"), "danger")
            self.datamodel.session.rollback()
        
        return redirect(self.get_redirect())


class MyProfileView(SimpleFormView):
    """View for users to edit their own profile
    """
    
    route_base = '/myprofile'
    form_title = lazy_gettext('My Profile')
    message = lazy_gettext('Update your profile information')
    
    def __init__(self):
        super().__init__()
        # Create dynamic form based on available fields
        self.form = self.create_profile_form()
    
    def create_profile_form(self):
        # Create a dynamic form based on user's profile
        class ProfileEditForm(DynamicForm):
            pass
        
        # Add basic profile fields
        profile_mixin = ProfileFormMixin()
        basic_fields = profile_mixin.get_profile_form_fields()
        for field_name, field in basic_fields.items():
            setattr(ProfileEditForm, field_name, field)
        
        # Add professional fields if user has extended profile
        if hasattr(g, 'user') and g.user:
            profile = self.get_user_profile(g.user)
            if profile and profile.profile_type in [ProfileType.EMPLOYEE, ProfileType.ADMIN]:
                prof_fields = profile_mixin.get_professional_form_fields()
                for field_name, field in prof_fields.items():
                    setattr(ProfileEditForm, field_name, field)
        
        return ProfileEditForm
    
    def get_user_profile(self, user) -> Optional[UserProfile]:
        """
        Get or create user profile
        """
        if not hasattr(user, 'profile') or not user.profile:
            # Create profile if it doesn't exist
            from flask_appbuilder.models.profiles import UserProfile
            profile = UserProfile(user_id=user.id)
            self.appbuilder.get_session.add(profile)
            self.appbuilder.get_session.commit()
            return profile
        return user.profile
    
    @expose('/edit', methods=['GET', 'POST'])
    @has_access
    def edit(self):
        """
        Edit current user's profile
        """
        pass
        if not g.user:
            flash(gettext("Please login to access your profile"), "warning")
            return redirect(url_for('AuthDBView.login'))
        
        profile = self.get_user_profile(g.user)
        form = self.form(obj=profile)
        
        if request.method == 'POST' and form.validate_on_submit():
            try:
                # Get form data
                form_data = {}
                for field_name in form.data:
                    if hasattr(profile, field_name):
                        form_data[field_name] = form.data[field_name]
                
                # Security validation
                for field_name in form_data:
                    if not ProfileSecurityManager.can_edit_field(field_name, profile, g.user):
                        flash(gettext(f"You don't have permission to edit {field_name}"), "warning")
                        return redirect(request.url)
                
                # Sanitize data
                sanitized_data = ProfileSecurityManager.sanitize_profile_data(form_data)
                
                # Validate data
                validation_errors = ProfileValidator.validate_profile_data(profile, sanitized_data)
                if validation_errors:
                    for error in validation_errors:
                        flash(gettext(error), "danger")
                    return self.render_template(
                        'appbuilder/general/model/edit.html',
                        title=self.form_title,
                        form=form,
                        appbuilder=self.appbuilder
                    )
                
                # Track changed fields for audit
                changed_fields = {}
                for key, new_value in sanitized_data.items():
                    old_value = getattr(profile, key, None)
                    if old_value != new_value:
                        changed_fields[key] = {'old': old_value, 'new': new_value}
                        setattr(profile, key, new_value)
                
                if changed_fields:
                    profile.last_profile_update = datetime.datetime.now(datetime.timezone.utc)
                    profile.update_profile_completion()
                    
                    # Log the change
                    ProfileAuditLogger.log_profile_change(profile, changed_fields, g.user)
                
                self.appbuilder.get_session.commit()
                flash(gettext("Profile updated successfully"), "success")
                return redirect(url_for('MyProfileView.show'))
                
            except ValidationError as e:
                flash(gettext(f"Validation error: {e}"), "danger")
                self.appbuilder.get_session.rollback()
            except Exception as e:
                flash(gettext(f"Error updating profile: {e}"), "danger")
                self.appbuilder.get_session.rollback()
        
        return self.render_template(
            'appbuilder/general/model/edit.html',
            title=self.form_title,
            form=form,
            appbuilder=self.appbuilder
        )
    
    @expose('/')
    @has_access
    def show(self):
        """Show current user's profile"""
        pass
        if not g.user:
            flash(gettext("Please login to access your profile"), "warning")
            return redirect(url_for('AuthDBView.login'))
        
        profile = self.get_user_profile(g.user)
        
        return self.render_template(
            'appbuilder/profile/show_profile.html',
            profile=profile,
            user=g.user,
            completion_rate=profile.calculate_profile_completion(),
            appbuilder=self.appbuilder
        )


class PublicProfileView(SimpleFormView):
    """View for displaying public user profiles
    """
    
    route_base = '/profile'
    
    @expose('/<int:user_id>')
    def show_public(self, user_id: int):
        """
        Show public profile for a specific user
        """
        pass
        user = self.appbuilder.sm.get_user_by_id(user_id)
        if not user:
            flash(gettext("User not found"), "warning")
            return redirect(url_for('IndexView.index'))
        
        profile = getattr(user, 'profile', None)
        if not profile or not profile.can_view_profile(g.user):
            flash(gettext("Profile not accessible"), "warning")
            return redirect(url_for('IndexView.index'))
        
        # Log access to sensitive profile data
        viewed_fields = [
            'full_name', 'biography', 'job_title', 'organization', 
            'city', 'country', 'skills', 'certifications'
        ]
        ProfileAuditLogger.log_profile_access(profile, g.user, viewed_fields)
        
        return self.render_template(
            'appbuilder/profile/public_profile.html',
            profile=profile,
            user=user,
            is_own_profile=(g.user and g.user.id == user_id),
            appbuilder=self.appbuilder
        )


class ProfileFieldView(ModelView):
    """Administrative view for managing dynamic profile fields
    """
    
    datamodel = None  # Will be set in manager
    route_base = '/profilefields'
    
    # List configuration
    list_title = lazy_gettext('Profile Fields')
    list_columns = [
        'name', 'label', 'field_type', 'required',
        'field_group', 'display_order', 'visible'
    ]
    
    # Show configuration
    show_title = lazy_gettext('Profile Field Details')
    show_columns = [
        'name', 'label', 'description', 'field_type',
        'required', 'unique', 'max_length', 'default_value',
        'choices', 'field_group', 'display_order',
        'visible', 'editable', 'admin_only', 'validation_rules'
    ]
    
    # Edit configuration
    edit_title = lazy_gettext('Edit Profile Field')
    edit_columns = [
        'name', 'label', 'description', 'field_type',
        'required', 'unique', 'max_length', 'default_value',
        'choices', 'field_group', 'display_order',
        'visible', 'editable', 'admin_only', 'validation_rules'
    ]
    
    # Add configuration
    add_title = lazy_gettext('Add Profile Field')
    add_columns = [
        'name', 'label', 'description', 'field_type',
        'required', 'field_group', 'display_order'
    ]
    
    # Permissions
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    # Validators
    validators_columns = {
        'name': [validators.Regexp(r'^[a-z_][a-z0-9_]*$', 
                                  message='Field name must be lowercase letters, numbers, and underscores only')]
    }


class ProfileStatsView(SimpleFormView):
    """View for profile statistics and analytics"""
    
    route_base = '/profile-stats'
    
    @expose('/')
    @has_access
    def index(self):
        """Show profile statistics dashboard
        """
        # Get profile statistics
        total_profiles = self.appbuilder.get_session.query(UserProfile).count()
        completed_profiles = self.appbuilder.get_session.query(UserProfile).filter(
            UserProfile.profile_completed == True
        ).count()
        verified_profiles = self.appbuilder.get_session.query(UserProfile).filter(
            UserProfile.profile_verified == True
        ).count()
        
        # Profile types distribution
        from sqlalchemy import func
        profile_types = self.appbuilder.get_session.query(
            UserProfile.profile_type, func.count(UserProfile.id)
        ).group_by(UserProfile.profile_type).all()
        
        stats = {
            'total_profiles': total_profiles,
            'completed_profiles': completed_profiles,
            'verified_profiles': verified_profiles,
            'completion_rate': (completed_profiles / total_profiles * 100) if total_profiles > 0 else 0,
            'verification_rate': (verified_profiles / total_profiles * 100) if total_profiles > 0 else 0,
            'profile_types': dict(profile_types)
        }
        
        return self.render_template(
            'appbuilder/profile/stats.html',
            stats=stats,
            appbuilder=self.appbuilder
        )
