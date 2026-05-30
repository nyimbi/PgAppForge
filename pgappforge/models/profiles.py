"""
User Profile Models and Mixins for PgAppForge

This module provides extensible user profile functionality that can be easily
customized and extended for different application needs.
"""
import datetime
import enum
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin, FileColumn, ImageColumn


class ProfileType(enum.Enum):
    """Standard profile types that can be extended"""
    BASIC = "basic"
    EMPLOYEE = "employee"
    CUSTOMER = "customer"
    VENDOR = "vendor"
    ADMIN = "admin"


class ProfileMixin:
    """
    Base mixin for user profile functionality.
    Add this to your User model to get basic profile features.
    """
    
    # Personal Information
    phone = Column(String(50))
    mobile = Column(String(50))
    date_of_birth = Column(Date)
    biography = Column(Text)
    
    # Address Information
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    postal_code = Column(String(20))
    
    # Profile Settings
    timezone = Column(String(50), default='UTC')
    language = Column(String(10), default='en')
    theme = Column(String(50), default='default')
    
    # Social Media
    website = Column(String(255))
    linkedin = Column(String(255))
    twitter = Column(String(255))
    github = Column(String(255))
    
    # Preferences (stored as JSON for flexibility)
    preferences = Column(JSON, default=dict)
    
    # Profile completion and validation
    profile_completed = Column(Boolean, default=False)
    profile_verified = Column(Boolean, default=False)
    
    @hybrid_property
    def full_name(self):
        """Computed full name property"""
        return f"{self.first_name} {self.last_name}".strip()
    
    @hybrid_property
    def initials(self):
        """User initials for avatar display"""
        if self.first_name and self.last_name:
            return f"{self.first_name[0]}{self.last_name[0]}".upper()
        return self.username[0].upper() if self.username else "U"
    
    @hybrid_property
    def full_address(self):
        """Formatted full address"""
        address_parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.postal_code,
            self.country
        ]
        return ", ".join([part for part in address_parts if part])
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a specific preference value"""
        if not self.preferences:
            return default
        return self.preferences.get(key, default)
    
    def set_preference(self, key: str, value: Any) -> None:
        """Set a specific preference value"""
        if not self.preferences:
            self.preferences = {}
        self.preferences[key] = value
    
    def calculate_profile_completion(self) -> float:
        """Calculate profile completion percentage"""
        required_fields = [
            'first_name', 'last_name', 'email', 'phone',
            'date_of_birth', 'city', 'country'
        ]
        completed_fields = sum(1 for field in required_fields 
                             if getattr(self, field, None))
        return (completed_fields / len(required_fields)) * 100
    
    def update_profile_completion(self) -> None:
        """Update profile completion status"""
        completion_rate = self.calculate_profile_completion()
        self.profile_completed = completion_rate >= 80.0


class ExtendedProfileMixin(ProfileMixin):
    """
    Extended profile mixin with additional professional and organizational fields.
    Use this for more comprehensive user profiles.
    """
    
    # Professional Information
    job_title = Column(String(255))
    department = Column(String(100))
    organization = Column(String(255))
    manager_email = Column(String(320))
    employee_id = Column(String(50))
    start_date = Column(Date)
    
    # Contact Preferences
    email_notifications = Column(Boolean, default=True)
    sms_notifications = Column(Boolean, default=False)
    push_notifications = Column(Boolean, default=True)
    
    # Emergency Contact
    emergency_contact_name = Column(String(255))
    emergency_contact_phone = Column(String(50))
    emergency_contact_relationship = Column(String(100))
    
    # Skills and Certifications
    skills = Column(JSON, default=list)  # Array of skill names
    certifications = Column(JSON, default=list)  # Array of certification objects
    
    def add_skill(self, skill: str) -> None:
        """Add a skill to the user's profile"""
        if not self.skills:
            self.skills = []
        if skill not in self.skills:
            self.skills.append(skill)
    
    def remove_skill(self, skill: str) -> None:
        """Remove a skill from the user's profile"""
        if self.skills and skill in self.skills:
            self.skills.remove(skill)
    
    def add_certification(self, name: str, issuer: str, 
                         date_obtained: datetime.date = None,
                         expiry_date: datetime.date = None) -> None:
        """Add a certification to the user's profile"""
        if not self.certifications:
            self.certifications = []
        
        cert = {
            'name': name,
            'issuer': issuer,
            'date_obtained': date_obtained.isoformat() if date_obtained else None,
            'expiry_date': expiry_date.isoformat() if expiry_date else None
        }
        self.certifications.append(cert)


class UserProfile(Model, AuditMixin, ExtendedProfileMixin):
    """
    Standalone user profile model that extends the base User model.
    This allows for a clean separation of concerns while maintaining relationships.
    """
    
    __tablename__ = 'ab_user_profile'
    
    id = Column(Integer, primary_key=True)
    
    # Link to the User model
    user_id = Column(Integer, ForeignKey('ab_user.id'), unique=True, nullable=False)
    user = relationship("User", backref="profile", uselist=False, foreign_keys=[user_id])
    
    # Profile type for categorization
    profile_type = Column(Enum(ProfileType), default=ProfileType.BASIC)
    
    # Avatar and media
    avatar = Column(ImageColumn(size=(150, 150, True), thumbnail_size=(30, 30, True)))
    cover_image = Column(ImageColumn(size=(800, 200, True), thumbnail_size=(400, 100, True)))
    
    # Additional metadata
    profile_visibility = Column(String(20), default='public')  # public, private, limited
    last_profile_update = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Custom fields (JSON for maximum flexibility)
    custom_fields = Column(JSON, default=dict)
    
    def __repr__(self) -> str:
        return f"<UserProfile {self.user.username if self.user else 'Unknown'}>"
    
    def get_custom_field(self, key: str, default: Any = None) -> Any:
        """Get a custom field value"""
        if not self.custom_fields:
            return default
        return self.custom_fields.get(key, default)
    
    def set_custom_field(self, key: str, value: Any) -> None:
        """Set a custom field value"""
        if not self.custom_fields:
            self.custom_fields = {}
        self.custom_fields[key] = value
        self.last_profile_update = datetime.datetime.now(datetime.timezone.utc)
    
    def is_profile_public(self) -> bool:
        """Check if profile is publicly viewable"""
        return self.profile_visibility == 'public'
    
    def can_view_profile(self, viewer_user) -> bool:
        """Check if a user can view this profile"""
        if self.profile_visibility == 'public':
            return True
        if self.profile_visibility == 'private':
            return viewer_user and viewer_user.id == self.user_id
        # Add custom logic for 'limited' visibility here
        return False


class ProfileField(Model, AuditMixin):
    """
    Dynamic profile field definitions for creating custom profile forms.
    This allows administrators to define custom fields without code changes.
    """
    
    __tablename__ = 'ab_profile_field'
    
    id = Column(Integer, primary_key=True)
    
    # Field definition
    name = Column(String(100), unique=True, nullable=False)
    label = Column(String(255), nullable=False)
    description = Column(Text)
    field_type = Column(String(50), nullable=False)  # string, integer, date, boolean, json, etc.
    
    # Field properties
    required = Column(Boolean, default=False)
    unique = Column(Boolean, default=False)
    max_length = Column(Integer)
    default_value = Column(String(255))
    choices = Column(JSON)  # For select fields
    
    # Field grouping and ordering
    field_group = Column(String(100), default='custom')
    display_order = Column(Integer, default=0)
    
    # Visibility and permissions
    visible = Column(Boolean, default=True)
    editable = Column(Boolean, default=True)
    admin_only = Column(Boolean, default=False)
    
    # Validation rules
    validation_rules = Column(JSON, default=dict)
    
    def __repr__(self) -> str:
        return f"<ProfileField {self.name}>"


class ProfileFieldValue(Model, AuditMixin):
    """
    Stores values for dynamic profile fields.
    This provides the ultimate flexibility for custom profile data.
    """
    
    __tablename__ = 'ab_profile_field_value'
    
    id = Column(Integer, primary_key=True)
    
    # Relationships
    profile_id = Column(Integer, ForeignKey('ab_user_profile.id'), nullable=False)
    profile = relationship("UserProfile", backref="field_values")
    
    field_id = Column(Integer, ForeignKey('ab_profile_field.id'), nullable=False)
    field = relationship("ProfileField", backref="values")
    
    # Value storage (JSON for flexibility)
    value = Column(JSON)
    
    def __repr__(self) -> str:
        return f"<ProfileFieldValue {self.field.name if self.field else 'Unknown'}>"
    
    def get_typed_value(self):
        """Get the value converted to the appropriate type"""
        if not self.field or not self.value:
            return None
            
        field_type = self.field.field_type.lower()
        
        if field_type == 'integer':
            return int(self.value) if self.value else None
        elif field_type == 'boolean':
            return bool(self.value) if self.value is not None else None
        elif field_type == 'date':
            if isinstance(self.value, str):
                return datetime.datetime.fromisoformat(self.value).date()
            return self.value
        elif field_type == 'datetime':
            if isinstance(self.value, str):
                return datetime.datetime.fromisoformat(self.value)
            return self.value
        else:
            return self.value