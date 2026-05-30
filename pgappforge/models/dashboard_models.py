"""
SQLAlchemy models for the PgAppForge dashboard system.

Provides database persistence for dashboard configurations, widgets,
and layout management following PgAppForge's model patterns.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from pgappforge.security.sqla.models import User


class DashboardLayoutType(str, Enum):
    """Dashboard layout types."""
    GRID = "grid"
    TABS = "tabs"
    SINGLE_COLUMN = "single_column"
    TWO_COLUMN = "two_column"
    CUSTOM = "custom"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.GRID.value, "Grid Layout"),
            (cls.TABS.value, "Tabbed Layout"),
            (cls.SINGLE_COLUMN.value, "Single Column"),
            (cls.TWO_COLUMN.value, "Two Column"),
            (cls.CUSTOM.value, "Custom Layout")
        ]


class WidgetType(str, Enum):
    """Widget types supported in dashboards."""
    METRIC_CARD = "metric_card"
    CHART = "chart"
    TABLE = "table"
    TEXT = "text"
    IFRAME = "iframe"
    HTML = "html"
    LIST = "list"
    GAUGE = "gauge"
    PROGRESS = "progress"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.METRIC_CARD.value, "Metric Card"),
            (cls.CHART.value, "Chart"),
            (cls.TABLE.value, "Data Table"),
            (cls.TEXT.value, "Text/Markdown"),
            (cls.IFRAME.value, "Iframe"),
            (cls.HTML.value, "HTML Content"),
            (cls.LIST.value, "List"),
            (cls.GAUGE.value, "Gauge"),
            (cls.PROGRESS.value, "Progress Bar")
        ]


class ChartType(str, Enum):
    """Chart types for chart widgets."""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    AREA = "area"
    SCATTER = "scatter"
    RADAR = "radar"
    POLAR = "polarArea"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.LINE.value, "Line Chart"),
            (cls.BAR.value, "Bar Chart"),
            (cls.PIE.value, "Pie Chart"),
            (cls.DOUGHNUT.value, "Doughnut Chart"),
            (cls.AREA.value, "Area Chart"),
            (cls.SCATTER.value, "Scatter Plot"),
            (cls.RADAR.value, "Radar Chart"),
            (cls.POLAR.value, "Polar Area Chart")
        ]


class DashboardConfig(AuditMixin, Model):
    """
    Dashboard configuration model.
    
    Stores dashboard layouts, settings, and metadata for customizable
    dashboard experiences in PgAppForge applications.
    """
    __tablename__ = 'dashboard_configs'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Layout configuration
    layout_type = Column(SQLEnum(DashboardLayoutType), nullable=False, default=DashboardLayoutType.GRID)
    layout_config = Column(JSON, default=dict)  # Layout-specific settings
    
    # Display settings
    is_public = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    refresh_interval = Column(Integer, default=0)  # Auto-refresh seconds, 0 = disabled
    
    # Permissions and sharing
    owner_id = Column(Integer, nullable=False)  # User who created the dashboard
    shared_with_roles = Column(JSON, default=list)  # Role IDs that can access
    shared_with_users = Column(JSON, default=list)  # User IDs that can access
    
    # Widget ordering and configuration
    widget_order = Column(JSON, default=list)  # Ordered list of widget IDs
    grid_settings = Column(JSON, default=dict)  # Grid layout specific settings
    
    # Metadata
    tags = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    
    def __repr__(self):
        return f"<DashboardConfig {self.name}>"

    def get_layout_config(self) -> Dict[str, Any]:
        """Get layout configuration with defaults."""
        defaults = {
            DashboardLayoutType.GRID: {
                'columns': 12,
                'row_height': 150,
                'margin': [10, 10],
                'container_padding': [20, 20]
            },
            DashboardLayoutType.TABS: {
                'tab_position': 'top',
                'animated': True
            },
            DashboardLayoutType.SINGLE_COLUMN: {
                'max_width': '1200px',
                'margin': 'auto'
            },
            DashboardLayoutType.TWO_COLUMN: {
                'left_width': 8,
                'right_width': 4,
                'gap': 20
            }
        }
        
        default_config = defaults.get(self.layout_type, {})
        return {**default_config, **(self.layout_config or {})}

    def can_user_access(self, user_id: int, user_roles: List[int]) -> bool:
        """Check if user can access this dashboard."""
        # Owner can always access
        if self.owner_id == user_id:
            return True
        
        # Public dashboards can be accessed by anyone
        if self.is_public:
            return True
        
        # Check if user is in shared users list
        if user_id in (self.shared_with_users or []):
            return True
        
        # Check if user has any shared roles
        shared_roles = set(self.shared_with_roles or [])
        user_role_set = set(user_roles)
        if shared_roles.intersection(user_role_set):
            return True
        
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'layout_type': self.layout_type.value,
            'layout_config': self.get_layout_config(),
            'is_public': self.is_public,
            'is_default': self.is_default,
            'refresh_interval': self.refresh_interval,
            'owner_id': self.owner_id,
            'widget_order': self.widget_order or [],
            'tags': self.tags or [],
            'is_active': self.is_active,
            'version': self.version,
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'updated_at': self.changed_on.isoformat() if self.changed_on else None
        }


class DashboardWidget(AuditMixin, Model):
    """
    Dashboard widget model.
    
    Represents individual widgets that can be placed on dashboards
    with their configuration, positioning, and data sources.
    """
    __tablename__ = 'dashboard_widgets'

    id = Column(Integer, primary_key=True)
    dashboard_id = Column(Integer, nullable=False)  # Reference to DashboardConfig
    
    # Widget identification
    widget_id = Column(String(100), nullable=False)  # Unique ID within dashboard
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Widget type and configuration
    widget_type = Column(SQLEnum(WidgetType), nullable=False)
    widget_config = Column(JSON, default=dict)  # Widget-specific configuration
    
    # Layout positioning
    position_x = Column(Integer, default=0)
    position_y = Column(Integer, default=0)
    width = Column(Integer, default=4)
    height = Column(Integer, default=3)
    
    # Display settings
    is_visible = Column(Boolean, default=True)
    order_index = Column(Integer, default=0)
    refresh_interval = Column(Integer, default=0)  # Widget-specific refresh, 0 = use dashboard default
    
    # Data source configuration
    data_source = Column(String(255))  # Source identifier (metric name, SQL query, etc.)
    data_config = Column(JSON, default=dict)  # Data source specific config
    
    # Styling
    background_color = Column(String(20))
    border_color = Column(String(20))
    text_color = Column(String(20))
    custom_css = Column(Text)
    
    def __repr__(self):
        return f"<DashboardWidget {self.name} ({self.widget_type.value})>"

    def get_widget_config(self) -> Dict[str, Any]:
        """Get widget configuration with type-specific defaults."""
        defaults = {
            WidgetType.METRIC_CARD: {
                'show_trend': True,
                'trend_period': '24h',
                'format': 'number',
                'decimals': 2,
                'show_sparkline': False
            },
            WidgetType.CHART: {
                'chart_type': ChartType.LINE.value,
                'time_range': '24h',
                'show_legend': True,
                'show_axes': True,
                'animate': True
            },
            WidgetType.TABLE: {
                'show_pagination': True,
                'page_size': 10,
                'show_search': True,
                'show_export': True
            },
            WidgetType.GAUGE: {
                'min_value': 0,
                'max_value': 100,
                'warning_threshold': 70,
                'critical_threshold': 90,
                'show_value': True
            },
            WidgetType.PROGRESS: {
                'min_value': 0,
                'max_value': 100,
                'show_percentage': True,
                'striped': False,
                'animated': True
            }
        }
        
        default_config = defaults.get(self.widget_type, {})
        return {**default_config, **(self.widget_config or {})}

    def get_data_config(self) -> Dict[str, Any]:
        """Get data configuration with defaults."""
        defaults = {
            'cache_duration': 300,  # 5 minutes
            'error_handling': 'show_error',  # show_error, hide_widget, show_placeholder
            'fallback_value': None
        }
        return {**defaults, **(self.data_config or {})}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'dashboard_id': self.dashboard_id,
            'widget_id': self.widget_id,
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'widget_type': self.widget_type.value,
            'widget_config': self.get_widget_config(),
            'position': {
                'x': self.position_x,
                'y': self.position_y,
                'width': self.width,
                'height': self.height
            },
            'is_visible': self.is_visible,
            'order_index': self.order_index,
            'refresh_interval': self.refresh_interval,
            'data_source': self.data_source,
            'data_config': self.get_data_config(),
            'styling': {
                'background_color': self.background_color,
                'border_color': self.border_color,
                'text_color': self.text_color,
                'custom_css': self.custom_css
            },
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'updated_at': self.changed_on.isoformat() if self.changed_on else None
        }


class DashboardTemplate(AuditMixin, Model):
    """
    Dashboard template model.
    
    Pre-configured dashboard layouts that can be used as starting points
    for creating new dashboards.
    """
    __tablename__ = 'dashboard_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Template metadata
    category = Column(String(100), default="general")
    tags = Column(JSON, default=list)
    screenshot_url = Column(String(500))
    
    # Template configuration
    layout_type = Column(SQLEnum(DashboardLayoutType), nullable=False)
    layout_config = Column(JSON, default=dict)
    
    # Widget templates
    widget_templates = Column(JSON, default=list)  # List of widget configurations
    
    # Usage and popularity
    usage_count = Column(Integer, default=0)
    is_featured = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)  # System templates vs user templates
    
    def __repr__(self):
        return f"<DashboardTemplate {self.name}>"

    def increment_usage(self):
        """Increment usage counter when template is used."""
        self.usage_count = (self.usage_count or 0) + 1

    def create_dashboard_from_template(self, name: str, title: str, owner_id: int) -> Dict[str, Any]:
        """Create dashboard configuration from this template."""
        return {
            'name': name,
            'title': title,
            'description': f"Created from template: {self.title}",
            'layout_type': self.layout_type,
            'layout_config': self.layout_config or {},
            'owner_id': owner_id,
            'widget_templates': self.widget_templates or [],
            'tags': ['template', self.name] + (self.tags or [])
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'tags': self.tags or [],
            'screenshot_url': self.screenshot_url,
            'layout_type': self.layout_type.value,
            'layout_config': self.layout_config or {},
            'widget_count': len(self.widget_templates or []),
            'usage_count': self.usage_count,
            'is_featured': self.is_featured,
            'is_system': self.is_system,
            'created_at': self.created_on.isoformat() if self.created_on else None
        }


class DashboardShare(AuditMixin, Model):
    """
    Dashboard sharing model.
    
    Tracks dashboard sharing permissions and access logs.
    """
    __tablename__ = 'dashboard_shares'

    id = Column(Integer, primary_key=True)
    dashboard_id = Column(Integer, nullable=False)
    
    # Sharing details
    shared_by_id = Column(Integer, nullable=False)
    shared_with_id = Column(Integer)  # User ID if shared with specific user
    shared_with_role = Column(String(100))  # Role name if shared with role
    
    # Permissions
    can_view = Column(Boolean, default=True)
    can_edit = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    can_share = Column(Boolean, default=False)
    
    # Sharing metadata
    share_token = Column(String(100), unique=True)  # For public sharing
    expires_at = Column(DateTime)  # Optional expiration
    is_active = Column(Boolean, default=True)
    
    # Usage tracking
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime)
    
    def __repr__(self):
        return f"<DashboardShare dashboard_id={self.dashboard_id}>"

    def is_expired(self) -> bool:
        """Check if share has expired."""
        if not self.expires_at:
            return False
        return datetime.now(tz=timezone.utc) > self.expires_at

    def record_access(self):
        """Record access to shared dashboard."""
        self.access_count = (self.access_count or 0) + 1
        self.last_accessed_at = datetime.now(tz=timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'dashboard_id': self.dashboard_id,
            'shared_by_id': self.shared_by_id,
            'shared_with_id': self.shared_with_id,
            'shared_with_role': self.shared_with_role,
            'permissions': {
                'can_view': self.can_view,
                'can_edit': self.can_edit,
                'can_delete': self.can_delete,
                'can_share': self.can_share
            },
            'share_token': self.share_token,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active,
            'is_expired': self.is_expired(),
            'access_count': self.access_count,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            'created_at': self.created_on.isoformat() if self.created_on else None
        }