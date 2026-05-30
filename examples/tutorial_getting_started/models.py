"""
Database Models for PgAppForge Getting Started Tutorial

This module defines the data models for the task management application,
including Task and TaskCategory models with AI and collaborative features.
"""

from datetime import datetime, date
from pgappforge import Model
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, 
    ForeignKey, Date, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
import enum


class Priority(enum.Enum):
    """Task priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Status(enum.Enum):
    """Task status options."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class TaskCategory(Model):
    """
    Task categories for organizing tasks.
    
    This model represents different categories that tasks can be assigned to,
    with color coding for visual organization.
    """
    __tablename__ = 'task_category'

    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Basic information
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    color = Column(String(7), default='#007bff')  # Hex color code
    
    # Settings
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    def __repr__(self):
        return self.name

    @property
    def task_count(self):
        """Return the number of tasks in this category."""
        return len(self.tasks) if self.tasks else 0

    @property
    def completed_task_count(self):
        """Return the number of completed tasks in this category."""
        if not self.tasks:
            return 0
        return len([task for task in self.tasks if task.completed])

    @property
    def completion_rate(self):
        """Return the completion rate as a percentage."""
        total = self.task_count
        if total == 0:
            return 0
        return (self.completed_task_count / total) * 100

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'color': self.color,
            'is_active': self.is_active,
            'task_count': self.task_count,
            'completion_rate': self.completion_rate
        }


class Task(Model):
    """
    Main task model with AI and collaborative features.
    
    This model represents individual tasks in the system with support for
    AI-generated content, collaborative editing, and comprehensive tracking.
    """
    __tablename__ = 'task'

    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Basic task information
    title = Column(String(200), nullable=False)
    description = Column(Text)
    
    # AI-generated content
    ai_summary = Column(Text)
    ai_tags = Column(String(500))  # Comma-separated tags
    ai_insights = Column(Text)     # AI-generated insights
    
    # Task management
    priority = Column(SQLEnum(Priority), default=Priority.MEDIUM)
    status = Column(SQLEnum(Status), default=Status.PENDING)
    
    # Dates
    due_date = Column(Date)
    start_date = Column(Date)
    completed_date = Column(DateTime)
    
    # Progress tracking
    completed = Column(Boolean, default=False)
    progress_percentage = Column(Integer, default=0)  # 0-100
    
    # Time tracking
    estimated_hours = Column(Integer)
    actual_hours = Column(Integer)
    
    # Relationships
    category_id = Column(Integer, ForeignKey('task_category.id'))
    category = relationship('TaskCategory', backref='tasks')
    
    
    # Additional metadata
    tags = Column(String(500))  # User-defined tags
    notes = Column(Text)        # Additional notes
    external_id = Column(String(100))  # For integration with external systems

    def __repr__(self):
        return f"{self.title} ({self.status.value if self.status else 'unknown'})"

    @property
    def priority_badge_class(self):
        """Return Bootstrap badge class for priority."""
        priority_classes = {
            Priority.LOW: 'badge-success',
            Priority.MEDIUM: 'badge-primary',
            Priority.HIGH: 'badge-warning',
            Priority.URGENT: 'badge-danger'
        }
        return priority_classes.get(self.priority, 'badge-secondary')

    @property
    def status_badge_class(self):
        """Return Bootstrap badge class for status."""
        status_classes = {
            Status.PENDING: 'badge-secondary',
            Status.IN_PROGRESS: 'badge-info',
            Status.COMPLETED: 'badge-success',
            Status.CANCELLED: 'badge-dark',
            Status.ON_HOLD: 'badge-warning'
        }
        return status_classes.get(self.status, 'badge-secondary')

    @property
    def is_overdue(self):
        """Check if task is overdue."""
        if not self.due_date or self.completed:
            return False
        return date.today() > self.due_date

    @property
    def days_until_due(self):
        """Calculate days until due date."""
        if not self.due_date:
            return None
        delta = self.due_date - date.today()
        return delta.days

    @property
    def ai_tags_list(self):
        """Return AI tags as a list."""
        if not self.ai_tags:
            return []
        return [tag.strip() for tag in self.ai_tags.split(',') if tag.strip()]

    @property
    def user_tags_list(self):
        """Return user tags as a list."""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]

    @property
    def all_tags_list(self):
        """Return all tags (AI + user) as a list."""
        return self.ai_tags_list + self.user_tags_list

    def mark_completed(self):
        """Mark task as completed."""
        self.completed = True
        self.status = Status.COMPLETED
        self.completed_date = datetime.utcnow()
        self.progress_percentage = 100

    def mark_in_progress(self):
        """Mark task as in progress."""
        self.completed = False
        self.status = Status.IN_PROGRESS
        if not self.start_date:
            self.start_date = date.today()

    def update_progress(self, percentage):
        """Update task progress percentage."""
        self.progress_percentage = max(0, min(100, percentage))
        if percentage >= 100:
            self.mark_completed()
        elif percentage > 0 and self.status == Status.PENDING:
            self.mark_in_progress()

    def add_ai_insight(self, insight):
        """Add an AI-generated insight."""
        if self.ai_insights:
            self.ai_insights += f"\n\n---\n\n{insight}"
        else:
            self.ai_insights = insight

    def to_dict(self, include_ai=True):
        """Convert to dictionary for API responses."""
        result = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'priority': self.priority.value if self.priority else None,
            'status': self.status.value if self.status else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'completed': self.completed,
            'progress_percentage': self.progress_percentage,
            'category': self.category.name if self.category else None,
            'assigned_to': self.assigned_to.username if self.assigned_to else None,
            'tags': self.user_tags_list,
            'is_overdue': self.is_overdue,
            'days_until_due': self.days_until_due,
            'created_on': self.created_on.isoformat() if self.created_on else None,
            'changed_on': self.changed_on.isoformat() if self.changed_on else None
        }
        
        if include_ai:
            result.update({
                'ai_summary': self.ai_summary,
                'ai_tags': self.ai_tags_list,
                'ai_insights': self.ai_insights
            })
            
        return result

    @classmethod
    def get_priority_choices(cls):
        """Get priority choices for forms."""
        return [(p.value, p.value.replace('_', ' ').title()) for p in Priority]

    @classmethod
    def get_status_choices(cls):
        """Get status choices for forms."""
        return [(s.value, s.value.replace('_', ' ').title()) for s in Status]

    @classmethod
    def get_statistics(cls, session):
        """Get task statistics."""
        from sqlalchemy import func
        
        # Basic counts
        total_tasks = session.query(cls).count()
        completed_tasks = session.query(cls).filter(cls.completed == True).count()
        overdue_tasks = session.query(cls).filter(
            cls.due_date < date.today(),
            cls.completed == False
        ).count()
        
        # Priority distribution
        priority_stats = session.query(
            cls.priority, func.count(cls.id)
        ).group_by(cls.priority).all()
        
        # Status distribution
        status_stats = session.query(
            cls.status, func.count(cls.id)
        ).group_by(cls.status).all()
        
        return {
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'overdue_tasks': overdue_tasks,
            'completion_rate': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            'priority_distribution': {p.value: count for p, count in priority_stats},
            'status_distribution': {s.value: count for s, count in status_stats}
        }


class TaskHistory(Model):
    """
    Track changes to tasks for audit and collaboration.
    
    This model keeps a history of all changes made to tasks,
    useful for collaboration and audit purposes.
    """
    __tablename__ = 'task_history'

    id = Column(Integer, primary_key=True)
    
    # Task reference
    task_id = Column(Integer, ForeignKey('task.id'), nullable=False)
    task = relationship('Task', backref='history')
    
    # Change information
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    change_type = Column(String(50))  # 'create', 'update', 'delete'
    
    # Change context
    change_reason = Column(String(200))
    user_agent = Column(String(500))
    ip_address = Column(String(45))

    def __repr__(self):
        return f"TaskHistory(task_id={self.task_id}, field={self.field_name}, type={self.change_type})"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'field_name': self.field_name,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'change_type': self.change_type,
            'change_reason': self.change_reason,
            'changed_by': self.changed_by.username if self.changed_by else None,
            'changed_on': self.changed_on.isoformat() if self.changed_on else None
        }