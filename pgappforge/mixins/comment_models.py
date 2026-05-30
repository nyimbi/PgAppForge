"""
Comment Models for PgAppForge

Provides database models for the commenting system used by CommentableMixin.
These models are designed to work with PgAppForge's security and audit systems.
"""

import logging
from datetime import datetime
from typing import Optional

from flask import current_user
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, event, Index
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, backref

log = logging.getLogger(__name__)


class CommentStatus:
    """Comment status constants."""
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    SPAM = 'spam'
    DELETED = 'deleted'
    
    ALL_STATUSES = [PENDING, APPROVED, REJECTED, SPAM, DELETED]


class Comment(AuditMixin, Model):
    """
    Universal comment model that can be attached to any commentable object.
    
    Uses polymorphic relationships to allow comments on any model that 
    inherits from CommentableMixin.
    """
    
    __tablename__ = 'fab_comments'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Content
    content = Column(Text, nullable=False)
    content_html = Column(Text, nullable=True)  # Processed HTML version
    
    # Status and moderation
    status = Column(String(20), default=CommentStatus.PENDING, nullable=False, index=True)
    moderation_reason = Column(String(500), nullable=True)
    
    # Threading support
    parent_comment_id = Column(Integer, ForeignKey('fab_comments.id'), nullable=True)
    thread_path = Column(String(1000), nullable=True, index=True)  # Materialized path
    depth = Column(Integer, default=0, index=True)
    
    # Polymorphic relationship to commentable objects
    commentable_type = Column(String(50), nullable=False, index=True)  # Table name
    commentable_id = Column(Integer, nullable=False, index=True)      # Record ID
    
    # User information
    @declared_attr
    def author_fk(cls):
        return Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    
    @declared_attr
    def author(cls):
        return relationship("User", foreign_keys=[cls.author_fk])
    
    # Anonymous comment support
    anonymous_name = Column(String(100), nullable=True)
    anonymous_email = Column(String(200), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    
    # Engagement metrics
    like_count = Column(Integer, default=0)
    reply_count = Column(Integer, default=0)
    
    # Threading relationships
    parent = relationship(
        'Comment',
        remote_side='Comment.id',
        backref=backref('replies', cascade='all, delete-orphan')
    )
    
    # Indexes for performance
    __table_args__ = (
        Index('ix_comments_commentable', 'commentable_type', 'commentable_id'),
        Index('ix_comments_status_created', 'status', 'created_on'),
        Index('ix_comments_thread_path', 'thread_path'),
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ip_address = self._get_client_ip()
        
        # Set author from current user if not provided
        if not self.author_fk and not self.anonymous_name:
            if current_user and hasattr(current_user, 'id'):
                self.author_fk = current_user.id
    
    @staticmethod
    def _get_client_ip() -> Optional[str]:
        """Get client IP address from request context."""
        try:
            from flask import request
            # Handle common proxy headers
            if request.headers.get('X-Forwarded-For'):
                return request.headers.get('X-Forwarded-For').split(',')[0].strip()
            elif request.headers.get('X-Real-IP'):
                return request.headers.get('X-Real-IP')
            else:
                return request.remote_addr
        except:
            return None
    
    def update_thread_path(self):
        """Update materialized path for threading."""
        if self.parent_comment_id:
            parent = Comment.query.get(self.parent_comment_id)
            if parent:
                self.thread_path = f"{parent.thread_path or ''}/{self.id}".strip('/')
                self.depth = parent.depth + 1
        else:
            self.thread_path = str(self.id)
            self.depth = 0
    
    def approve(self, moderator_id: int = None):
        """Approve this comment."""
        self.status = CommentStatus.APPROVED
        if moderator_id:
            self.changed_by_fk = moderator_id
    
    def reject(self, reason: str = None, moderator_id: int = None):
        """Reject this comment with optional reason."""
        self.status = CommentStatus.REJECTED
        self.moderation_reason = reason
        if moderator_id:
            self.changed_by_fk = moderator_id
    
    def mark_as_spam(self, moderator_id: int = None):
        """Mark comment as spam."""
        self.status = CommentStatus.SPAM
        if moderator_id:
            self.changed_by_fk = moderator_id
    
    def soft_delete(self, moderator_id: int = None):
        """Soft delete comment (preserves for moderation history)."""
        self.status = CommentStatus.DELETED
        if moderator_id:
            self.changed_by_fk = moderator_id
    
    def increment_like_count(self):
        """Increment like count atomically."""
        from sqlalchemy import update
        from pgappforge import db
        
        stmt = update(Comment).where(Comment.id == self.id).values(
            like_count=Comment.like_count + 1
        )
        db.session.execute(stmt)
        db.session.commit()
        # Refresh instance
        db.session.refresh(self)
    
    def increment_reply_count(self):
        """Increment reply count atomically."""
        from sqlalchemy import update
        from pgappforge import db
        
        stmt = update(Comment).where(Comment.id == self.id).values(
            reply_count=Comment.reply_count + 1
        )
        db.session.execute(stmt)
        db.session.commit()
        db.session.refresh(self)
    
    def get_display_name(self) -> str:
        """Get display name for comment author."""
        if self.author:
            return f"{self.author.first_name} {self.author.last_name}".strip()
        elif self.anonymous_name:
            return self.anonymous_name
        else:
            return "Anonymous"
    
    def is_editable_by(self, user) -> bool:
        """Check if user can edit this comment."""
        if not user:
            return False
        
        # Author can edit their own comments
        if self.author_fk == user.id:
            return True
        
        # Moderators can edit any comment
        if hasattr(user, 'has_permission') and user.has_permission('can_moderate_comments'):
            return True
        
        return False
    
    def is_deletable_by(self, user) -> bool:
        """Check if user can delete this comment."""
        return self.is_editable_by(user)
    
    def get_thread_comments(self, max_depth: int = None) -> list:
        """Get all comments in this thread."""
        if max_depth is None:
            max_depth = 10  # Prevent infinite depth
        
        query = Comment.query.filter(
            Comment.thread_path.startswith(self.thread_path)
        ).order_by(Comment.thread_path)
        
        if max_depth:
            query = query.filter(Comment.depth <= self.depth + max_depth)
        
        return query.all()
    
    @classmethod
    def get_for_object(cls, commentable_type: str, commentable_id: int, 
                      approved_only: bool = True, max_depth: int = None):
        """Get comments for a specific object."""
        query = cls.query.filter(
            cls.commentable_type == commentable_type,
            cls.commentable_id == commentable_id
        )
        
        if approved_only:
            query = query.filter(cls.status == CommentStatus.APPROVED)
        
        if max_depth is not None:
            query = query.filter(cls.depth <= max_depth)
        
        return query.order_by(cls.thread_path).all()
    
    @classmethod
    def create_for_object(cls, commentable_type: str, commentable_id: int,
                         content: str, user_id: int = None, parent_comment_id: int = None,
                         anonymous_name: str = None, anonymous_email: str = None,
                         auto_approve: bool = False):
        """Create a new comment for an object."""
        from pgappforge import db
        
        comment = cls(
            commentable_type=commentable_type,
            commentable_id=commentable_id,
            content=content,
            parent_comment_id=parent_comment_id,
            author_fk=user_id,
            anonymous_name=anonymous_name,
            anonymous_email=anonymous_email,
            status=CommentStatus.APPROVED if auto_approve else CommentStatus.PENDING
        )
        
        db.session.add(comment)
        db.session.flush()  # Get ID for thread path
        
        # Update thread path and reply count
        comment.update_thread_path()
        
        if parent_comment_id:
            parent = cls.query.get(parent_comment_id)
            if parent:
                parent.increment_reply_count()
        
        db.session.commit()
        return comment
    
    def __repr__(self):
        return f"<Comment(id={self.id}, author='{self.get_display_name()}', status={self.status})>"


class CommentLike(AuditMixin, Model):
    """
    Track comment likes/reactions.
    """
    
    __tablename__ = 'fab_comment_likes'
    
    id = Column(Integer, primary_key=True)
    comment_id = Column(Integer, ForeignKey('fab_comments.id'), nullable=False)
    
    @declared_attr
    def user_fk(cls):
        return Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    
    @declared_attr
    def user(cls):
        return relationship("User", foreign_keys=[cls.user_fk])
    
    # Reaction type (like, dislike, love, etc.)
    reaction_type = Column(String(20), default='like', nullable=False)
    
    # IP for anonymous reactions
    ip_address = Column(String(45), nullable=True)
    
    # Relationships
    comment = relationship('Comment', backref='likes')
    
    __table_args__ = (
        Index('ix_comment_likes_unique', 'comment_id', 'user_fk', 'ip_address', unique=True),
    )
    
    @classmethod
    def toggle_like(cls, comment_id: int, user_id: int = None, 
                   ip_address: str = None, reaction_type: str = 'like'):
        """Toggle like on a comment."""
        from pgappforge import db
        
        # Find existing like
        query = cls.query.filter(cls.comment_id == comment_id)
        
        if user_id:
            query = query.filter(cls.user_fk == user_id)
        elif ip_address:
            query = query.filter(cls.ip_address == ip_address)
        else:
            return False
        
        existing_like = query.first()
        
        if existing_like:
            # Remove existing like
            db.session.delete(existing_like)
            # Decrement counter
            comment = Comment.query.get(comment_id)
            if comment and comment.like_count > 0:
                comment.like_count -= 1
            db.session.commit()
            return False
        else:
            # Add new like
            like = cls(
                comment_id=comment_id,
                user_fk=user_id,
                ip_address=ip_address,
                reaction_type=reaction_type
            )
            db.session.add(like)
            
            # Increment counter
            comment = Comment.query.get(comment_id)
            if comment:
                comment.like_count += 1
            
            db.session.commit()
            return True


# Event listeners for maintaining data integrity
@event.listens_for(Comment, 'after_insert')
def update_thread_path_after_insert(mapper, connection, target):
    """Update thread path after comment is inserted."""
    if target.id:  # Ensure we have an ID
        target.update_thread_path()


@event.listens_for(Comment, 'before_delete')
def handle_comment_deletion(mapper, connection, target):
    """Handle cascade when comment is deleted."""
    # Update reply counts of parent
    if target.parent_comment_id:
        parent = Comment.query.get(target.parent_comment_id)
        if parent and parent.reply_count > 0:
            parent.reply_count -= 1


__all__ = [
    'Comment',
    'CommentLike',
    'CommentStatus'
]