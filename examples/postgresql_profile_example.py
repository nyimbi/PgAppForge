#!/usr/bin/env python3
"""
PostgreSQL Advanced Profile Management Example

This example demonstrates PgAppForge's comprehensive PostgreSQL support
including JSONB, PostGIS, pgvector, arrays, and other PostgreSQL-specific types.

Prerequisites:
- PostgreSQL 12+
- PostGIS extension
- pgvector extension
- ltree extension (optional)
- hstore extension (optional)

Setup:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS hstore;
```
"""

import datetime
import json
import uuid
from typing import List, Optional

from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.sqla import Model
from pgappforge.security.sqla.models import User
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.dialects.postgresql import (
    ARRAY, INET, INTERVAL, JSONB, UUID, BIT, TSVECTOR
)

# Import PostgreSQL-specific components
from pgappforge.models.postgresql import (
    AdvancedPostgreSQLProfileMixin,
    Vector, Geometry, Geography, LTREE, HSTORE,
    PostgreSQLProfileMixin, PostGISProfileMixin, PgVectorProfileMixin
)
from pgappforge.widgets_postgresql.postgresql import (
    JSONBWidget, PostgreSQLArrayWidget, PostGISGeometryWidget,
    PgVectorWidget, PostgreSQLUUIDWidget
)


class PostgreSQLUserProfile(Model, AdvancedPostgreSQLProfileMixin):
    """
    Advanced user profile using all PostgreSQL features
    """
    __tablename__ = 'postgresql_user_profile'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True)
    
    # Basic information
    display_name = Column(String(255))
    bio = Column(Text)
    
    # JSONB fields for flexible data
    settings = Column(JSONB, default=dict)
    achievements = Column(JSONB, default=list)
    social_media = Column(JSONB, default=dict)
    
    # Array fields
    certifications = Column(ARRAY(String(255)), default=list)
    interests = Column(ARRAY(String(100)), default=list)
    project_tags = Column(ARRAY(String(50)), default=list)
    
    # Network and system fields
    last_active_ip = Column(INET)
    allowed_ips = Column(ARRAY(INET), default=list)
    
    # UUID fields for integration
    external_systems = Column(JSONB, default=dict)  # Store multiple system UUIDs
    
    # Geospatial fields
    current_location = Column(Geometry('POINT', 4326))
    home_address_location = Column(Geometry('POINT', 4326))
    work_territories = Column(ARRAY(Geometry('POLYGON', 4326)), default=list)
    
    # Vector embeddings for AI features
    profile_vector = Column(Vector(768))  # Profile similarity matching
    skills_vector = Column(Vector(384))   # Skill-based matching
    content_vector = Column(Vector(512))  # Content-based recommendations
    
    # Full-text search
    searchable_content = Column(TSVECTOR)
    
    # Time-based fields
    notification_intervals = Column(JSONB, default=dict)
    
    # Feature flags as bit string
    enabled_features = Column(BIT(64), default='0000000000000000000000000000000000000000000000000000000000000000')
    
    # Organizational hierarchy
    org_path = Column(LTREE)
    
    # Custom key-value attributes
    custom_fields = Column(HSTORE, default=dict)
    
    def __repr__(self):
        return f'<PostgreSQLUserProfile {self.display_name}>'
    
    # JSONB helper methods
    def set_setting(self, key: str, value) -> None:
        """Set a user setting"""
        if not self.settings:
            self.settings = {}
        self.settings[key] = value
    
    def get_setting(self, key: str, default=None):
        """Get a user setting"""
        return self.settings.get(key, default) if self.settings else default
    
    def add_achievement(self, title: str, description: str, date: datetime.datetime = None):
        """Add an achievement"""
        if not self.achievements:
            self.achievements = []
        
        achievement = {
            'title': title,
            'description': description,
            'date': (date or datetime.datetime.utcnow()).isoformat(),
            'id': str(uuid.uuid4())
        }
        self.achievements.append(achievement)
    
    def set_social_media(self, platform: str, username: str, url: str = None):
        """Set social media information"""
        if not self.social_media:
            self.social_media = {}
        
        self.social_media[platform] = {
            'username': username,
            'url': url or f'https://{platform}.com/{username}',
            'verified': False
        }
    
    # Array helper methods
    def add_certification(self, cert_name: str) -> None:
        """Add a certification"""
        if not self.certifications:
            self.certifications = []
        if cert_name not in self.certifications:
            self.certifications.append(cert_name)
    
    def add_interest(self, interest: str) -> None:
        """Add an interest"""
        if not self.interests:
            self.interests = []
        if interest not in self.interests:
            self.interests.append(interest)
    
    def tag_project(self, tag: str) -> None:
        """Add a project tag"""
        if not self.project_tags:
            self.project_tags = []
        if tag not in self.project_tags:
            self.project_tags.append(tag)
    
    # Geospatial methods
    def set_current_location(self, latitude: float, longitude: float):
        """Set current location as WKT"""
        self.current_location = f'POINT({longitude} {latitude})'
    
    def set_home_location(self, latitude: float, longitude: float):
        """Set home location"""
        self.home_address_location = f'POINT({longitude} {latitude})'
    
    def add_work_territory(self, polygon_coordinates: List[List[float]]):
        """Add a work territory polygon"""
        # Convert coordinates to WKT POLYGON format
        coord_str = ', '.join([f'{lon} {lat}' for lon, lat in polygon_coordinates])
        polygon_wkt = f'POLYGON(({coord_str}))'
        
        if not self.work_territories:
            self.work_territories = []
        self.work_territories.append(polygon_wkt)
    
    # Vector embedding methods
    def set_profile_embedding(self, embedding: List[float]):
        """Set profile embedding vector"""
        if len(embedding) != 768:
            raise ValueError("Profile embedding must be 768 dimensions")
        self.profile_vector = embedding
    
    def set_skills_embedding(self, embedding: List[float]):
        """Set skills embedding vector"""
        if len(embedding) != 384:
            raise ValueError("Skills embedding must be 384 dimensions")
        self.skills_vector = embedding
    
    # Feature flag methods
    def enable_feature(self, feature_bit: int):
        """Enable a feature flag by setting the specified bit"""
        if not (0 <= feature_bit < 64):
            raise ValueError("Feature bit must be between 0 and 63")
        
        if not self.enabled_features:
            self.enabled_features = '0' * 64
        
        # Convert bit string to list for easier manipulation
        bits = list(str(self.enabled_features))
        # Set bit from left (MSB first)
        bits[feature_bit] = '1'
        self.enabled_features = ''.join(bits)
    
    def disable_feature(self, feature_bit: int):
        """Disable a feature flag by clearing the specified bit"""
        if not (0 <= feature_bit < 64):
            raise ValueError("Feature bit must be between 0 and 63")
        
        if not self.enabled_features:
            self.enabled_features = '0' * 64
        
        bits = list(str(self.enabled_features))
        bits[feature_bit] = '0'
        self.enabled_features = ''.join(bits)
    
    def is_feature_enabled(self, feature_bit: int) -> bool:
        """Check if a feature is enabled by testing the specified bit"""
        if not (0 <= feature_bit < 64):
            return False
        
        if not self.enabled_features:
            return False
        
        return str(self.enabled_features)[feature_bit] == '1'
    
    def get_enabled_features(self) -> List[int]:
        """Get list of all enabled feature bit positions"""
        if not self.enabled_features:
            return []
        
        enabled = []
        for i, bit in enumerate(str(self.enabled_features)):
            if bit == '1':
                enabled.append(i)
        return enabled
    
    # Organizational methods
    def set_org_position(self, department: str, team: str = None, role: str = None):
        """Set organizational position using LTREE"""
        path_parts = [department]
        if team:
            path_parts.append(team)
        if role:
            path_parts.append(role)
        
        self.org_path = '.'.join(path_parts)
    
    def is_in_same_department(self, other_profile) -> bool:
        """Check if in same department"""
        if self.org_path and other_profile.org_path:
            return str(self.org_path).split('.')[0] == str(other_profile.org_path).split('.')[0]
        return False


class CompanyLocation(Model):
    """
    Company locations with PostGIS support
    """
    __tablename__ = 'company_locations'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    address = Column(Text)
    
    # Geometric data
    location = Column(Geometry('POINT', 4326))
    coverage_area = Column(Geometry('POLYGON', 4326))
    
    # Additional PostgreSQL types
    established_date = Column(DateTime)
    timezone_offset = Column(INTERVAL)
    contact_info = Column(JSONB)
    
    def __repr__(self):
        return f'<CompanyLocation {self.name}>'


def create_app():
    """Create Flask application with PostgreSQL support"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'postgresql-demo-key'
    
    # PostgreSQL database configuration
    # Update these credentials for your PostgreSQL setup
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'postgresql://username:password@localhost/fab_postgresql_demo'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Enable PostgreSQL-specific features
    app.config['PGAF_ENABLE_POSTGRESQL_EXTENSIONS'] = True
    app.config['PGAF_POSTGRESQL_WIDGETS_ENABLED'] = True
    
    # Optional: Configure extensions
    app.config['PGAF_POSTGRESQL_EXTENSIONS'] = [
        'postgis',      # Spatial data support
        'vector',       # pgvector extension
        'ltree',        # Hierarchical data
        'hstore',       # Key-value storage
        'btree_gin',    # Enhanced indexing
        'pg_trgm'       # Fuzzy text search
    ]
    
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    return app, appbuilder


def create_sample_data(appbuilder):
    """Create sample data demonstrating PostgreSQL features"""
    try:
        # Create a sample user profile
        profile = PostgreSQLUserProfile(
            user_id=1,
            display_name='Dr. Jane PostgreSQL',
            bio='Database expert specializing in PostgreSQL advanced features'
        )
        
        # Set JSONB settings
        profile.set_setting('theme', 'dark')
        profile.set_setting('notifications', {
            'email': True,
            'push': False,
            'sms': True,
            'frequency': 'daily'
        })
        profile.set_setting('privacy_level', 'public')
        
        # Add achievements
        profile.add_achievement(
            'PostgreSQL Certified',
            'Achieved PostgreSQL Professional Certification',
            datetime.datetime(2023, 6, 15)
        )
        profile.add_achievement(
            'PostGIS Expert',
            'Completed advanced PostGIS spatial analysis course',
            datetime.datetime(2023, 8, 20)
        )
        
        # Set social media
        profile.set_social_media('github', 'janepostgres', 'https://github.com/janepostgres')
        profile.set_social_media('linkedin', 'jane-postgresql', 'https://linkedin.com/in/jane-postgresql')
        profile.set_social_media('twitter', 'janepostgres')
        
        # Add certifications and interests
        profile.add_certification('PostgreSQL Professional Certification')
        profile.add_certification('PostGIS Spatial Database Certification')
        profile.add_certification('pgvector Machine Learning Integration')
        
        profile.add_interest('Database Architecture')
        profile.add_interest('Geospatial Analysis')
        profile.add_interest('Machine Learning')
        profile.add_interest('Performance Optimization')
        
        # Set geospatial data
        profile.set_current_location(40.7128, -74.0060)  # NYC
        profile.set_home_location(40.7580, -73.9855)     # Times Square
        
        # Add work territory (Manhattan area)
        manhattan_area = [
            [-74.0479, 40.6892],  # Southwest
            [-73.9441, 40.6892],  # Southeast  
            [-73.9441, 40.8820],  # Northeast
            [-74.0479, 40.8820],  # Northwest
            [-74.0479, 40.6892]   # Close polygon
        ]
        profile.add_work_territory(manhattan_area)
        
        # Set organizational position
        profile.set_org_position('engineering', 'database_team', 'senior_developer')
        
        # Set vector embeddings (dummy data for demonstration)
        import random
        profile.set_profile_embedding([random.uniform(-1, 1) for _ in range(768)])
        profile.set_skills_embedding([random.uniform(-1, 1) for _ in range(384)])
        
        # Set content vector embedding
        profile.content_vector = [random.uniform(-1, 1) for _ in range(512)]
        
        # Enable some feature flags for demonstration
        profile.enable_feature(0)   # Feature 0: Advanced Search
        profile.enable_feature(5)   # Feature 5: Notifications
        profile.enable_feature(12)  # Feature 12: Analytics
        profile.enable_feature(25)  # Feature 25: Experimental UI
        
        # Set custom fields
        if not profile.custom_fields:
            profile.custom_fields = {}
        profile.custom_fields.update({
            'favorite_postgres_feature': 'JSONB',
            'years_experience': '8',
            'specialization': 'spatial_databases'
        })
        
        appbuilder.get_session.add(profile)
        
        # Create a company location
        headquarters = CompanyLocation(
            name='PostgreSQL Corp HQ',
            address='123 Database Ave, PostgreSQL City, PC 12345',
            location='POINT(-74.0060 40.7128)',  # NYC coordinates
            established_date=datetime.datetime(2010, 1, 1),
            timezone_offset='5 hours',  # EST offset
            contact_info={
                'phone': '+1-555-POSTGRES',
                'email': 'contact@postgresql-corp.com',
                'website': 'https://postgresql-corp.com',
                'business_hours': {
                    'monday': '9:00-17:00',
                    'tuesday': '9:00-17:00',
                    'wednesday': '9:00-17:00',
                    'thursday': '9:00-17:00',
                    'friday': '9:00-17:00'
                }
            }
        )
        
        # Coverage area (rough circle around NYC)
        coverage_polygon_wkt = '''POLYGON((-74.2591 40.4774, -73.7004 40.4774, 
                                         -73.7004 40.9176, -74.2591 40.9176, 
                                         -74.2591 40.4774))'''
        headquarters.coverage_area = coverage_polygon_wkt
        
        appbuilder.get_session.add(headquarters)
        appbuilder.get_session.commit()
        
        print("✅ PostgreSQL sample data created successfully!")
        return profile
        
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
        appbuilder.get_session.rollback()
        return None


def demonstrate_postgresql_features(appbuilder, profile):
    """Demonstrate PostgreSQL-specific features"""
    print("\n=== PostgreSQL Features Demonstration ===")
    
    if not profile:
        print("No profile data available for demonstration")
        return
    
    print(f"Profile: {profile.display_name}")
    
    # JSONB demonstrations
    print(f"\n📊 JSONB Settings:")
    print(f"  Theme: {profile.get_setting('theme')}")
    print(f"  Notifications: {json.dumps(profile.get_setting('notifications'), indent=2)}")
    
    print(f"\n🏆 JSONB Achievements:")
    for achievement in profile.achievements or []:
        print(f"  - {achievement['title']}: {achievement['description']} ({achievement['date'][:10]})")
    
    print(f"\n🌐 JSONB Social Media:")
    for platform, info in (profile.social_media or {}).items():
        print(f"  - {platform.title()}: @{info['username']} ({info['url']})")
    
    # Array demonstrations
    print(f"\n📜 Array Certifications:")
    for cert in profile.certifications or []:
        print(f"  - {cert}")
    
    print(f"\n💡 Array Interests:")
    print(f"  {', '.join(profile.interests or [])}")
    
    print(f"\n🏷️ Array Project Tags:")
    print(f"  {', '.join(profile.project_tags or [])}")
    
    # Geospatial demonstrations
    print(f"\n🗺️ PostGIS Locations:")
    print(f"  Current Location: {profile.current_location}")
    print(f"  Home Location: {profile.home_address_location}")
    print(f"  Work Territories: {len(profile.work_territories or [])} defined")
    
    # Vector demonstrations
    print(f"\n🤖 pgvector Embeddings:")
    profile_vec_len = len(profile.profile_vector) if profile.profile_vector else 0
    skills_vec_len = len(profile.skills_vector) if profile.skills_vector else 0
    content_vec_len = len(profile.content_vector) if profile.content_vector else 0
    print(f"  Profile Vector: {profile_vec_len} dimensions")
    print(f"  Skills Vector: {skills_vec_len} dimensions")
    print(f"  Content Vector: {content_vec_len} dimensions")
    
    if profile.profile_vector:
        # Calculate vector magnitude and statistics
        import math
        magnitude = math.sqrt(sum(x*x for x in profile.profile_vector))
        mean_value = sum(profile.profile_vector) / len(profile.profile_vector)
        min_value = min(profile.profile_vector)
        max_value = max(profile.profile_vector)
        print(f"  Profile Vector Stats:")
        print(f"    Magnitude: {magnitude:.4f}")
        print(f"    Mean: {mean_value:.4f}")
        print(f"    Range: [{min_value:.4f}, {max_value:.4f}]")
    
    # Feature flags demonstration
    print(f"\n🚩 Feature Flags (Bit String):")
    enabled_features = profile.get_enabled_features()
    print(f"  Total Features: 64 bits")
    print(f"  Enabled Features: {len(enabled_features)} ({enabled_features})")
    print(f"  Feature 0 (Advanced Search): {'✅' if profile.is_feature_enabled(0) else '❌'}")
    print(f"  Feature 5 (Notifications): {'✅' if profile.is_feature_enabled(5) else '❌'}")
    print(f"  Feature 12 (Analytics): {'✅' if profile.is_feature_enabled(12) else '❌'}")
    print(f"  Feature 25 (Experimental UI): {'✅' if profile.is_feature_enabled(25) else '❌'}")
    
    # LTREE organizational structure
    print(f"\n🏢 LTREE Organizational Path:")
    print(f"  Position: {profile.org_path}")
    if profile.org_path:
        path_parts = str(profile.org_path).split('.')
        print(f"  Department: {path_parts[0]}")
        if len(path_parts) > 1:
            print(f"  Team: {path_parts[1]}")
        if len(path_parts) > 2:
            print(f"  Role: {path_parts[2]}")
    
    # HSTORE custom fields
    print(f"\n🔧 HSTORE Custom Fields:")
    for key, value in (profile.custom_fields or {}).items():
        print(f"  {key}: {value}")
    
    print(f"\nPostgreSQL features demonstration completed!")


def run_postgresql_queries(appbuilder):
    """Demonstrate PostgreSQL-specific SQL queries"""
    print("\n=== PostgreSQL Query Examples ===")
    
    try:
        # JSONB query examples
        print("🔍 JSONB Queries:")
        
        # Find profiles with specific settings
        result = appbuilder.get_session.execute(
            "SELECT display_name, settings->>'theme' as theme "
            "FROM postgresql_user_profile "
            "WHERE settings->>'theme' = 'dark'"
        ).fetchall()
        
        for row in result:
            print(f"  Dark theme user: {row[0]}")
        
        # Array query examples
        print("\n🔍 Array Queries:")
        
        # Find profiles with specific interests
        result = appbuilder.get_session.execute(
            "SELECT display_name "
            "FROM postgresql_user_profile "
            "WHERE 'Machine Learning' = ANY(interests)"
        ).fetchall()
        
        for row in result:
            print(f"  ML interested user: {row[0]}")
        
        # Full-text search example (if configured)
        print("\n🔍 Full-text Search:")
        print("  (Would demonstrate TSVECTOR queries in production)")
        
        # Geospatial query examples
        print("\n🔍 PostGIS Spatial Queries:")
        print("  Example spatial queries:")
        print("  - ST_Distance(location1, location2) -- Calculate distance between points")
        print("  - ST_Within(point, polygon) -- Check if point is within area")
        print("  - ST_DWithin(location, center, 1000) -- Find locations within 1000 meters")
        print("  - ST_Buffer(location, 500) -- Create 500m buffer around location")
        
        # Try to demonstrate actual spatial queries
        try:
            result = appbuilder.get_session.execute(
                "SELECT display_name, ST_AsText(current_location) as location "
                "FROM postgresql_user_profile "
                "WHERE current_location IS NOT NULL"
            ).fetchall()
            
            for row in result:
                print(f"  Location data: {row[0]} at {row[1]}")
        except Exception:
            print("  (Spatial queries require PostGIS extension)")
        
        # Vector similarity examples
        print("\n🔍 pgvector Similarity Queries:")
        print("  Example similarity queries:")
        print("  - SELECT * FROM profiles ORDER BY profile_vector <=> '[0.1,0.2,...]' LIMIT 10;")
        print("  - SELECT *, (1 - (profile_vector <=> '[0.1,0.2,...]')) as similarity")
        print("    FROM profiles WHERE (1 - (profile_vector <=> '[0.1,0.2,...]')) > 0.8;")
        
        # Demonstrate actual vector operations if possible
        try:
            # Get all profiles with vectors for similarity calculation
            profiles = appbuilder.get_session.query(
                "SELECT id, display_name FROM postgresql_user_profile WHERE profile_vector IS NOT NULL"
            ).fetchall()
            
            if profiles:
                print(f"  Found {len(profiles)} profiles with embeddings for similarity comparison")
        except Exception:
            pass
        
    except Exception as e:
        print(f"Query demonstration error (expected in demo): {e}")


if __name__ == '__main__':
    """Run the PostgreSQL example application"""
    app, appbuilder = create_app()
    
    with app.app_context():
        try:
            # Create database tables
            from sqlalchemy import text
            
            # Check and create PostgreSQL extensions
            extensions = ['postgis', 'vector', 'ltree', 'hstore']
            for ext in extensions:
                try:
                    appbuilder.get_session.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
                    print(f"✅ Extension {ext} ready")
                except Exception as e:
                    print(f"⚠️  Extension {ext} not available: {e}")
            
            appbuilder.get_session.commit()
            
            # Create database tables
            appbuilder.get_session.get_bind().create_all()
            print("✅ Database tables created")
            
            # Create sample data
            profile = create_sample_data(appbuilder)
            
            # Demonstrate features
            demonstrate_postgresql_features(appbuilder, profile)
            
            # Show query examples
            run_postgresql_queries(appbuilder)
            
        except Exception as e:
            print(f"❌ Application setup error: {e}")
            print("\n📋 Setup Requirements:")
            print("  1. PostgreSQL 12+ server running")
            print("  2. Update database connection string in code")
            print("  3. Install extensions: postgis, vector, ltree, hstore")
            print("  4. Grant necessary permissions to database user")
            print("\n💡 Extension Installation:")
            print("  sudo -u postgres psql -d your_database")
            print("  CREATE EXTENSION IF NOT EXISTS postgis;")
            print("  CREATE EXTENSION IF NOT EXISTS vector;")
            print("  CREATE EXTENSION IF NOT EXISTS ltree;")
            print("  CREATE EXTENSION IF NOT EXISTS hstore;")
    
    print("\n=== PostgreSQL Integration Summary ===")
    print("✅ JSONB support with rich editing widgets and syntax highlighting")
    print("✅ PostgreSQL arrays with drag-and-drop interface and validation")
    print("✅ PostGIS geometry/geography with interactive map visualization")
    print("✅ pgvector embeddings with similarity search and visualization")
    print("✅ UUID generation and validation with one-click generation")
    print("✅ Interval support with preset buttons and natural language parsing")
    print("✅ Bit string manipulation with visual tools and operations")
    print("✅ Network type support (INET, MACADDR) with validation")
    print("✅ LTREE hierarchical data with interactive tree widget support")
    print("✅ Parent-child relationship management for standard tables")
    print("✅ HSTORE key-value storage with dynamic attribute management")
    print("✅ Full-text search capabilities with TSVECTOR indexing")
    print("\n🎯 Key Features:")
    print("  - Comprehensive form widgets for all PostgreSQL types")
    print("  - Advanced spatial queries and mapping integration")
    print("  - AI/ML ready with vector similarity search")
    print("  - Production-ready with validation and error handling")
    print("  - Extensible architecture for custom PostgreSQL types")
    print("\n🚀 Ready for enterprise PostgreSQL applications!")