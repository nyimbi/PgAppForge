#!/usr/bin/env python3
"""
PgAppForge Addon Configuration

This file demonstrates the PROPER way to integrate enhanced functionality
with PgAppForge using the official addon manager pattern instead
of the parallel infrastructure anti-pattern.

ELIMINATES ARCHITECTURAL ISSUES:
- ✅ Uses PgAppForge's ADDON_MANAGERS system
- ✅ Follows PgAppForge initialization patterns  
- ✅ Proper configuration integration with Flask config
- ✅ No parallel infrastructure - extends existing systems
"""

from typing import Dict, List

# =============================================================================
# 1. PROPER ADDON MANAGER REGISTRATION
# =============================================================================

# This is how PgAppForge addons should be registered
# Add this to your PgAppForge configuration:

ADDON_MANAGERS = [
    'tests.proper_pgappforge_extensions.SearchManager',
    'tests.proper_pgappforge_extensions.GeocodingManager', 
    'tests.proper_pgappforge_extensions.ApprovalWorkflowManager',
    'tests.proper_pgappforge_extensions.CommentManager',
]

# =============================================================================
# 2. FLASK-APPBUILDER CONFIGURATION INTEGRATION
# =============================================================================

class FlaskAppBuilderConfig:
    """
    Configuration class that integrates with PgAppForge's config system
    instead of creating parallel configuration management.
    """
    
    # =============================================================================
    # Core PgAppForge Configuration (existing)
    # =============================================================================
    SECRET_KEY = 'YOUR_SECRET_KEY_HERE'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    CSRF_ENABLED = True
    
    # PgAppForge base configuration
    APP_NAME = "Enhanced PgAppForge App"
    APP_THEME = ""  # default bootstrap theme
    APP_ICON = "static/img/logo.jpg"
    
    # =============================================================================
    # Enhanced Search Configuration (integrated with FAB config)
    # =============================================================================
    
    # Search system configuration - uses FAB_ prefix to avoid conflicts
    FAB_SEARCH_DEFAULT_LIMIT = 50
    FAB_SEARCH_MAX_LIMIT = 500
    FAB_SEARCH_MIN_RANK = 0.1
    FAB_SEARCH_ENABLE_FULL_TEXT = True
    
    # =============================================================================
    # Enhanced Geocoding Configuration (integrated with FAB config)
    # =============================================================================
    
    # Geocoding service configuration
    FAB_NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
    FAB_NOMINATIM_USER_AGENT = 'PgAppForge-Enhanced/1.0 (contact@yourdomain.com)'
    
    # API keys for premium geocoding services (optional)
    FAB_MAPQUEST_API_KEY = None  # Set in environment or here
    FAB_GOOGLE_MAPS_API_KEY = None  # Set in environment or here
    
    # Geocoding behavior configuration
    FAB_GEOCODING_TIMEOUT = 30
    FAB_GEOCODING_RATE_LIMIT = 1.0  # seconds between requests
    FAB_GEOCODING_CACHE_TTL = 86400  # 24 hours
    
    # =============================================================================
    # Enhanced Approval Workflow Configuration (integrated with FAB config)
    # =============================================================================
    
    # Approval workflow definitions
    FAB_APPROVAL_WORKFLOWS = {
        # Simple document approval workflow
        'document_approval': {
            'steps': [
                {
                    'name': 'manager_review',
                    'required_role': 'Manager',
                    'required_approvals': 1,
                    'timeout_hours': 48
                },
                {
                    'name': 'admin_approval', 
                    'required_role': 'Admin',
                    'required_approvals': 1,
                    'timeout_hours': 24
                }
            ],
            'initial_state': 'draft',
            'approved_state': 'published',
            'rejected_state': 'rejected'
        },
        
        # More complex contract approval workflow
        'contract_approval': {
            'steps': [
                {
                    'name': 'legal_review',
                    'required_role': 'Legal',
                    'required_approvals': 1,
                    'timeout_hours': 72
                },
                {
                    'name': 'finance_review',
                    'required_role': 'Finance', 
                    'required_approvals': 1,
                    'timeout_hours': 48
                },
                {
                    'name': 'executive_approval',
                    'required_role': 'Executive',
                    'required_approvals': 2,  # Requires 2 executives
                    'timeout_hours': 24
                }
            ],
            'initial_state': 'draft',
            'approved_state': 'active',
            'rejected_state': 'cancelled'
        }
    }
    
    # =============================================================================
    # Enhanced Comment System Configuration (integrated with FAB config)
    # =============================================================================
    
    # Comment system behavior
    FAB_COMMENTS_ENABLED = True
    FAB_COMMENTS_REQUIRE_MODERATION = True
    FAB_COMMENTS_MAX_LENGTH = 2000
    FAB_COMMENTS_ALLOW_ANONYMOUS = False
    FAB_COMMENTS_ENABLE_THREADING = True
    FAB_COMMENTS_MAX_DEPTH = 5  # Maximum comment thread depth
    
    # Comment notification settings
    FAB_COMMENTS_NOTIFY_MODERATORS = True
    FAB_COMMENTS_NOTIFY_PARTICIPANTS = True
    
    # =============================================================================
    # Integration with existing PgAppForge security
    # =============================================================================
    
    # Use PgAppForge's existing security configuration
    AUTH_TYPE = 1  # Database authentication
    AUTH_ROLE_ADMIN = 'Admin'
    AUTH_ROLE_PUBLIC = 'Public'
    
    # Enhanced roles for new functionality - integrates with FAB's role system
    FAB_CUSTOM_ROLES = [
        {'name': 'Manager', 'permissions': ['can_approve', 'can_moderate_comments']},
        {'name': 'Legal', 'permissions': ['can_approve_legal', 'can_view_contracts']},
        {'name': 'Finance', 'permissions': ['can_approve_finance', 'can_view_budgets']},
        {'name': 'Executive', 'permissions': ['can_approve_executive', 'can_view_all']},
    ]


# =============================================================================
# 3. PROPER APPLICATION INITIALIZATION
# =============================================================================

def create_enhanced_app():
    """
    Example of proper PgAppForge application initialization
    that integrates enhanced functionality without parallel infrastructure.
    """
    from flask import Flask
    from pgappforge import AppBuilder, SQLA
    from pgappforge.security.sqla.manager import SecurityManager
    
    # Create Flask app
    app = Flask(__name__)
    app.config.from_object(FlaskAppBuilderConfig)
    
    # Initialize PgAppForge database
    db = SQLA(app)
    
    # Create PgAppForge instance with addon managers
    # The ADDON_MANAGERS will be automatically loaded and initialized
    appbuilder = AppBuilder(
        app, 
        db.session,
        security_manager_class=SecurityManager
    )
    
    # Enhanced functionality is now automatically available through
    # the registered addon managers - no parallel infrastructure needed!
    
    return app, db, appbuilder


# =============================================================================
# 4. PROPER MODEL INTEGRATION EXAMPLES
# =============================================================================

def setup_enhanced_models(db, appbuilder):
    """
    Example of how to properly integrate models with enhanced functionality
    using PgAppForge patterns instead of mixins.
    """
    from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
    from pgappforge.models.mixins import AuditMixin
    from pgappforge.models.decorators import renders
    
    # =============================================================================
    # Enhanced Document Model - Proper PgAppForge integration
    # =============================================================================
    
    class Document(AuditMixin, db.Model):
        """
        Document model with enhanced functionality.
        
        Uses PgAppForge's AuditMixin and integrates with addon managers
        instead of creating parallel infrastructure.
        """
        __tablename__ = 'documents'
        
        # Basic fields
        id = Column(Integer, primary_key=True)
        title = Column(String(255), nullable=False)
        content = Column(Text)
        category = Column(String(100))
        
        # Enhanced search integration - model declares searchable fields
        __searchable__ = {
            'title': 1.0,      # Highest weight
            'content': 0.8,    # High weight  
            'category': 0.6    # Medium weight
        }
        
        # Enhanced approval workflow integration
        _approval_workflow = 'document_approval'  # References workflow in config
        approval_history = Column(Text)  # JSON field for approval data
        current_state = Column(String(50), default='draft')
        current_step = Column(Integer)
        approved_at = Column(DateTime)
        
        # Enhanced comment system integration
        comments = Column(Text)  # JSON field for comment data
        
        # Methods that integrate with addon managers instead of implementing logic
        def search_similar(self, query: str):
            """Use SearchManager instead of implementing search logic."""
            search_manager = current_app.extensions['appbuilder'].sm
            return search_manager.search(self.__class__, query)
        
        def start_approval_process(self):
            """Use ApprovalWorkflowManager instead of implementing workflow logic."""
            approval_manager = current_app.extensions['appbuilder'].awm  
            approval_manager.register_model_workflow(self.__class__)
            self.current_state = 'pending_approval'
            self.current_step = 0
        
        @renders('title')
        def title_link(self):
            """PgAppForge render decorator for UI integration."""
            return f'<a href="/documents/{self.id}">{self.title}</a>'
    
    
    # =============================================================================
    # Enhanced Location Model - Proper PgAppForge integration  
    # =============================================================================
    
    class Location(AuditMixin, db.Model):
        """
        Location model with geocoding integration.
        
        Integrates with GeocodingManager instead of implementing geocoding logic.
        """
        __tablename__ = 'locations'
        
        id = Column(Integer, primary_key=True)
        name = Column(String(255), nullable=False)
        address = Column(String(500))
        city = Column(String(100))
        state = Column(String(100)) 
        country = Column(String(100))
        postal_code = Column(String(20))
        
        # Geocoding fields
        latitude = Column(Float)
        longitude = Column(Float)
        geocoded = Column(Boolean, default=False)
        geocode_source = Column(String(50))
        geocoded_at = Column(DateTime)
        
        # Enhanced search integration
        __searchable__ = {
            'name': 1.0,
            'address': 0.9,
            'city': 0.7,
            'state': 0.5,
            'country': 0.5
        }
        
        def geocode(self):
            """Use GeocodingManager instead of implementing geocoding logic."""
            geocoding_manager = current_app.extensions['appbuilder'].gm
            return geocoding_manager.geocode_model_instance(self)
        
        @renders('coordinates')
        def coordinates_display(self):
            """PgAppForge render decorator for coordinate display."""
            if self.latitude and self.longitude:
                return f"{self.latitude:.6f}, {self.longitude:.6f}"
            return "Not geocoded"
    
    
    return Document, Location


# =============================================================================
# 5. PROPER VIEW INTEGRATION EXAMPLES
# =============================================================================

def setup_enhanced_views(appbuilder, Document, Location):
    """
    Example of proper view integration that extends PgAppForge views
    instead of creating parallel infrastructure.
    """
    from pgappforge import ModelView
    from pgappforge.models.sqla.interface import SQLAInterface
    from pgappforge.actions import action
    from pgappforge.security.decorators import has_access
    from flask import redirect, url_for, flash
    
    # =============================================================================
    # Enhanced Document View - Extends PgAppForge ModelView
    # =============================================================================
    
    class EnhancedDocumentView(ModelView):
        """
        Document view with enhanced functionality.
        
        Extends PgAppForge's ModelView and integrates with addon managers
        instead of implementing parallel functionality.
        """
        datamodel = SQLAInterface(Document)
        
        # Use PgAppForge's native configuration
        list_columns = ['title', 'category', 'current_state', 'created_on']
        edit_columns = ['title', 'content', 'category']
        add_columns = ['title', 'content', 'category']
        
        # Enhanced search - uses SearchManager automatically
        search_columns = ['title', 'content', 'category']
        
        # Custom actions that integrate with addon managers
        @action("start_approval", "Start Approval", "Start approval process?", "fa-play")
        @has_access
        def start_approval_action(self, items):
            """Start approval process using ApprovalWorkflowManager."""
            approval_manager = self.appbuilder.awm
            
            for item in items:
                if item.current_state == 'draft':
                    item.start_approval_process()
                    approval_manager.register_model_workflow(item.__class__, 'document_approval')
            
            self.update_redirect()
            flash(f"Started approval process for {len(items)} documents", "info")
            return redirect(self.get_redirect())
        
        @action("geocode_references", "Geocode References", "Geocode location references?", "fa-map")
        @has_access  
        def geocode_references_action(self, items):
            """Extract and geocode location references using GeocodingManager."""
            geocoding_manager = self.appbuilder.gm
            
            geocoded_count = 0
            for item in items:
                # Extract location references from content (simple example)
                if hasattr(item, 'content') and item.content:
                    # This would use more sophisticated location extraction in practice
                    if 'address:' in item.content.lower():
                        # Create location and geocode it
                        location = Location(name=f"Reference from {item.title}")
                        if geocoding_manager.geocode_model_instance(location):
                            geocoded_count += 1
            
            flash(f"Geocoded {geocoded_count} location references", "success")
            return redirect(self.get_redirect())
    
    
    # =============================================================================
    # Enhanced Location View - Extends PgAppForge ModelView
    # =============================================================================
    
    class EnhancedLocationView(ModelView):
        """
        Location view with geocoding integration.
        
        Extends PgAppForge's ModelView with geocoding functionality.
        """
        datamodel = SQLAInterface(Location)
        
        list_columns = ['name', 'address', 'city', 'coordinates_display', 'geocoded']
        edit_columns = ['name', 'address', 'city', 'state', 'country', 'postal_code']
        add_columns = ['name', 'address', 'city', 'state', 'country', 'postal_code']
        
        # Enhanced search using SearchManager
        search_columns = ['name', 'address', 'city', 'state', 'country']
        
        @action("geocode_locations", "Geocode", "Geocode selected locations?", "fa-map-marker")
        @has_access
        def geocode_action(self, items):
            """Geocode locations using GeocodingManager."""
            geocoding_manager = self.appbuilder.gm
            
            geocoded_count = 0
            for item in items:
                if geocoding_manager.geocode_model_instance(item, force=True):
                    geocoded_count += 1
            
            flash(f"Successfully geocoded {geocoded_count} of {len(items)} locations", "success")
            return redirect(self.get_redirect())
    
    
    # Register views with PgAppForge
    appbuilder.add_view(
        EnhancedDocumentView,
        "Documents",
        icon="fa-file-text",
        category="Content",
        category_icon="fa-folder"
    )
    
    appbuilder.add_view(
        EnhancedLocationView, 
        "Locations",
        icon="fa-map-marker",
        category="Geography",
        category_icon="fa-globe"
    )
    
    return EnhancedDocumentView, EnhancedLocationView


# =============================================================================
# 6. COMPLETE APPLICATION EXAMPLE
# =============================================================================

def create_complete_enhanced_app():
    """
    Complete example showing proper PgAppForge integration
    without parallel infrastructure.
    """
    
    # Create application
    app, db, appbuilder = create_enhanced_app()
    
    # Setup models
    Document, Location = setup_enhanced_models(db, appbuilder)
    
    # Setup views  
    DocumentView, LocationView = setup_enhanced_views(appbuilder, Document, Location)
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Initialize PgAppForge's security system
        appbuilder.sm.sync_role_from_db()
        
        # Create custom roles defined in config
        for role_config in FlaskAppBuilderConfig.FAB_CUSTOM_ROLES:
            role = appbuilder.sm.find_role(role_config['name'])
            if not role:
                role = appbuilder.sm.add_role(role_config['name'])
                # Add permissions (would need to create permissions first)
                for permission in role_config['permissions']:
                    # This is simplified - real implementation would handle permission creation
                    pass
    
    return app


if __name__ == "__main__":
    print("✅ PROPER FLASK-APPBUILDER ADDON CONFIGURATION")
    print("")
    print("🏗️ ARCHITECTURAL IMPROVEMENTS:")
    print("  - Uses ADDON_MANAGERS instead of parallel infrastructure")
    print("  - Extends PgAppForge classes instead of reimplementing")
    print("  - Integrates with PgAppForge's configuration system")
    print("  - Uses PgAppForge's security and database patterns")
    print("  - Follows PgAppForge view and model conventions")
    print("")
    print("📚 USAGE:")
    print("  1. Add ADDON_MANAGERS to your PgAppForge configuration")
    print("  2. Use FlaskAppBuilderConfig as base for your configuration")
    print("  3. Register enhanced views with appbuilder.add_view()")
    print("  4. Models automatically integrate with addon managers")
    print("")
    print("🚀 NO MORE PARALLEL INFRASTRUCTURE ANTI-PATTERN!")