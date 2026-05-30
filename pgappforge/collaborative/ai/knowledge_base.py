"""
Knowledge Base Management for PgAppForge collaborative AI features.

Automatically indexes workspace content, manages document lifecycle,
and provides intelligent content discovery for RAG-powered chatbots.
"""

import asyncio
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Tuple
import json

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin

from .types import DocumentType, DocumentChunk
from .rag_engine import RAGEngine
from .ai_models import ModelManager
from ..utils.validation import ValidationHelper

logger = logging.getLogger(__name__)


class IndexingStatus(Enum):
    """Status of content indexing."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress" 
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContentSource(Enum):
    """Sources of content for indexing."""
    
    CHAT_MESSAGE = "chat_message"
    COMMENT = "comment"
    DOCUMENT = "document"
    WIKI_PAGE = "wiki_page"
    CODE_FILE = "code_file"
    MEETING_NOTES = "meeting_notes"
    USER_UPLOAD = "user_upload"
    EXTERNAL_LINK = "external_link"


@dataclass
class IndexingTask:
    """Task for indexing content."""
    
    content_id: str
    content_source: ContentSource
    content_text: str
    workspace_id: Optional[int] = None
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # 1=high, 5=low
    created_at: datetime = field(default_factory=datetime.utcnow)


class IndexedContent(Model, AuditMixin):
    """Tracks indexed content to avoid duplicate processing."""
    
    __tablename__ = "fab_indexed_content"
    
    id = Column(Integer, primary_key=True)
    
    # Content identification
    content_id = Column(String(255), nullable=False, index=True)
    content_source = Column(String(50), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    
    # Workspace context
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"))
    team_id = Column(Integer, ForeignKey("fab_teams.id"))
    
    # Indexing status
    status = Column(String(20), default=IndexingStatus.PENDING.value)
    indexed_at = Column(DateTime)
    chunks_created = Column(Integer, default=0)
    
    # Content metadata
    content_length = Column(Integer)
    language = Column(String(10), default="en")
    last_modified = Column(DateTime)
    
    # Error tracking
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    
    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_content_workspace_source", "workspace_id", "content_source"),
        Index("ix_content_status", "status"),
        Index("ix_content_hash_workspace", "content_hash", "workspace_id"),
    )
    
    def mark_completed(self, chunks_created: int):
        """Mark content as successfully indexed."""
        self.status = IndexingStatus.COMPLETED.value
        self.indexed_at = datetime.now(tz=timezone.utc)
        self.chunks_created = chunks_created
        self.error_message = None
    
    def mark_failed(self, error: str):
        """Mark content indexing as failed."""
        self.status = IndexingStatus.FAILED.value
        self.error_message = error
        self.retry_count += 1


class KnowledgeBaseManager:
    """Manages knowledge base content indexing and lifecycle."""
    
    def __init__(
        self,
        rag_engine: RAGEngine,
        model_manager: ModelManager,
        session_factory: Callable,
        max_concurrent_tasks: int = 5,
        auto_indexing_enabled: bool = True
    ):
        self.rag_engine = rag_engine
        self.model_manager = model_manager
        self.session_factory = session_factory
        self.max_concurrent_tasks = max_concurrent_tasks
        self.auto_indexing_enabled = auto_indexing_enabled
        
        self.logger = logging.getLogger(__name__)
        self.indexing_queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Set[str] = set()
        self.indexing_semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # Content filters for what should be indexed
        self.content_filters = {
            ContentSource.CHAT_MESSAGE: self._filter_chat_message,
            ContentSource.COMMENT: self._filter_comment,
            ContentSource.DOCUMENT: self._filter_document,
            ContentSource.WIKI_PAGE: self._filter_wiki_page,
            ContentSource.CODE_FILE: self._filter_code_file,
            ContentSource.MEETING_NOTES: self._filter_meeting_notes,
            ContentSource.USER_UPLOAD: self._filter_user_upload,
            ContentSource.EXTERNAL_LINK: self._filter_external_link
        }
        
        # Background task handles
        self.background_tasks: List[asyncio.Task] = []
    
    async def start_background_processing(self):
        """Start background content indexing processing."""
        if not self.auto_indexing_enabled:
            self.logger.info("Auto-indexing disabled, skipping background processing")
            return
        
        self.logger.info("Starting knowledge base background processing")
        
        # Start indexing queue processor
        indexing_task = asyncio.create_task(self._process_indexing_queue())
        self.background_tasks.append(indexing_task)
        
        # Start periodic cleanup
        cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self.background_tasks.append(cleanup_task)
        
        # Start content discovery
        discovery_task = asyncio.create_task(self._discover_new_content())
        self.background_tasks.append(discovery_task)
        
        self.logger.info("Knowledge base background processing started")
    
    async def stop_background_processing(self):
        """Stop background processing."""
        self.logger.info("Stopping knowledge base background processing")
        
        # Cancel all background tasks
        for task in self.background_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.background_tasks, return_exceptions=True)
        
        self.logger.info("Knowledge base background processing stopped")
    
    async def index_content(
        self,
        content_id: str,
        content_source: ContentSource,
        content_text: str,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        force_reindex: bool = False
    ) -> Dict[str, Any]:
        """Index content immediately or add to queue."""
        try:
            # Create indexing task
            task = IndexingTask(
                content_id=content_id,
                content_source=content_source,
                content_text=content_text,
                workspace_id=workspace_id,
                team_id=team_id,
                user_id=user_id,
                metadata=metadata or {},
                priority=1  # High priority for explicit requests
            )
            
            # Check if content needs indexing
            if not force_reindex:
                content_hash = self._get_content_hash(content_text)
                existing = await self._get_indexed_content(content_id, content_hash, workspace_id)
                
                if existing and existing.status == IndexingStatus.COMPLETED.value:
                    self.logger.debug(f"Content {content_id} already indexed, skipping")
                    return {
                        "status": "skipped",
                        "reason": "already_indexed",
                        "chunks_created": existing.chunks_created
                    }
            
            # Process immediately for high priority or process in background
            if task.priority == 1:
                return await self._process_indexing_task(task)
            else:
                await self.indexing_queue.put(task)
                return {
                    "status": "queued",
                    "message": "Content added to indexing queue"
                }
        
        except Exception as e:
            self.logger.error(f"Failed to index content {content_id}: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def remove_content(
        self,
        content_id: str,
        workspace_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Remove content from knowledge base."""
        try:
            # Remove from RAG engine
            deleted_count = await self.rag_engine.delete_document(content_id, workspace_id)
            
            # Mark as removed in database
            session = self.session_factory()
            
            indexed_content = session.query(IndexedContent).filter_by(
                content_id=content_id
            )
            
            if workspace_id:
                indexed_content = indexed_content.filter_by(workspace_id=workspace_id)
            
            removed_records = indexed_content.delete(synchronize_session=False)
            session.commit()
            session.close()
            
            self.logger.info(f"Removed content {content_id}: {deleted_count} embeddings, {removed_records} records")
            
            return {
                "status": "success",
                "embeddings_deleted": deleted_count,
                "records_deleted": removed_records
            }
            
        except Exception as e:
            if 'session' in locals():
                session.rollback()
                session.close()
            self.logger.error(f"Failed to remove content {content_id}: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def search_content(
        self,
        query: str,
        workspace_id: Optional[int] = None,
        content_sources: Optional[List[ContentSource]] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Search indexed content."""
        try:
            # Convert content sources to document types
            document_types = []
            if content_sources:
                for source in content_sources:
                    if source == ContentSource.CHAT_MESSAGE:
                        document_types.append(DocumentType.CHAT_MESSAGE)
                    elif source == ContentSource.COMMENT:
                        document_types.append(DocumentType.COMMENT)
                    elif source == ContentSource.DOCUMENT:
                        document_types.append(DocumentType.WORKSPACE_DOCUMENT)
                    elif source == ContentSource.WIKI_PAGE:
                        document_types.append(DocumentType.WIKI_PAGE)
                    elif source == ContentSource.CODE_FILE:
                        document_types.append(DocumentType.CODE_FILE)
                    elif source == ContentSource.MEETING_NOTES:
                        document_types.append(DocumentType.MEETING_NOTES)
            
            # Use RAG engine for search
            results = await self.rag_engine.query(
                query=query,
                workspace_id=workspace_id,
                document_types=document_types,
                max_results=limit,
                include_sources=True
            )
            
            return {
                "status": "success",
                "results": results["sources"] if "sources" in results else [],
                "total_found": len(results.get("sources", [])),
                "confidence": results.get("confidence", 0.0),
                "query": query
            }
            
        except Exception as e:
            self.logger.error(f"Content search failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "results": []
            }
    
    async def get_indexing_stats(
        self, 
        workspace_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get knowledge base indexing statistics."""
        try:
            session = self.session_factory()
            
            query = session.query(IndexedContent)
            if workspace_id:
                query = query.filter_by(workspace_id=workspace_id)
            
            # Get status counts
            stats = {}
            for status in IndexingStatus:
                count = query.filter_by(status=status.value).count()
                stats[f"{status.value}_count"] = count
            
            # Get total content and chunks
            stats["total_content"] = query.count()
            stats["total_chunks"] = query.with_entities(
                session.func.sum(IndexedContent.chunks_created)
            ).scalar() or 0
            
            # Get content by source
            source_counts = {}
            for source in ContentSource:
                count = query.filter_by(content_source=source.value).count()
                source_counts[source.value] = count
            
            stats["content_by_source"] = source_counts
            
            # Get recent activity
            one_day_ago = datetime.now(tz=timezone.utc) - timedelta(days=1)
            stats["indexed_last_24h"] = query.filter(
                IndexedContent.indexed_at >= one_day_ago
            ).count()
            
            session.close()
            
            return {
                "status": "success",
                "stats": stats,
                "queue_size": self.indexing_queue.qsize(),
                "active_tasks": len(self.active_tasks)
            }
            
        except Exception as e:
            if 'session' in locals():
                session.close()
            self.logger.error(f"Failed to get indexing stats: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _process_indexing_queue(self):
        """Process the indexing queue in background."""
        while True:
            try:
                # Get next task from queue
                task = await self.indexing_queue.get()
                
                # Process with semaphore to limit concurrent tasks
                async with self.indexing_semaphore:
                    await self._process_indexing_task(task)
                
                # Mark task as done
                self.indexing_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error processing indexing queue: {e}")
                await asyncio.sleep(5)  # Brief pause on error
    
    async def _process_indexing_task(self, task: IndexingTask) -> Dict[str, Any]:
        """Process a single indexing task."""
        task_key = f"{task.content_id}:{task.workspace_id}"
        
        try:
            # Prevent duplicate processing
            if task_key in self.active_tasks:
                return {"status": "skipped", "reason": "already_processing"}
            
            self.active_tasks.add(task_key)
            
            # Apply content filter
            if not await self._should_index_content(task):
                await self._mark_content_skipped(task)
                return {"status": "skipped", "reason": "filtered_out"}
            
            # Create or update indexed content record
            content_hash = self._get_content_hash(task.content_text)
            indexed_content = await self._create_or_update_indexed_content(task, content_hash)
            
            # Convert to document type
            document_type = self._get_document_type(task.content_source)
            
            # Add to RAG engine
            embedding_ids = await self.rag_engine.add_document(
                content=task.content_text,
                document_id=task.content_id,
                document_type=document_type,
                workspace_id=task.workspace_id,
                team_id=task.team_id,
                user_id=task.user_id,
                metadata=task.metadata
            )
            
            # Mark as completed
            session = self.session_factory()
            indexed_content = session.query(IndexedContent).get(indexed_content.id)
            indexed_content.mark_completed(len(embedding_ids))
            session.commit()
            session.close()
            
            self.logger.info(f"Successfully indexed content {task.content_id} with {len(embedding_ids)} chunks")
            
            return {
                "status": "success",
                "chunks_created": len(embedding_ids),
                "embedding_ids": embedding_ids
            }
            
        except Exception as e:
            # Mark as failed
            try:
                session = self.session_factory()
                indexed_content = session.query(IndexedContent).filter_by(
                    content_id=task.content_id,
                    workspace_id=task.workspace_id
                ).first()
                
                if indexed_content:
                    indexed_content.mark_failed(str(e))
                    session.commit()
                
                session.close()
            except Exception:
                pass  # Don't fail on failure to mark failed
            
            self.logger.error(f"Failed to process indexing task {task.content_id}: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
        
        finally:
            self.active_tasks.discard(task_key)
    
    async def _should_index_content(self, task: IndexingTask) -> bool:
        """Determine if content should be indexed."""
        # Check content length
        if len(task.content_text.strip()) < 10:
            return False
        
        # Apply source-specific filter
        filter_func = self.content_filters.get(task.content_source)
        if filter_func:
            return await filter_func(task)
        
        return True
    
    async def _filter_chat_message(self, task: IndexingTask) -> bool:
        """Filter chat messages for indexing."""
        content = task.content_text.strip()
        
        # Skip very short messages
        if len(content) < 20:
            return False
        
        # Skip messages that are mostly emojis or special characters
        if len([c for c in content if c.isalnum()]) < len(content) * 0.5:
            return False
        
        # Skip system messages
        if task.metadata.get("message_type") == "system":
            return False
        
        return True
    
    async def _filter_comment(self, task: IndexingTask) -> bool:
        """Filter comments for indexing."""
        content = task.content_text.strip()
        
        # Skip very short comments
        if len(content) < 15:
            return False
        
        # Skip comments that are just reactions
        reaction_words = ["👍", "👎", "+1", "-1", "lgtm", "thanks", "thx"]
        if content.lower() in reaction_words:
            return False
        
        return True
    
    async def _filter_document(self, task: IndexingTask) -> bool:
        """Filter documents for indexing."""
        # Index most documents, but skip empty ones
        return len(task.content_text.strip()) > 0
    
    async def _filter_wiki_page(self, task: IndexingTask) -> bool:
        """Filter wiki pages for indexing."""
        return len(task.content_text.strip()) > 0
    
    async def _filter_code_file(self, task: IndexingTask) -> bool:
        """Filter code files for indexing."""
        # Skip binary files or very large files
        if len(task.content_text) > 50000:  # 50KB limit
            return False
        
        # Skip files that are mostly generated content
        if "auto-generated" in task.content_text.lower():
            return False
        
        return True
    
    async def _filter_meeting_notes(self, task: IndexingTask) -> bool:
        """Filter meeting notes for indexing."""
        return len(task.content_text.strip()) > 20
    
    async def _filter_user_upload(self, task: IndexingTask) -> bool:
        """Filter user uploads for indexing."""
        return len(task.content_text.strip()) > 0
    
    async def _filter_external_link(self, task: IndexingTask) -> bool:
        """Filter external links for indexing."""
        # Only index if we have extracted content
        return len(task.content_text.strip()) > 50
    
    def _get_document_type(self, content_source: ContentSource) -> DocumentType:
        """Convert content source to document type."""
        mapping = {
            ContentSource.CHAT_MESSAGE: DocumentType.CHAT_MESSAGE,
            ContentSource.COMMENT: DocumentType.COMMENT,
            ContentSource.DOCUMENT: DocumentType.WORKSPACE_DOCUMENT,
            ContentSource.WIKI_PAGE: DocumentType.WIKI_PAGE,
            ContentSource.CODE_FILE: DocumentType.CODE_FILE,
            ContentSource.MEETING_NOTES: DocumentType.MEETING_NOTES,
            ContentSource.USER_UPLOAD: DocumentType.USER_DOCUMENT,
            ContentSource.EXTERNAL_LINK: DocumentType.WORKSPACE_DOCUMENT
        }
        return mapping.get(content_source, DocumentType.WORKSPACE_DOCUMENT)
    
    def _get_content_hash(self, content: str) -> str:
        """Generate hash for content deduplication."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def _get_indexed_content(
        self, 
        content_id: str, 
        content_hash: str, 
        workspace_id: Optional[int]
    ) -> Optional[IndexedContent]:
        """Get existing indexed content record."""
        try:
            session = self.session_factory()
            
            query = session.query(IndexedContent).filter_by(
                content_id=content_id,
                content_hash=content_hash
            )
            
            if workspace_id:
                query = query.filter_by(workspace_id=workspace_id)
            
            result = query.first()
            session.close()
            return result
            
        except Exception as e:
            if 'session' in locals():
                session.close()
            self.logger.error(f"Failed to get indexed content: {e}")
            return None
    
    async def _create_or_update_indexed_content(
        self, 
        task: IndexingTask, 
        content_hash: str
    ) -> IndexedContent:
        """Create or update indexed content record."""
        session = self.session_factory()
        
        try:
            # Try to find existing record
            existing = session.query(IndexedContent).filter_by(
                content_id=task.content_id,
                workspace_id=task.workspace_id
            ).first()
            
            if existing:
                # Update existing record
                existing.content_hash = content_hash
                existing.content_source = task.content_source.value
                existing.status = IndexingStatus.IN_PROGRESS.value
                existing.content_length = len(task.content_text)
                existing.last_modified = datetime.now(tz=timezone.utc)
                existing.retry_count = 0
                existing.error_message = None
                indexed_content = existing
            else:
                # Create new record
                indexed_content = IndexedContent(
                    content_id=task.content_id,
                    content_source=task.content_source.value,
                    content_hash=content_hash,
                    workspace_id=task.workspace_id,
                    team_id=task.team_id,
                    status=IndexingStatus.IN_PROGRESS.value,
                    content_length=len(task.content_text),
                    last_modified=datetime.now(tz=timezone.utc),
                    created_by_user_id=task.user_id
                )
                session.add(indexed_content)
            
            session.commit()
            result_id = indexed_content.id
            session.close()
            
            # Return a fresh instance
            session = self.session_factory()
            result = session.query(IndexedContent).get(result_id)
            session.close()
            return result
            
        except Exception as e:
            session.rollback()
            session.close()
            raise
    
    async def _mark_content_skipped(self, task: IndexingTask):
        """Mark content as skipped in database."""
        try:
            content_hash = self._get_content_hash(task.content_text)
            indexed_content = await self._create_or_update_indexed_content(task, content_hash)
            
            session = self.session_factory()
            indexed_content = session.query(IndexedContent).get(indexed_content.id)
            indexed_content.status = IndexingStatus.SKIPPED.value
            session.commit()
            session.close()
            
        except Exception as e:
            self.logger.error(f"Failed to mark content as skipped: {e}")
    
    async def _periodic_cleanup(self):
        """Periodic cleanup of old and failed content."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                
                session = self.session_factory()
                
                # Clean up old failed records (older than 7 days)
                seven_days_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
                deleted_failed = session.query(IndexedContent).filter(
                    IndexedContent.status == IndexingStatus.FAILED.value,
                    IndexedContent.created_at < seven_days_ago,
                    IndexedContent.retry_count > 3
                ).delete(synchronize_session=False)
                
                # Clean up very old completed records (older than 90 days)
                ninety_days_ago = datetime.now(tz=timezone.utc) - timedelta(days=90)
                deleted_old = session.query(IndexedContent).filter(
                    IndexedContent.status == IndexingStatus.COMPLETED.value,
                    IndexedContent.created_at < ninety_days_ago
                ).delete(synchronize_session=False)
                
                session.commit()
                session.close()
                
                if deleted_failed > 0 or deleted_old > 0:
                    self.logger.info(f"Cleanup: removed {deleted_failed} failed records, {deleted_old} old records")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error during periodic cleanup: {e}")
                if 'session' in locals():
                    session.rollback()
                    session.close()
    
    async def _discover_new_content(self):
        """Discover new content that needs indexing."""
        while True:
            try:
                await asyncio.sleep(1800)  # Run every 30 minutes
                
                # This would integrate with various content sources
                # to discover new content that hasn't been indexed yet
                # Implementation would depend on specific content sources
                
                self.logger.debug("Content discovery cycle completed")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error during content discovery: {e}")