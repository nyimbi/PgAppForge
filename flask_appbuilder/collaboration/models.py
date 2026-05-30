"""
Database Models for Real-Time Collaboration

Defines the database schema for collaboration sessions, events, conflicts,
and change tracking with proper Flask-AppBuilder naming conventions.
"""

import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from flask_appbuilder import Model

# Use Flask-AppBuilder's Model base class for consistency
class CollaborationSession(Model):
    """
    Collaboration sessions track multi-user editing sessions for specific records.
    
    Each session represents a collaborative editing context where multiple users
    can work on the same model record simultaneously.
    """
    __tablename__ = 'ab_collaboration_sessions'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)
    model_name = Column(String(100), nullable=False, index=True)
    record_id = Column(String(100), index=True)  # NULL for new records
    created_by = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, 
                       onupdate=datetime.datetime.utcnow, nullable=False)
    status = Column(String(20), default='active', nullable=False)  # active, inactive, archived
    settings = Column(JSONB, default=lambda: {})  # Session-specific settings
    participants = Column(JSONB, default=lambda: [])  # List of participant user IDs
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    events = relationship("CollaborationEvent", back_populates="session", lazy="dynamic")
    conflicts = relationship("CollaborationConflict", back_populates="session", lazy="dynamic")
    
    def __repr__(self):
        return f'<CollaborationSession {self.session_id}>'
    
    def add_participant(self, user_id: int):
        """Add participant to session"""
        if not isinstance(self.participants, list):
            self.participants = []
        if user_id not in self.participants:
            self.participants.append(user_id)
    
    def remove_participant(self, user_id: int):
        """Remove participant from session"""
        if isinstance(self.participants, list) and user_id in self.participants:
            self.participants.remove(user_id)
    
    def is_participant(self, user_id: int) -> bool:
        """Check if user is participant in session"""
        return isinstance(self.participants, list) and user_id in self.participants


class CollaborationEvent(Model):
    """
    Real-time collaboration events log all changes and interactions.
    
    This provides a complete audit trail and enables conflict resolution
    and change synchronization across participants.
    """
    __tablename__ = 'ab_collaboration_events'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), ForeignKey('ab_collaboration_sessions.session_id'), 
                       nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # field_change, cursor_move, comment, etc.
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    model_name = Column(String(100), nullable=False)
    record_id = Column(String(100))
    field_name = Column(String(100))
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    event_metadata = Column(JSONB, default=lambda: {})  # Additional event data
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    processed_at = Column(DateTime)  # When event was fully processed
    
    # Relationships
    session = relationship("CollaborationSession", back_populates="events")
    user = relationship("User", foreign_keys=[user_id])
    
    def __repr__(self):
        return f'<CollaborationEvent {self.event_type} by {self.user_id}>'


class CollaborationConflict(Model):
    """
    Conflict resolution log for concurrent editing conflicts.
    
    Tracks when conflicts occur, how they were resolved, and provides
    audit trail for conflict resolution decisions.
    """
    __tablename__ = 'ab_collaboration_conflicts'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), ForeignKey('ab_collaboration_sessions.session_id'), 
                       nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    conflict_type = Column(String(50), nullable=False)  # text, json, list, etc.
    local_change = Column(JSONB, nullable=False)  # Local user's change
    remote_change = Column(JSONB, nullable=False)  # Remote user's change
    resolution = Column(JSONB)  # Final resolved value
    resolution_method = Column(String(50))  # auto, manual, operational_transform, etc.
    resolved_by = Column(Integer, ForeignKey('ab_user.id'))  # NULL for auto-resolved
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime)
    
    # Relationships  
    session = relationship("CollaborationSession", back_populates="conflicts")
    resolver = relationship("User", foreign_keys=[resolved_by])
    
    def __repr__(self):
        return f'<CollaborationConflict {self.conflict_type} in {self.field_name}>'


class ModelChangeLog(Model):
    """
    Model-level change tracking for collaboration and audit purposes.
    
    Tracks all changes to collaborative models for real-time sync,
    conflict detection, and audit trails.
    """
    __tablename__ = 'ab_model_change_log'
    
    id = Column(Integer, primary_key=True)
    model_name = Column(String(100), nullable=False, index=True)
    record_id = Column(String(100), nullable=False, index=True)
    field_name = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)
    change_type = Column(String(20), nullable=False)  # INSERT, UPDATE, DELETE
    user_id = Column(Integer, ForeignKey('ab_user.id'))
    session_id = Column(String(36), ForeignKey('ab_collaboration_sessions.session_id'))
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    session = relationship("CollaborationSession", foreign_keys=[session_id])
    
    def __repr__(self):
        return f'<ModelChangeLog {self.change_type} {self.model_name}:{self.record_id}>'


class CollaborationPresence(Model):
    """
    Real-time presence tracking for active collaboration participants.
    
    Tracks who is currently active in collaboration sessions for
    presence indicators and live cursor positioning.
    """
    __tablename__ = 'ab_collaboration_presence'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), ForeignKey('ab_collaboration_sessions.session_id'), 
                       nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    status = Column(String(20), default='active')  # active, away, typing, etc.
    current_field = Column(String(100))  # Field user is currently focused on
    cursor_position = Column(Integer)  # Cursor position within field
    last_activity = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    presence_metadata = Column(JSONB, default=lambda: {})  # Additional presence data
    
    # Relationships
    session = relationship("CollaborationSession", foreign_keys=[session_id])
    user = relationship("User", foreign_keys=[user_id])
    
    def __repr__(self):
        return f'<CollaborationPresence {self.user_id} in {self.session_id}>'
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.datetime.now(datetime.timezone.utc)


class CollaborationComment(Model):
    """
    Comments and annotations on collaborative records and fields.
    
    Enables threaded discussions and annotations within collaborative
    editing sessions.
    """
    __tablename__ = 'ab_collaboration_comments'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(36), ForeignKey('ab_collaboration_sessions.session_id'), 
                       nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    field_name = Column(String(100))  # NULL for general record comments
    content = Column(Text, nullable=False)
    parent_comment_id = Column(Integer, ForeignKey('ab_collaboration_comments.id'))  # For threading
    mentions = Column(JSONB, default=lambda: [])  # List of mentioned user IDs
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, 
                       onupdate=datetime.datetime.utcnow, nullable=False)
    
    # Relationships
    session = relationship("CollaborationSession", foreign_keys=[session_id])
    user = relationship("User", foreign_keys=[user_id])
    parent_comment = relationship("CollaborationComment", remote_side=[id])
    replies = relationship("CollaborationComment", back_populates="parent_comment")
    
    def __repr__(self):
        return f'<CollaborationComment by {self.user_id}>'