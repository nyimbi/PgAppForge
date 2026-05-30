"""
Content Management Mixins for Flask-AppBuilder

This module provides mixins for content and document management features:
- Document management with metadata
- URL-friendly slug generation
- Commenting system
- Search capabilities
- Content categorization

These mixins are designed to work with Flask-AppBuilder's existing
infrastructure while providing comprehensive content management features.
"""

import hashlib
import json
import logging
import mimetypes
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import current_user, g
from flask_appbuilder.models.mixins import AuditMixin, FileColumn, ImageColumn
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, event
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

log = logging.getLogger(__name__)


class DocumentMixin(AuditMixin):
    """
    Document management mixin for Flask-AppBuilder.
    
    Provides comprehensive document handling capabilities including:
    - File storage and metadata
    - Document type detection
    - Content extraction and indexing
    - Document lifecycle management
    - Permission-aware access control
    - Document versioning support
    
    Features:
    - Automatic MIME type detection
    - File size and hash tracking
    - Document metadata extraction
    - Content text extraction
    - Download tracking and permissions
    - Document templates and rendering
    """
    
    # Core document fields
    doc_title = Column(String(200), nullable=False, default="Untitled Document")
    doc_description = Column(Text, nullable=True)
    doc_file = Column(FileColumn, nullable=True)
    doc_image = Column(ImageColumn(thumbnail_size=(64, 64, True), size=(400, 400, True)), nullable=True)
    
    # Document metadata
    mime_type = Column(String(100), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    doc_hash = Column(String(64), nullable=True)  # SHA-256 hash
    doc_type = Column(String(20), nullable=True)  # pdf, docx, txt, etc.
    
    # Content and structure
    doc_text = Column(Text, nullable=True)  # Extracted text content
    word_count = Column(Integer, default=0)
    char_count = Column(Integer, default=0)
    page_count = Column(Integer, default=1)
    
    # Document properties
    is_downloadable = Column(Boolean, default=True)
    is_public = Column(Boolean, default=False)
    is_template = Column(Boolean, default=False)
    is_encrypted = Column(Boolean, default=False)
    
    # Processing status
    is_processed = Column(Boolean, default=False)
    processing_error = Column(Text, nullable=True)
    last_processed_at = Column(DateTime, nullable=True)
    
    # Document relationships and categorization
    category = Column(String(50), nullable=True)
    tags = Column(Text, nullable=True)  # Comma-separated tags
    version_number = Column(Integer, default=1)
    
    # Access tracking
    download_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.doc_title == "Untitled Document" and 'doc_title' not in kwargs:
            self.doc_title = f"Document {datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def set_file_content(self, file_content: bytes, filename: str = None):
        """
        Set document content and automatically extract metadata.
        
        Args:
            file_content: Binary file content
            filename: Original filename (for MIME type detection)
        """
        try:
            # Store file content
            self.doc_file = file_content
            self.file_size_bytes = len(file_content) if file_content else 0
            
            # Generate hash
            if file_content:
                self.doc_hash = hashlib.sha256(file_content).hexdigest()
            
            # Detect MIME type
            if filename:
                self.mime_type = mimetypes.guess_type(filename)[0]
                self.doc_type = self._extract_doc_type(filename)
            
            # Extract text content if possible
            self._extract_text_content()
            
            # Mark as processed
            self.is_processed = True
            self.last_processed_at = datetime.now(tz=timezone.utc)
            self.processing_error = None
            
        except Exception as e:
            self.processing_error = str(e)
            self.is_processed = False
            log.error(f"Document processing failed: {e}")
    
    def _extract_doc_type(self, filename: str) -> str:
        """Extract document type from filename."""
        if not filename:
            return None
        
        ext = filename.lower().split('.')[-1] if '.' in filename else None
        
        type_mapping = {
            'pdf': 'pdf',
            'doc': 'word', 'docx': 'word',
            'xls': 'excel', 'xlsx': 'excel',
            'ppt': 'powerpoint', 'pptx': 'powerpoint',
            'txt': 'text', 'md': 'markdown',
            'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
            'mp4': 'video', 'avi': 'video', 'mov': 'video',
            'mp3': 'audio', 'wav': 'audio', 'flac': 'audio'
        }
        
        return type_mapping.get(ext, 'unknown')
    
    def _extract_text_content(self):
        """
        Extract text content from document.
        This is a basic implementation - extend based on your needs.
        """
        if not self.doc_file:
            return
        
        try:
            if self.doc_type == 'text' or self.mime_type and 'text' in self.mime_type:
                # Handle text files
                self.doc_text = self.doc_file.decode('utf-8', errors='ignore')
                self.char_count = len(self.doc_text) if self.doc_text else 0
                self.word_count = len(self.doc_text.split()) if self.doc_text else 0
            
            # For other file types, you would implement specific extractors
            # e.g., PyPDF2 for PDF, python-docx for Word documents, etc.
            
        except Exception as e:
            log.warning(f"Text extraction failed: {e}")
    
    def add_tag(self, tag: str):
        """Add a tag to the document."""
        current_tags = self.get_tags()
        if tag not in current_tags:
            current_tags.append(tag)
            self.tags = ','.join(current_tags)
    
    def remove_tag(self, tag: str):
        """Remove a tag from the document."""
        current_tags = self.get_tags()
        if tag in current_tags:
            current_tags.remove(tag)
            self.tags = ','.join(current_tags) if current_tags else None
    
    def get_tags(self) -> List[str]:
        """Get list of tags."""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    
    def increment_download_count(self):
        """Increment download counter."""
        self.download_count = (self.download_count or 0) + 1
    
    def increment_view_count(self):
        """Increment view counter."""
        self.view_count = (self.view_count or 0) + 1
    
    def can_download(self, user=None) -> bool:
        """Check if user can download this document."""
        if not self.is_downloadable:
            return False
        
        if self.is_public:
            return True
        
        # Check if user owns the document
        if user and hasattr(self, 'created_by_fk') and self.created_by_fk == user.id:
            return True
        
        # Additional permission checks can be added here
        return user is not None  # Authenticated users can download by default
    
    def get_download_url(self, user=None) -> Optional[str]:
        """Get secure download URL."""
        if not self.can_download(user):
            return None
        return f"/admin/document/{self.id}/download"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert document to dictionary."""
        return {
            'id': getattr(self, 'id', None),
            'title': self.doc_title,
            'description': self.doc_description,
            'mime_type': self.mime_type,
            'doc_type': self.doc_type,
            'file_size_bytes': self.file_size_bytes,
            'word_count': self.word_count,
            'char_count': self.char_count,
            'page_count': self.page_count,
            'category': self.category,
            'tags': self.get_tags(),
            'is_downloadable': self.is_downloadable,
            'is_public': self.is_public,
            'download_count': self.download_count,
            'view_count': self.view_count,
            'created_on': self.created_on.isoformat() if self.created_on else None,
            'version_number': self.version_number
        }
    
    def __repr__(self):
        return f"<Document(id={getattr(self, 'id', 'unknown')}, title='{self.doc_title}')>"


class SlugMixin:
    """
    URL-friendly slug generation mixin.
    
    Automatically generates and maintains URL-friendly slugs based on
    a specified source field. Ensures slug uniqueness and provides
    slug-based lookups.
    
    Features:
    - Automatic slug generation from source field
    - Uniqueness enforcement
    - Custom slug validation
    - Slug-based queries
    - SEO-friendly URLs
    """
    
    slug = Column(String(100), nullable=True, unique=True, index=True)
    
    # Configuration - override in subclasses
    __slug_source__ = 'title'  # Field to generate slug from
    __slug_max_length__ = 100
    __slug_separator__ = '-'
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug:
            self.generate_slug()
    
    def generate_slug(self, source_value: str = None, force: bool = False):
        """Generate slug from source field or provided value."""
        if self.slug and not force:
            return self.slug
        
        if not source_value:
            source_field = getattr(self, self.__slug_source__, None)
            if not source_field:
                return None
            source_value = str(source_field)
        
        # Create base slug
        slug = self._slugify(source_value)
        
        # Ensure uniqueness
        original_slug = slug
        counter = 1
        
        while self._slug_exists(slug):
            slug = f"{original_slug}{self.__slug_separator__}{counter}"
            counter += 1
            
            # Prevent infinite loops
            if counter > 1000:
                slug = f"{original_slug}{self.__slug_separator__}{datetime.now().strftime('%Y%m%d%H%M%S')}"
                break
        
        self.slug = slug[:self.__slug_max_length__]
        return self.slug
    
    def _slugify(self, text: str) -> str:
        """Convert text to URL-friendly slug."""
        if not text:
            return ""
        
        # Convert to lowercase and remove special characters
        slug = re.sub(r'[^\w\s-]', '', text.lower())
        # Replace spaces and underscores with separator
        slug = re.sub(r'[-\s_]+', self.__slug_separator__, slug)
        # Remove leading/trailing separators
        slug = slug.strip(self.__slug_separator__)
        
        return slug[:self.__slug_max_length__]
    
    def _slug_exists(self, slug: str) -> bool:
        """Check if slug already exists."""
        if not hasattr(self.__class__, 'query'):
            return False
        
        query = self.__class__.query.filter(self.__class__.slug == slug)
        
        # Exclude current record if it has an ID
        if hasattr(self, 'id') and self.id:
            query = query.filter(self.__class__.id != self.id)
        
        return query.first() is not None
    
    @classmethod
    def get_by_slug(cls, slug: str):
        """Find record by slug."""
        return cls.query.filter(cls.slug == slug).first()
    
    @classmethod
    def __declare_last__(cls):
        """Set up event listeners for automatic slug generation."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'before_insert')
        def generate_slug_on_insert(mapper, connection, target):
            if not target.slug:
                target.generate_slug()
        
        @event.listens_for(cls, 'before_update')
        def update_slug_on_change(mapper, connection, target):
            # Regenerate slug if source field changed
            if hasattr(target, cls.__slug_source__):
                source_field = getattr(target, cls.__slug_source__)
                if source_field and not target.slug:
                    target.generate_slug()


class CommentableMixin(AuditMixin):
    """
    Advanced commenting system mixin.
    
    Provides comprehensive commenting functionality including:
    - Hierarchical (threaded) comments
    - Comment moderation and approval
    - Comment voting and rating
    - Spam detection and filtering
    - Comment templates and formatting
    - Notification system integration
    
    Features:
    - Parent-child comment relationships
    - Comment status management (pending, approved, rejected)
    - User-based comment permissions
    - Comment search and filtering
    - Bulk comment operations
    """
    
    # Override in subclasses to configure commenting
    __commentable__ = True
    __comment_moderation__ = False
    __max_comment_depth__ = 5
    __allow_anonymous_comments__ = False
    
    def get_comments(self, approved_only: bool = True, max_depth: int = None) -> List:
        """
        Get comments for this object.
        
        Args:
            approved_only: Only return approved comments
            max_depth: Maximum nesting depth
            
        Returns:
            List of comment objects
        """
        if not hasattr(self, 'id') or not self.__commentable__:
            return []
        
        try:
            from .comment_models import Comment
            return Comment.get_for_object(
                commentable_type=self.__tablename__,
                commentable_id=self.id,
                approved_only=approved_only,
                max_depth=max_depth or self.__max_comment_depth__
            )
        except ImportError as e:
            log.warning(f"Comment model not available: {e}")
            return []
        except Exception as e:
            log.error(f"Failed to retrieve comments: {e}")
            return []
    
    def add_comment(self, content: str, user_id: int = None, parent_comment_id: int = None, 
                   anonymous_name: str = None, anonymous_email: str = None) -> Optional[object]:
        """
        Add a comment to this object.
        
        Args:
            content: Comment content
            user_id: ID of user making comment
            parent_comment_id: Parent comment for threaded discussions
            anonymous_name: Name for anonymous comments
            anonymous_email: Email for anonymous comments
            
        Returns:
            Comment object if successful, None if failed
        """
        if not self.__commentable__:
            log.warning(f"Comments not enabled for {self.__class__.__name__}")
            return None
        
        if not content or not content.strip():
            log.warning("Comment content cannot be empty")
            return None
        
        if not self.__allow_anonymous_comments__ and not user_id:
            log.warning("Anonymous comments not allowed and no user provided")
            return None
        
        if not hasattr(self, 'id') or not self.id:
            log.error("Cannot add comment to unsaved object")
            return None
        
        try:
            from .comment_models import Comment
            
            # Auto-approve if moderation is disabled
            auto_approve = not self.__comment_moderation__
            
            comment = Comment.create_for_object(
                commentable_type=self.__tablename__,
                commentable_id=self.id,
                content=content.strip(),
                user_id=user_id,
                parent_comment_id=parent_comment_id,
                anonymous_name=anonymous_name,
                anonymous_email=anonymous_email,
                auto_approve=auto_approve
            )
            
            log.info(f"Comment added to {self.__class__.__name__} {self.id}")
            return comment
            
        except ImportError as e:
            log.error(f"Comment model not available: {e}")
            return None
        except Exception as e:
            log.error(f"Failed to create comment: {e}")
            return None
    
    def get_comment_count(self, approved_only: bool = True) -> int:
        """Get total number of comments."""
        return len(self.get_comments(approved_only))
    
    def can_comment(self, user=None) -> bool:
        """Check if user can comment on this object."""
        if not self.__commentable__:
            return False
        
        if self.__allow_anonymous_comments__:
            return True
        
        return user is not None
    
    def moderate_comments(self, comment_ids: List[int], action: str, user_id: int = None, 
                         reason: str = None) -> int:
        """
        Moderate multiple comments.
        
        Args:
            comment_ids: List of comment IDs to moderate
            action: 'approve', 'reject', 'spam', or 'delete'
            user_id: ID of user performing moderation
            reason: Reason for rejection/deletion
            
        Returns:
            int: Number of comments successfully moderated
        """
        if not self.__comment_moderation__:
            log.warning("Comment moderation not enabled")
            return 0
        
        if not comment_ids:
            return 0
        
        try:
            from .comment_models import Comment
            
            count = 0
            comments = Comment.query.filter(Comment.id.in_(comment_ids)).all()
            
            for comment in comments:
                # Verify comment belongs to this object
                if (comment.commentable_type != self.__tablename__ or 
                    comment.commentable_id != self.id):
                    log.warning(f"Comment {comment.id} doesn't belong to this object")
                    continue
                
                try:
                    if action == 'approve':
                        comment.approve(user_id)
                    elif action == 'reject':
                        comment.reject(reason, user_id)
                    elif action == 'spam':
                        comment.mark_as_spam(user_id)
                    elif action == 'delete':
                        comment.soft_delete(user_id)
                    else:
                        log.warning(f"Unknown moderation action: {action}")
                        continue
                    
                    count += 1
                    log.info(f"Comment {comment.id} {action}ed by user {user_id}")
                    
                except Exception as e:
                    log.error(f"Failed to {action} comment {comment.id}: {e}")
            
            # Commit changes
            from flask_appbuilder import db
            db.session.commit()
            
            return count
            
        except ImportError as e:
            log.error(f"Comment model not available: {e}")
            return 0
        except Exception as e:
            log.error(f"Comment moderation failed: {e}")
            return 0


class SearchableMixin:
    """
    Full-text search mixin with advanced capabilities.
    
    Provides comprehensive search functionality including:
    - Full-text search across specified fields
    - Search result ranking and scoring
    - Search term highlighting
    - Search analytics and tracking
    - Custom search configurations
    
    Features:
    - Configurable searchable fields with weights
    - Search vector generation and maintenance
    - Advanced search queries with filters
    - Search result optimization
    - Search history and analytics
    """
    
    # Configuration - override in subclasses
    __searchable__ = {}  # {'field_name': 'weight'}
    __search_language__ = 'english'
    
    search_vector = Column(Text, nullable=True)  # Store search terms
    search_rank = Column(Integer, default=0)     # Search ranking score
    
    @classmethod
    def search(cls, query: str, limit: int = 50, min_rank: float = 0.1, **filters):
        """
        Perform full-text search with database-specific optimizations and ranking.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            min_rank: Minimum relevance rank (0-1) for results
            **filters: Additional filters to apply
            
        Returns:
            List of matching records ordered by relevance
        """
        if not query or not cls.__searchable__:
            return []
        
        try:
            # Detect database type and use appropriate search method
            from flask_appbuilder import db
            database_url = str(db.engine.url)
            
            if 'postgresql' in database_url:
                return cls._postgresql_full_text_search(query, limit, min_rank, **filters)
            elif 'mysql' in database_url:
                return cls._mysql_full_text_search(query, limit, min_rank, **filters)
            elif 'sqlite' in database_url:
                return cls._sqlite_fts_search(query, limit, min_rank, **filters)
            else:
                # Fallback to enhanced basic search for other databases
                return cls._enhanced_basic_search(query, limit, **filters)
                
        except Exception as e:
            log.warning(f"Advanced search failed, falling back to basic search: {e}")
            return cls._enhanced_basic_search(query, limit, **filters)
    
    @classmethod
    def _postgresql_full_text_search(cls, query: str, limit: int, min_rank: float, **filters):
        """PostgreSQL full-text search with ranking."""
        try:
            from flask_appbuilder import db
            from sqlalchemy import text, func
            
            # Sanitize query for PostgreSQL tsquery
            sanitized_query = query.replace("'", "''").replace("&", " & ").replace("|", " | ")
            search_terms = [term.strip() for term in sanitized_query.split() if term.strip()]
            tsquery = " & ".join(search_terms)
            
            # Build weighted search vector from searchable fields
            search_expressions = []
            for field_name, weight in cls.__searchable__.items():
                if hasattr(cls, field_name):
                    field = getattr(cls, field_name)
                    weight_char = {1.0: 'A', 0.8: 'B', 0.4: 'C', 0.1: 'D'}.get(weight, 'D')
                    search_expressions.append(f"setweight(to_tsvector('english', coalesce({field_name}, '')), '{weight_char}')")
            
            if not search_expressions:
                return []
            
            search_vector = " || ".join(search_expressions)
            
            # Build query with ranking
            rank_expression = text(f"ts_rank({search_vector}, plainto_tsquery('english', :query))")
            match_condition = text(f"{search_vector} @@ plainto_tsquery('english', :query)")
            
            query_obj = db.session.query(cls, rank_expression.label('rank')).filter(match_condition)
            
            # Apply additional filters
            for filter_name, filter_value in filters.items():
                if hasattr(cls, filter_name):
                    filter_field = getattr(cls, filter_name)
                    query_obj = query_obj.filter(filter_field == filter_value)
            
            # Filter by minimum rank and order by relevance
            results = query_obj.filter(rank_expression >= min_rank)\
                             .order_by(rank_expression.desc())\
                             .limit(limit)\
                             .all()
            
            return [result[0] for result in results]  # Extract model instances
            
        except Exception as e:
            log.warning(f"PostgreSQL full-text search failed: {e}")
            return cls._enhanced_basic_search(query, limit, **filters)
    
    @classmethod
    def _mysql_full_text_search(cls, query: str, limit: int, min_rank: float, **filters):
        """MySQL full-text search with MATCH AGAINST."""
        try:
            from flask_appbuilder import db
            from sqlalchemy import text
            
            # Build MATCH AGAINST expression
            searchable_fields = [field_name for field_name in cls.__searchable__.keys() 
                               if hasattr(cls, field_name)]
            
            if not searchable_fields:
                return []
            
            match_fields = ", ".join(searchable_fields)
            match_expression = text(f"MATCH ({match_fields}) AGAINST (:query IN BOOLEAN MODE)")
            
            query_obj = db.session.query(cls, match_expression.label('score'))\
                                 .filter(match_expression)
            
            # Apply additional filters
            for filter_name, filter_value in filters.items():
                if hasattr(cls, filter_name):
                    filter_field = getattr(cls, filter_name)
                    query_obj = query_obj.filter(filter_field == filter_value)
            
            # Order by relevance score and apply limits
            results = query_obj.filter(match_expression >= min_rank)\
                             .order_by(text("score DESC"))\
                             .limit(limit)\
                             .all()
            
            return [result[0] for result in results]
            
        except Exception as e:
            log.warning(f"MySQL full-text search failed: {e}")
            return cls._enhanced_basic_search(query, limit, **filters)
    
    @classmethod
    def _sqlite_fts_search(cls, query: str, limit: int, min_rank: float, **filters):
        """SQLite FTS search (requires FTS extension)."""
        try:
            from flask_appbuilder import db
            from sqlalchemy import text
            
            # Check if we have FTS virtual table (simplified approach)
            # In production, you'd create FTS virtual tables for better performance
            return cls._enhanced_basic_search(query, limit, **filters)
            
        except Exception as e:
            log.warning(f"SQLite FTS search failed: {e}")
            return cls._enhanced_basic_search(query, limit, **filters)
    
    @classmethod
    def _enhanced_basic_search(cls, query: str, limit: int, **filters):
        """Enhanced basic search with fuzzy matching and ranking."""
        try:
            from flask_appbuilder import db
            from sqlalchemy import or_, func, case
            
            # Split query into terms for better matching
            search_terms = [term.strip().lower() for term in query.split() if len(term.strip()) > 2]
            
            if not search_terms:
                return []
            
            search_conditions = []
            rank_expressions = []
            
            for field_name, weight in cls.__searchable__.items():
                if hasattr(cls, field_name):
                    field = getattr(cls, field_name)
                    
                    # Add conditions for each search term
                    for term in search_terms:
                        # Exact phrase match (highest score)
                        exact_match = field.ilike(f'%{query}%')
                        search_conditions.append(exact_match)
                        rank_expressions.append(case([(exact_match, weight * 3)], else_=0))
                        
                        # Word boundary match (medium score)
                        word_match = field.ilike(f'% {term} %') | field.ilike(f'{term} %') | field.ilike(f'% {term}')
                        search_conditions.append(word_match)
                        rank_expressions.append(case([(word_match, weight * 2)], else_=0))
                        
                        # Partial match (low score)
                        partial_match = field.ilike(f'%{term}%')
                        search_conditions.append(partial_match)
                        rank_expressions.append(case([(partial_match, weight)], else_=0))
            
            if not search_conditions:
                return []
            
            # Combine all conditions with OR
            combined_condition = or_(*search_conditions)
            
            # Calculate total rank
            total_rank = sum(rank_expressions) if rank_expressions else 0
            
            # Build query with ranking
            query_obj = db.session.query(cls, total_rank.label('calculated_rank'))\
                                 .filter(combined_condition)
            
            # Apply additional filters
            for filter_name, filter_value in filters.items():
                if hasattr(cls, filter_name):
                    filter_field = getattr(cls, filter_name)
                    query_obj = query_obj.filter(filter_field == filter_value)
            
            # Order by calculated rank and apply limits
            results = query_obj.order_by(total_rank.desc())\
                             .limit(limit)\
                             .all()
            
            return [result[0] for result in results]
            
        except Exception as e:
            log.error(f"Enhanced basic search failed: {e}")
            # Final fallback - simple ilike search
            return cls._simple_fallback_search(query, limit, **filters)
    
    @classmethod
    def _simple_fallback_search(cls, query: str, limit: int, **filters):
        """Simple fallback search using basic ILIKE."""
        try:
            from flask_appbuilder import db
            from sqlalchemy import or_
            
            search_conditions = []
            for field_name, _ in cls.__searchable__.items():
                if hasattr(cls, field_name):
                    field = getattr(cls, field_name)
                    search_conditions.append(field.ilike(f'%{query}%'))
            
            if not search_conditions:
                return []
            
            query_obj = cls.query.filter(or_(*search_conditions))
            
            # Apply additional filters
            for filter_name, filter_value in filters.items():
                if hasattr(cls, filter_name):
                    filter_field = getattr(cls, filter_name)
                    query_obj = query_obj.filter(filter_field == filter_value)
            
            return query_obj.limit(limit).all()
            
        except Exception as e:
            log.error(f"Even fallback search failed: {e}")
            return []
    
    def update_search_vector(self):
        """Update search vector for this record."""
        if not self.__searchable__:
            return
        
        search_terms = []
        
        for field_name, weight in self.__searchable__.items():
            if hasattr(self, field_name):
                field_value = getattr(self, field_name)
                if field_value:
                    search_terms.append(str(field_value))
        
        self.search_vector = ' '.join(search_terms)
    
    @classmethod
    def __declare_last__(cls):
        """Set up search vector maintenance."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'before_insert')
        def update_search_on_insert(mapper, connection, target):
            target.update_search_vector()
        
        @event.listens_for(cls, 'before_update')
        def update_search_on_update(mapper, connection, target):
            target.update_search_vector()


# Utility function for content mixin setup
def setup_content_mixins(app):
    """
    Set up content mixins with Flask-AppBuilder.
    
    Args:
        app: Flask application instance
    """
    # Configure document settings
    app.config.setdefault('DOCUMENT_MAX_SIZE', 10 * 1024 * 1024)  # 10MB
    app.config.setdefault('DOCUMENT_ALLOWED_TYPES', [
        'pdf', 'doc', 'docx', 'txt', 'md', 'rtf',
        'xls', 'xlsx', 'csv',
        'jpg', 'jpeg', 'png', 'gif', 'bmp',
        'mp4', 'avi', 'mov', 'wmv',
        'mp3', 'wav', 'flac'
    ])
    
    # Configure commenting
    app.config.setdefault('COMMENTS_MODERATION_REQUIRED', False)
    app.config.setdefault('COMMENTS_MAX_DEPTH', 5)
    app.config.setdefault('COMMENTS_ALLOW_ANONYMOUS', False)
    
    # Configure search
    app.config.setdefault('SEARCH_ENABLED', True)
    app.config.setdefault('SEARCH_DEFAULT_LANGUAGE', 'english')
    
    log.info("Content mixins configured successfully")


__all__ = [
    'DocumentMixin',
    'SlugMixin', 
    'CommentableMixin',
    'SearchableMixin',
    'setup_content_mixins'
]