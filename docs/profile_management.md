# User Profile Management System

PgAppForge now includes a comprehensive, extensible user profile management system that allows for flexible customization while maintaining security and performance.

## Overview

The profile system provides:

- **Extensible Profile Models**: Mix-and-match profile functionality
- **Dynamic Custom Fields**: Add fields without code changes
- **Security & Validation**: Field-level permissions and data validation
- **Multiple Profile Types**: Basic, Employee, Customer, Vendor, Admin profiles
- **REST API**: Full API support for profile operations
- **Audit Logging**: Track all profile changes and access

## Quick Start

### Basic Profile Integration

Add basic profile functionality to your User model:

```python
from pgappforge.models.profiles import ProfileMixin
from pgappforge.security.sqla.models import User

class MyUser(User, ProfileMixin):
    pass
```

### Extended Profile Integration

For comprehensive profile features:

```python
from pgappforge.models.profiles import ExtendedProfileMixin
from pgappforge.security.sqla.models import User

class MyUser(User, ExtendedProfileMixin):
    pass
```

### Standalone Profile Model

Use the standalone profile model (recommended):

```python
from pgappforge.models.profiles import UserProfile
from pgappforge.security.profile_views import MyProfileView, UserProfileView

# Register views
appbuilder.add_view(MyProfileView, "My Profile", icon="fa-user")
appbuilder.add_view(UserProfileView, "Manage Profiles", icon="fa-users", category="Admin")
```

## Profile Types

The system supports multiple profile types:

- **BASIC**: Standard user profile with personal information
- **EMPLOYEE**: Extended profile with professional details
- **CUSTOMER**: Customer-specific profile features
- **VENDOR**: Vendor/supplier profile information
- **ADMIN**: Administrative profile with extended permissions

## Profile Features

### Personal Information
- Full name, contact details
- Date of birth, biography
- Address information
- Timezone and language preferences

### Professional Information (Extended Profiles)
- Job title, department, organization
- Employee ID, start date
- Manager contact information
- Skills and certifications

### Social Media Integration
- Website, LinkedIn, Twitter, GitHub links
- Professional networking information

### Customization
- JSON-based preferences storage
- Dynamic custom fields
- Profile visibility controls
- Avatar and cover image support

## Views and UI

### My Profile View
Users can edit their own profiles through a comprehensive form interface:

```python
from pgappforge.security.profile_views import MyProfileView

appbuilder.add_view(MyProfileView, "My Profile", icon="fa-user")
```

### Public Profile View
Display public user profiles:

```python
from pgappforge.security.profile_views import PublicProfileView

appbuilder.add_view(PublicProfileView, "Public Profiles", icon="fa-users")
```

### Administrative Views
For profile management:

```python
from pgappforge.security.profile_views import UserProfileView, ProfileFieldView

appbuilder.add_view(UserProfileView, "Manage Profiles", category="Admin")
appbuilder.add_view(ProfileFieldView, "Profile Fields", category="Admin")
```

## REST API

The profile system includes comprehensive REST API endpoints:

```python
from pgappforge.api.profiles import UserProfileApi

appbuilder.add_api(UserProfileApi)
```

### API Endpoints

- `GET /api/v1/profiles/my-profile` - Get current user's profile
- `PUT /api/v1/profiles/my-profile` - Update current user's profile  
- `GET /api/v1/profiles/public/<user_id>` - Get public profile
- `GET /api/v1/profiles/stats` - Get profile statistics
- `POST /api/v1/profiles/search` - Advanced profile search

### Example API Usage

```python
import requests

# Get my profile
response = requests.get('/api/v1/profiles/my-profile', 
                       headers={'Authorization': 'Bearer <token>'})

# Update profile
profile_data = {
    'phone': '+1-555-0123',
    'job_title': 'Senior Developer',
    'skills': ['Python', 'JavaScript', 'React']
}
response = requests.put('/api/v1/profiles/my-profile',
                       json=profile_data,
                       headers={'Authorization': 'Bearer <token>'})
```

## Security Features

### Field-Level Permissions
Control who can view and edit specific profile fields:

```python
from pgappforge.security.profile_validators import ProfileSecurityManager

# Check if user can edit a field
can_edit = ProfileSecurityManager.can_edit_field('employee_id', profile, user)

# Check if user can view a field  
can_view = ProfileSecurityManager.can_view_field('phone', profile, viewer)
```

### Data Validation and Sanitization
Automatic validation and sanitization of profile data:

```python
from pgappforge.security.profile_validators import ProfileValidator

# Validate profile data
errors = ProfileValidator.validate_profile_data(profile, form_data)
```

### Audit Logging
Track profile changes and access:

```python
from pgappforge.security.profile_validators import ProfileAuditLogger

# Log profile changes
ProfileAuditLogger.log_profile_change(profile, changed_fields, editor_user)

# Log profile access
ProfileAuditLogger.log_profile_access(profile, viewer_user, fields_accessed)
```

## Dynamic Custom Fields

Add custom fields without code changes:

```python
from pgappforge.models.profiles import ProfileField

# Create a custom field
custom_field = ProfileField(
    name='security_clearance',
    label='Security Clearance',
    field_type='string',
    choices=['None', 'Confidential', 'Secret', 'Top Secret'],
    admin_only=True
)
```

### Field Types
- `string` - Text fields
- `integer` - Numeric fields  
- `date` - Date fields
- `datetime` - Date/time fields
- `boolean` - Yes/no fields
- `json` - Complex data structures

## Profile Completion and Verification

Track profile completeness and verification status:

```python
# Calculate completion rate
completion_rate = profile.calculate_profile_completion()

# Update completion status
profile.update_profile_completion()

# Check if profile is verified
if profile.profile_verified:
    # Show verified badge
    pass
```

## Customizing Profile Templates

Override the default templates to match your application's design:

### My Profile Template
`templates/appbuilder/profile/show_profile.html`

### Public Profile Template  
`templates/appbuilder/profile/public_profile.html`

### Edit Profile Template
Use the standard PgAppForge form templates or create custom ones.

## Migration from Existing Systems

### From Basic User Model
If you have existing user data:

1. Create UserProfile records for existing users
2. Migrate data from User fields to Profile fields
3. Update views to use profile system

### Database Migration Example

```python
def migrate_user_profiles():
    for user in User.query.all():
        if not hasattr(user, 'profile') or not user.profile:
            profile = UserProfile(
                user_id=user.id,
                phone=getattr(user, 'phone', None),
                # ... migrate other fields
            )
            db.session.add(profile)
    
    db.session.commit()
```

## Performance Considerations

### Database Optimization
- Use eager loading for user-profile relationships
- Index frequently queried fields
- Consider caching for public profiles

### Caching Strategy
```python
from flask_caching import Cache

cache = Cache(app)

@cache.memoize(timeout=300)
def get_public_profile(user_id):
    return UserProfile.query.filter_by(user_id=user_id).first()
```

## Configuration Options

Configure profile system behavior:

```python
app.config.update({
    'PROFILE_COMPLETION_REQUIRED_FIELDS': [
        'first_name', 'last_name', 'email', 'phone'
    ],
    'PROFILE_COMPLETION_THRESHOLD': 80.0,
    'PROFILE_ENABLE_AUDIT_LOGGING': True,
    'PROFILE_MAX_CUSTOM_FIELDS': 50,
    'PROFILE_MAX_SKILLS': 50,
    'PROFILE_MAX_CERTIFICATIONS': 20,
})
```

## Best Practices

### Security
- Always validate and sanitize profile data
- Use field-level permissions appropriately
- Enable audit logging for sensitive fields
- Implement proper access controls

### Performance  
- Use pagination for profile lists
- Cache frequently accessed profiles
- Optimize database queries with proper indexing

### User Experience
- Provide clear profile completion indicators
- Use progressive disclosure for advanced fields
- Implement real-time validation feedback

### Data Quality
- Implement validation rules for profile data
- Provide clear field descriptions
- Use appropriate input types and constraints

## Troubleshooting

### Common Issues

**Profile not showing for user**
- Check if UserProfile record exists
- Verify profile visibility settings
- Check user permissions

**Custom fields not appearing**
- Verify ProfileField configuration
- Check field visibility settings
- Ensure proper form integration

**API authentication errors**
- Verify API token configuration
- Check endpoint permissions
- Validate request headers

### Debug Mode

Enable debug logging for profile operations:

```python
import logging

logging.getLogger('pgappforge.models.profiles').setLevel(logging.DEBUG)
logging.getLogger('pgappforge.security.profile_validators').setLevel(logging.DEBUG)
```

## Examples

See the complete working example in `examples/profile_management.py` which demonstrates:

- Setting up profile models and views
- Creating sample data
- Using the API endpoints
- Implementing custom profile features

Run the example:

```bash
cd examples
python profile_management.py
```

## Contributing

To contribute to the profile system:

1. Add tests for new features
2. Update documentation  
3. Follow existing code patterns
4. Ensure backward compatibility
5. Add migration scripts if needed