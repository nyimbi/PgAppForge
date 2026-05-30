"""
SQLAlchemy models for the Flask-AppBuilder export system.

Provides database persistence for export jobs, configurations, and history
following Flask-AppBuilder's model patterns and conventions.
"""

from datetime import datetime, timedelta
from enum import Enum
import json
import os
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSON
from flask_appbuilder import Model
from flask_appbuilder.models.mixins import AuditMixin


class ExportFormat(str, Enum):
    """Export format types."""
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"
    JSON = "json"
    XML = "xml"
    HTML = "html"
    TSV = "tsv"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.CSV.value, "CSV (Comma Separated Values)"),
            (cls.XLSX.value, "Excel (XLSX)"),
            (cls.PDF.value, "PDF Document"),
            (cls.JSON.value, "JSON"),
            (cls.XML.value, "XML"),
            (cls.HTML.value, "HTML Table"),
            (cls.TSV.value, "TSV (Tab Separated Values)")
        ]

    @property
    def content_type(self) -> str:
        """Get MIME content type for the format."""
        content_types = {
            self.CSV: "text/csv",
            self.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            self.PDF: "application/pdf",
            self.JSON: "application/json",
            self.XML: "application/xml",
            self.HTML: "text/html",
            self.TSV: "text/tab-separated-values"
        }
        return content_types.get(self, "application/octet-stream")

    @property
    def file_extension(self) -> str:
        """Get file extension for the format."""
        return f".{self.value}"


class ExportStatus(str, Enum):
    """Export job status types."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.PENDING.value, "Pending"),
            (cls.PROCESSING.value, "Processing"),
            (cls.COMPLETED.value, "Completed"),
            (cls.FAILED.value, "Failed"),
            (cls.CANCELLED.value, "Cancelled"),
            (cls.EXPIRED.value, "Expired")
        ]


class ExportPriority(str, Enum):
    """Export job priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

    @classmethod
    def get_choices(cls):
        """Get choices for form fields."""
        return [
            (cls.LOW.value, "Low Priority"),
            (cls.NORMAL.value, "Normal Priority"),
            (cls.HIGH.value, "High Priority"),
            (cls.URGENT.value, "Urgent Priority")
        ]


class ExportJob(AuditMixin, Model):
    """
    Export job model.
    
    Tracks export operations including configuration, status, progress,
    and generated file information.
    """
    __tablename__ = 'export_jobs'

    id = Column(Integer, primary_key=True)
    
    # Job identification
    job_id = Column(String(100), unique=True, nullable=False)  # UUID for job tracking
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Export configuration
    export_format = Column(SQLEnum(ExportFormat), nullable=False)
    data_source = Column(String(255), nullable=False)  # Table, view, or query identifier
    data_source_config = Column(JSON, default=dict)  # Additional source configuration
    
    # Export options
    export_options = Column(JSON, default=dict)  # Format-specific options
    filters = Column(JSON, default=dict)  # Data filtering options
    columns = Column(JSON, default=list)  # Specific columns to export (empty = all)
    
    # Job control
    status = Column(SQLEnum(ExportStatus), nullable=False, default=ExportStatus.PENDING)
    priority = Column(SQLEnum(ExportPriority), default=ExportPriority.NORMAL)
    scheduled_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Progress tracking
    progress_percentage = Column(Integer, default=0)
    progress_message = Column(String(500))
    total_records = Column(Integer)
    processed_records = Column(Integer, default=0)
    
    # Results
    file_path = Column(String(1000))  # Path to generated file
    file_size = Column(Integer)  # File size in bytes
    download_url = Column(String(1000))  # URL for downloading file
    download_count = Column(Integer, default=0)
    
    # Error handling
    error_message = Column(Text)
    error_details = Column(JSON)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Lifecycle management
    expires_at = Column(DateTime)  # When file should be cleaned up
    auto_cleanup = Column(Boolean, default=True)
    
    # User and permissions
    requested_by_id = Column(Integer, nullable=False)
    access_permissions = Column(JSON, default=dict)  # Who can access this export
    
    def __repr__(self):
        return f"<ExportJob {self.job_id} - {self.status.value}>"

    @property
    def is_completed(self) -> bool:
        """Check if job is completed (successfully or failed)."""
        return self.status in [ExportStatus.COMPLETED, ExportStatus.FAILED, ExportStatus.CANCELLED]

    @property
    def is_active(self) -> bool:
        """Check if job is currently active."""
        return self.status in [ExportStatus.PENDING, ExportStatus.PROCESSING]

    @property
    def is_expired(self) -> bool:
        """Check if export file has expired."""
        if not self.expires_at:
            return False
        return datetime.now(tz=timezone.utc) > self.expires_at

    @property
    def duration(self) -> Optional[timedelta]:
        """Get job execution duration."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now(tz=timezone.utc)
        return end_time - self.started_at

    @property
    def file_size_display(self) -> str:
        """Get human-readable file size."""
        if not self.file_size:
            return "Unknown"
        
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def can_user_download(self, user_id: int, user_roles: List[str] = None) -> bool:
        """Check if user can download this export."""
        # Requestor can always download
        if self.requested_by_id == user_id:
            return True
        
        # Check access permissions
        permissions = self.access_permissions or {}
        
        # Check if user is explicitly allowed
        if user_id in permissions.get('allowed_users', []):
            return True
        
        # Check if user has required role
        if user_roles:
            allowed_roles = set(permissions.get('allowed_roles', []))
            if allowed_roles.intersection(set(user_roles)):
                return True
        
        # Check if public access is enabled
        return permissions.get('public_access', False)

    def start_processing(self):
        """Mark job as started."""
        self.status = ExportStatus.PROCESSING
        self.started_at = datetime.now(tz=timezone.utc)
        self.progress_percentage = 0
        self.progress_message = "Starting export..."

    def update_progress(self, percentage: int, message: str = "", processed: int = None):
        """Update job progress."""
        self.progress_percentage = max(0, min(100, percentage))
        if message:
            self.progress_message = message
        if processed is not None:
            self.processed_records = processed

    def complete_successfully(self, file_path: str, file_size: int = None, download_url: str = None):
        """Mark job as completed successfully."""
        self.status = ExportStatus.COMPLETED
        self.completed_at = datetime.now(tz=timezone.utc)
        self.progress_percentage = 100
        self.progress_message = "Export completed successfully"
        self.file_path = file_path
        self.file_size = file_size or (os.path.getsize(file_path) if os.path.exists(file_path) else None)
        self.download_url = download_url
        
        # Set default expiration (7 days from completion)
        if not self.expires_at:
            self.expires_at = self.completed_at + timedelta(days=7)

    def fail_with_error(self, error_message: str, error_details: Dict[str, Any] = None):
        """Mark job as failed."""
        self.status = ExportStatus.FAILED
        self.completed_at = datetime.now(tz=timezone.utc)
        self.error_message = error_message
        self.error_details = error_details or {}

    def cancel(self):
        """Cancel the job."""
        self.status = ExportStatus.CANCELLED
        self.completed_at = datetime.now(tz=timezone.utc)
        self.progress_message = "Export cancelled"

    def increment_download_count(self):
        """Increment download counter."""
        self.download_count = (self.download_count or 0) + 1

    def should_retry(self) -> bool:
        """Check if job should be retried."""
        return (self.status == ExportStatus.FAILED and 
                self.retry_count < self.max_retries)

    def retry(self):
        """Prepare job for retry."""
        if self.should_retry():
            self.retry_count += 1
            self.status = ExportStatus.PENDING
            self.error_message = None
            self.error_details = None
            self.progress_percentage = 0
            self.progress_message = f"Retrying export (attempt {self.retry_count + 1})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'job_id': self.job_id,
            'name': self.name,
            'description': self.description,
            'export_format': self.export_format.value,
            'data_source': self.data_source,
            'status': self.status.value,
            'priority': self.priority.value,
            'progress_percentage': self.progress_percentage,
            'progress_message': self.progress_message,
            'total_records': self.total_records,
            'processed_records': self.processed_records,
            'file_size': self.file_size,
            'file_size_display': self.file_size_display,
            'download_url': self.download_url,
            'download_count': self.download_count,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_completed': self.is_completed,
            'is_active': self.is_active,
            'is_expired': self.is_expired,
            'duration_seconds': self.duration.total_seconds() if self.duration else None,
            'requested_by_id': self.requested_by_id,
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'updated_at': self.changed_on.isoformat() if self.changed_on else None
        }


class ExportTemplate(AuditMixin, Model):
    """
    Export template model.
    
    Pre-configured export settings that can be reused for common
    export operations.
    """
    __tablename__ = 'export_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Template configuration
    export_format = Column(SQLEnum(ExportFormat), nullable=False)
    data_source = Column(String(255), nullable=False)
    data_source_config = Column(JSON, default=dict)
    export_options = Column(JSON, default=dict)
    default_filters = Column(JSON, default=dict)
    default_columns = Column(JSON, default=list)
    
    # Template metadata
    category = Column(String(100), default="general")
    tags = Column(JSON, default=list)
    is_public = Column(Boolean, default=False)
    is_system = Column(Boolean, default=False)
    
    # Usage tracking
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime)
    
    def __repr__(self):
        return f"<ExportTemplate {self.name}>"

    def increment_usage(self):
        """Increment usage counter when template is used."""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = datetime.now(tz=timezone.utc)

    def create_job_from_template(self, name: str, user_id: int, **overrides) -> Dict[str, Any]:
        """Create export job configuration from this template."""
        job_config = {
            'name': name,
            'description': f"Export created from template: {self.title}",
            'export_format': self.export_format,
            'data_source': self.data_source,
            'data_source_config': self.data_source_config or {},
            'export_options': self.export_options or {},
            'filters': self.default_filters or {},
            'columns': self.default_columns or [],
            'requested_by_id': user_id
        }
        
        # Apply any overrides
        job_config.update(overrides)
        return job_config

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'export_format': self.export_format.value,
            'data_source': self.data_source,
            'data_source_config': self.data_source_config or {},
            'export_options': self.export_options or {},
            'default_filters': self.default_filters or {},
            'default_columns': self.default_columns or [],
            'category': self.category,
            'tags': self.tags or [],
            'is_public': self.is_public,
            'is_system': self.is_system,
            'usage_count': self.usage_count,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'updated_at': self.changed_on.isoformat() if self.changed_on else None
        }


class ExportSchedule(AuditMixin, Model):
    """
    Export schedule model.
    
    Manages scheduled/recurring exports with cron-like scheduling.
    """
    __tablename__ = 'export_schedules'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Schedule configuration
    is_active = Column(Boolean, default=True)
    cron_expression = Column(String(100), nullable=False)  # Cron-style schedule
    timezone = Column(String(50), default="UTC")
    
    # Export configuration (similar to ExportJob)
    export_format = Column(SQLEnum(ExportFormat), nullable=False)
    data_source = Column(String(255), nullable=False)
    data_source_config = Column(JSON, default=dict)
    export_options = Column(JSON, default=dict)
    filters = Column(JSON, default=dict)
    columns = Column(JSON, default=list)
    
    # Schedule management
    next_run_at = Column(DateTime)
    last_run_at = Column(DateTime)
    run_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    max_failures = Column(Integer, default=3)  # Disable after this many failures
    
    # Notifications
    notify_on_success = Column(Boolean, default=False)
    notify_on_failure = Column(Boolean, default=True)
    notification_recipients = Column(JSON, default=list)  # Email addresses
    
    # File management
    retention_days = Column(Integer, default=7)  # How long to keep generated files
    file_name_template = Column(String(500))  # Template for generated file names
    
    # Ownership
    created_by_id = Column(Integer, nullable=False)
    
    def __repr__(self):
        return f"<ExportSchedule {self.name}>"

    @property
    def is_due(self) -> bool:
        """Check if schedule is due to run."""
        if not self.is_active or not self.next_run_at:
            return False
        return datetime.now(tz=timezone.utc) >= self.next_run_at

    @property
    def is_disabled_due_to_failures(self) -> bool:
        """Check if schedule is disabled due to too many failures."""
        return self.failure_count >= self.max_failures

    def record_success(self, next_run_time: datetime):
        """Record successful execution."""
        self.last_run_at = datetime.now(tz=timezone.utc)
        self.next_run_at = next_run_time
        self.run_count = (self.run_count or 0) + 1
        self.failure_count = 0  # Reset failure count on success

    def record_failure(self, next_run_time: datetime = None):
        """Record failed execution."""
        self.last_run_at = datetime.now(tz=timezone.utc)
        self.failure_count = (self.failure_count or 0) + 1
        
        # Disable if too many failures
        if self.failure_count >= self.max_failures:
            self.is_active = False
        elif next_run_time:
            self.next_run_at = next_run_time

    def generate_filename(self, timestamp: datetime = None) -> str:
        """Generate filename for export using template."""
        if not self.file_name_template:
            timestamp = timestamp or datetime.now(tz=timezone.utc)
            return f"{self.name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.{self.export_format.value}"
        
        # TODO: Implement template substitution
        return self.file_name_template.format(
            name=self.name,
            timestamp=(timestamp or datetime.now(tz=timezone.utc)).strftime('%Y%m%d_%H%M%S'),
            format=self.export_format.value
        )

    def create_job_from_schedule(self) -> Dict[str, Any]:
        """Create export job from this schedule."""
        return {
            'name': f"{self.name} - Scheduled Export",
            'description': f"Scheduled export: {self.description or self.name}",
            'export_format': self.export_format,
            'data_source': self.data_source,
            'data_source_config': self.data_source_config or {},
            'export_options': self.export_options or {},
            'filters': self.filters or {},
            'columns': self.columns or [],
            'requested_by_id': self.created_by_id,
            'priority': ExportPriority.NORMAL,
            'auto_cleanup': True,
            'access_permissions': {
                'allowed_users': [self.created_by_id],
                'public_access': False
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'cron_expression': self.cron_expression,
            'timezone': self.timezone,
            'export_format': self.export_format.value,
            'data_source': self.data_source,
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'run_count': self.run_count,
            'failure_count': self.failure_count,
            'max_failures': self.max_failures,
            'is_due': self.is_due,
            'is_disabled_due_to_failures': self.is_disabled_due_to_failures,
            'retention_days': self.retention_days,
            'notify_on_success': self.notify_on_success,
            'notify_on_failure': self.notify_on_failure,
            'notification_recipients': self.notification_recipients or [],
            'created_by_id': self.created_by_id,
            'created_at': self.created_on.isoformat() if self.created_on else None,
            'updated_at': self.changed_on.isoformat() if self.changed_on else None
        }