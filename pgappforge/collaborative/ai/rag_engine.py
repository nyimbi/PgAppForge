"""
Retrieval-Augmented Generation (RAG) engine for PgAppForge collaborative features.

Provides intelligent document retrieval and context-aware response generation
by combining vector search with AI models for accurate, workspace-specific answers.
"""

import asyncio
import logging
import hashlib
import json
import time
import threading
import psutil
from functools import lru_cache
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union, Callable
from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin

from .types import DocumentChunk, RetrievalResult, DocumentType, ChunkingStrategy, EmbeddingModelProtocol, VectorStoreProtocol
from .ai_models import AIModelAdapter, ChatMessage, ModelResponse
from .models import VectorEmbedding
from ..utils.validation import ValidationHelper

# Check if FAISS is available without importing the module (prevents circular import)
try:
    import faiss
    FAISS_AVAILABLE = True
    # Import FAISS vector store when available
    from .faiss_vector_store import FAISSIntegratedVectorStore
except Exception as e:
    # FAISS is optional - gracefully handle import failures
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"FAISS not available: {e}. RAG engine will use standard vector operations.")
    FAISS_AVAILABLE = False
    FAISSIntegratedVectorStore = None

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """Memory usage monitoring and management for RAG components."""

    def __init__(self, max_memory_mb: int = 512, check_interval: int = 30):
        self.max_memory_mb = max_memory_mb
        self.check_interval = check_interval
        self.logger = logging.getLogger(__name__ + ".MemoryMonitor")
        self.callbacks: List[Callable[[], None]] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None

    def register_cleanup_callback(self, callback: Callable[[], None]):
        """Register callback for memory cleanup."""
        self.callbacks.append(callback)

    def get_memory_usage(self) -> Dict[str, float]:
        """Get current memory usage statistics."""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()

            return {
                "rss_mb": memory_info.rss / 1024 / 1024,
                "vms_mb": memory_info.vms / 1024 / 1024,
                "percent": process.memory_percent(),
                "available_mb": psutil.virtual_memory().available / 1024 / 1024
            }
        except Exception as e:
            self.logger.warning(f"Failed to get memory usage: {e}")
            return {"rss_mb": 0, "vms_mb": 0, "percent": 0, "available_mb": 0}

    def is_memory_pressure(self) -> bool:
        """Check if system is under memory pressure."""
        usage = self.get_memory_usage()
        return usage["rss_mb"] > self.max_memory_mb or usage["percent"] > 80.0

    def start_monitoring(self):
        """Start background memory monitoring."""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_memory, daemon=True)
        self._monitor_thread.start()
        self.logger.info(f"Started memory monitoring (max: {self.max_memory_mb}MB)")

    def stop_monitoring(self):
        """Stop background memory monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def _monitor_memory(self):
        """Background memory monitoring loop."""
        while self._monitoring:
            try:
                if self.is_memory_pressure():
                    usage = self.get_memory_usage()
                    self.logger.warning(
                        f"Memory pressure detected: {usage['rss_mb']:.1f}MB ({usage['percent']:.1f}%)"
                    )

                    # Trigger cleanup callbacks
                    for callback in self.callbacks:
                        try:
                            callback()
                        except Exception as e:
                            self.logger.error(f"Cleanup callback failed: {e}")

                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"Memory monitoring error: {e}")
                time.sleep(self.check_interval)


class LRUCache:
    """Thread-safe LRU cache with size and TTL limits."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None

            value, timestamp = self.cache[key]

            # Check TTL
            if time.time() - timestamp > self.ttl_seconds:
                del self.cache[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self.cache.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: str, value: Any):
        """Put value in cache."""
        with self.lock:
            # Remove if exists to update position
            if key in self.cache:
                del self.cache[key]

            # Add new entry
            self.cache[key] = (value, time.time())

            # Evict oldest if over size limit
            while len(self.cache) > self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]

    def clear(self):
        """Clear all cached entries."""
        with self.lock:
            self.cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests) if total_requests > 0 else 0.0

            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "memory_usage_mb": self._estimate_memory_usage()
            }

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage of cache in MB."""
        # Rough estimate: 1KB per cache entry on average
        return len(self.cache) * 1024 / 1024 / 1024

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        with self.lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, timestamp) in self.cache.items()
                if current_time - timestamp > self.ttl_seconds
            ]

            for key in expired_keys:
                del self.cache[key]

            return len(expired_keys)


class ConnectionPool:
    """Database connection pool with limits and monitoring."""

    def __init__(self, session_factory, max_connections: int = 20, max_idle_time: int = 300):
        self.session_factory = session_factory
        self.max_connections = max_connections
        self.max_idle_time = max_idle_time
        self.active_connections = 0
        self.connection_times: Dict[int, float] = {}
        self.lock = threading.RLock()
        self.logger = logging.getLogger(__name__ + ".ConnectionPool")

    def acquire_session(self):
        """Acquire database session with connection limits."""
        with self.lock:
            if self.active_connections >= self.max_connections:
                raise RuntimeError(f"Connection pool exhausted (max: {self.max_connections})")

            session = self.session_factory()
            connection_id = id(session)
            self.active_connections += 1
            self.connection_times[connection_id] = time.time()

            self.logger.debug(f"Acquired connection {connection_id} ({self.active_connections}/{self.max_connections})")
            return session, connection_id

    def release_session(self, session, connection_id: int):
        """Release database session."""
        with self.lock:
            try:
                session.close()
            except Exception as e:
                self.logger.warning(f"Error closing session {connection_id}: {e}")
            finally:
                self.active_connections = max(0, self.active_connections - 1)
                self.connection_times.pop(connection_id, None)
                self.logger.debug(f"Released connection {connection_id} ({self.active_connections}/{self.max_connections})")

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics."""
        with self.lock:
            current_time = time.time()
            long_running = sum(
                1 for conn_time in self.connection_times.values()
                if current_time - conn_time > self.max_idle_time
            )

            return {
                "active_connections": self.active_connections,
                "max_connections": self.max_connections,
                "utilization": self.active_connections / self.max_connections if self.max_connections > 0 else 0.0,
                "long_running_connections": long_running
            }

    def cleanup_stale_connections(self) -> int:
        """Log information about potentially stale connections."""
        with self.lock:
            current_time = time.time()
            stale_count = 0

            for connection_id, conn_time in list(self.connection_times.items()):
                if current_time - conn_time > self.max_idle_time:
                    stale_count += 1
                    self.logger.warning(f"Long-running connection detected: {connection_id} ({current_time - conn_time:.1f}s)")

            return stale_count


# DocumentType imported from types module


# DocumentChunk imported from types module


# RetrievalResult imported from types module


@dataclass
class RAGContext:
    """Context for RAG generation."""

    query: str
    retrieved_chunks: List[RetrievalResult]
    workspace_id: Optional[int] = None
    user_id: Optional[int] = None
    max_context_length: int = 4000
    include_metadata: bool = True





class VectorStore:
    """Vector storage and similarity search with memory management."""

    def __init__(self, session_factory, embedding_model: AIModelAdapter, enable_monitoring: bool = True):
        self.embedding_model = embedding_model
        self.logger = logging.getLogger(__name__)

        # Memory management components
        self.memory_monitor = MemoryMonitor(max_memory_mb=512)
        self.connection_pool = ConnectionPool(session_factory, max_connections=10)

        # Caching for performance and memory efficiency
        self.embedding_cache = LRUCache(max_size=1000, ttl_seconds=3600)  # 1 hour TTL
        self.similarity_cache = LRUCache(max_size=500, ttl_seconds=1800)   # 30 min TTL

        # Register cleanup callbacks
        self.memory_monitor.register_cleanup_callback(self._cleanup_caches)

        if enable_monitoring:
            self.memory_monitor.start_monitoring()

    def _cleanup_caches(self):
        """Cleanup caches when under memory pressure."""
        self.logger.info("Memory pressure detected, cleaning up caches")

        # Clean expired entries first
        embedding_expired = self.embedding_cache.cleanup_expired()
        similarity_expired = self.similarity_cache.cleanup_expired()

        self.logger.info(f"Cleaned {embedding_expired} embedding cache entries, {similarity_expired} similarity cache entries")

        # If still under pressure, clear 50% of cache
        if self.memory_monitor.is_memory_pressure():
            embedding_stats = self.embedding_cache.get_stats()
            similarity_stats = self.similarity_cache.get_stats()

            # Clear half the cache entries
            if embedding_stats["size"] > 100:
                self.embedding_cache.clear()
                self.logger.info("Cleared embedding cache due to memory pressure")

            if similarity_stats["size"] > 50:
                self.similarity_cache.clear()
                self.logger.info("Cleared similarity cache due to memory pressure")

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get comprehensive memory and performance statistics."""
        return {
            "memory_usage": self.memory_monitor.get_memory_usage(),
            "connection_pool": self.connection_pool.get_pool_stats(),
            "embedding_cache": self.embedding_cache.get_stats(),
            "similarity_cache": self.similarity_cache.get_stats()
        }

    def shutdown(self):
        """Shutdown monitoring and cleanup resources."""
        self.memory_monitor.stop_monitoring()
        self.embedding_cache.clear()
        self.similarity_cache.clear()
        self.logger.info("VectorStore shutdown completed")

    async def add_documents(
        self,
        chunks: List[DocumentChunk],
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> List[str]:
        """Add document chunks to vector store."""
        try:
            # Generate embeddings for all chunks with caching
            contents = [chunk.content for chunk in chunks]
            embeddings = await self._get_embeddings_with_cache(contents)

            session, connection_id = self.connection_pool.acquire_session()
            embedding_ids = []

            for chunk, embedding in zip(chunks, embeddings):
                # Check for existing embedding with same content hash
                content_hash = chunk.get_content_hash()
                existing = session.query(VectorEmbedding).filter_by(
                    content_hash=content_hash,
                    workspace_id=workspace_id
                ).first()

                if existing:
                    self.logger.debug(f"Skipping duplicate content: {content_hash[:8]}")
                    embedding_ids.append(str(existing.id))
                    continue

                # Create new embedding record
                vector_embedding = VectorEmbedding(
                    document_id=chunk.document_id,
                    document_type=chunk.document_type.value,
                    chunk_index=chunk.chunk_index,
                    content_hash=content_hash,
                    content=chunk.content,
                    embedding_model=self.embedding_model.config.model_name,
                    workspace_id=workspace_id,
                    team_id=team_id,
                    user_id=user_id,
                    content_length=len(chunk.content),
                    created_by_user_id=user_id
                )

                vector_embedding.set_embedding_vector(embedding)
                vector_embedding.set_metadata(chunk.metadata)

                session.add(vector_embedding)
                session.flush()  # Get ID without committing
                embedding_ids.append(str(vector_embedding.id))

            session.commit()
            self.logger.info(f"Added {len(embedding_ids)} embeddings to vector store")
            return embedding_ids

        except Exception as e:
            if session:
                session.rollback()
            self.logger.error(f"Failed to add documents to vector store: {e}")
            raise
        finally:
            if session and connection_id:
                self.connection_pool.release_session(session, connection_id)

    async def _get_embeddings_with_cache(self, contents: List[str]) -> List[List[float]]:
        """Get embeddings with caching to avoid redundant API calls."""
        cached_embeddings = []
        uncached_contents = []
        uncached_indices = []

        # Check cache for each content
        for i, content in enumerate(contents):
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            cached_embedding = self.embedding_cache.get(content_hash)

            if cached_embedding is not None:
                cached_embeddings.append((i, cached_embedding))
            else:
                uncached_contents.append(content)
                uncached_indices.append(i)

        # Generate embeddings for uncached content
        if uncached_contents:
            new_embeddings = await self.embedding_model.generate_embeddings(uncached_contents)

            # Cache new embeddings
            for content, embedding in zip(uncached_contents, new_embeddings):
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                self.embedding_cache.put(content_hash, embedding)
        else:
            new_embeddings = []

        # Combine cached and new embeddings in correct order
        result = [None] * len(contents)

        # Place cached embeddings
        for i, embedding in cached_embeddings:
            result[i] = embedding

        # Place new embeddings
        for i, embedding in zip(uncached_indices, new_embeddings):
            result[i] = embedding

        return result

    async def similarity_search(
        self,
        query: str,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        document_types: Optional[List[DocumentType]] = None,
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[RetrievalResult]:
        """Search for similar documents using vector similarity."""
        # Create cache key for this search
        cache_key = self._create_search_cache_key(
            query, workspace_id, team_id, document_types, limit, similarity_threshold
        )

        # Check cache first
        cached_result = self.similarity_cache.get(cache_key)
        if cached_result is not None:
            self.logger.debug(f"Cache hit for similarity search: {cache_key[:16]}")
            return cached_result

        session = None
        connection_id = None

        try:
            # Generate embedding for query with caching
            query_embeddings = await self._get_embeddings_with_cache([query])
            query_vector = query_embeddings[0]

            session, connection_id = self.connection_pool.acquire_session()

            # Build query with filters
            query_builder = session.query(VectorEmbedding)

            if workspace_id:
                query_builder = query_builder.filter(VectorEmbedding.workspace_id == workspace_id)

            if team_id:
                query_builder = query_builder.filter(VectorEmbedding.team_id == team_id)

            if document_types:
                type_values = [dt.value for dt in document_types]
                query_builder = query_builder.filter(VectorEmbedding.document_type.in_(type_values))

            # Get all candidate embeddings
            candidates = query_builder.all()

            # Calculate similarities
            results = []
            for candidate in candidates:
                candidate_vector = candidate.get_embedding_vector()
                if not candidate_vector:
                    continue

                # Calculate cosine similarity
                similarity = self._cosine_similarity(query_vector, candidate_vector)

                if similarity >= similarity_threshold:
                    chunk = DocumentChunk(
                        content=candidate.content,
                        metadata=candidate.get_metadata(),
                        chunk_index=candidate.chunk_index,
                        document_id=candidate.document_id,
                        document_type=DocumentType(candidate.document_type),
                        embeddings=candidate_vector
                    )

                    results.append(RetrievalResult(
                        chunk=chunk,
                        similarity_score=similarity,
                        metadata={
                            "embedding_id": candidate.id,
                            "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
                            "content_length": candidate.content_length
                        }
                    ))

            # Sort by similarity and limit results
            results.sort(key=lambda x: x.similarity_score, reverse=True)
            final_results = results[:limit]

            # Cache results for future queries
            self.similarity_cache.put(cache_key, final_results)

            return final_results

        except Exception as e:
            self.logger.error(f"Similarity search failed: {e}")
            return []
        finally:
            if session and connection_id:
                self.connection_pool.release_session(session, connection_id)

    def _create_search_cache_key(
        self,
        query: str,
        workspace_id: Optional[int],
        team_id: Optional[int],
        document_types: Optional[List[DocumentType]],
        limit: int,
        similarity_threshold: float
    ) -> str:
        """Create cache key for similarity search."""
        # Create deterministic key from search parameters
        key_parts = [
            query,
            str(workspace_id) if workspace_id else "None",
            str(team_id) if team_id else "None",
            ",".join(sorted([dt.value for dt in document_types])) if document_types else "None",
            str(limit),
            f"{similarity_threshold:.2f}"
        ]

        key_string = "|".join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            import numpy as np

            # Convert to numpy arrays
            a = np.array(vec1)
            b = np.array(vec2)

            # Calculate cosine similarity
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot_product / (norm_a * norm_b))

        except ImportError:
            self.logger.warning("NumPy not available, using manual cosine similarity calculation")
            return self._manual_cosine_similarity(vec1, vec2)
        except Exception as e:
            self.logger.error(f"Cosine similarity calculation failed: {e}")
            return 0.0

    def _manual_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Manual cosine similarity calculation without NumPy."""
        if len(vec1) != len(vec2):
            return 0.0

        try:
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            norm_a = sum(a * a for a in vec1) ** 0.5
            norm_b = sum(b * b for b in vec2) ** 0.5

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return dot_product / (norm_a * norm_b)
        except Exception:
            return 0.0

    async def delete_documents(
        self,
        document_ids: List[str],
        workspace_id: Optional[int] = None
    ) -> int:
        """Delete documents from vector store."""
        try:
            session = self.session_factory()

            query_builder = session.query(VectorEmbedding).filter(
                VectorEmbedding.document_id.in_(document_ids)
            )

            if workspace_id:
                query_builder = query_builder.filter(VectorEmbedding.workspace_id == workspace_id)

            deleted_count = query_builder.delete(synchronize_session=False)
            session.commit()

            self.logger.info(f"Deleted {deleted_count} embeddings from vector store")
            return deleted_count

        except Exception as e:
            session.rollback()
            self.logger.error(f"Failed to delete documents from vector store: {e}")
            raise
        finally:
            session.close()


# ChunkingStrategy imported from types module


class DocumentProcessor:
    """Enhanced document processor with advanced chunking and preprocessing."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        chunking_strategy: ChunkingStrategy = ChunkingStrategy.SENTENCE_BOUNDARY,
        enable_preprocessing: bool = True,
        min_chunk_size: int = 100,
        max_chunk_size: int = 2000
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunking_strategy = chunking_strategy
        self.enable_preprocessing = enable_preprocessing
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.logger = logging.getLogger(__name__)

        # Text processing patterns
        self._url_pattern = r'https?://[^\s<>"{}|\\^`[\]]+|www\.[^\s<>"{}|\\^`[\]]+'
        self._email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        self._code_fence_pattern = r'```[\s\S]*?```|`[^`]+`'

    def process_document(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """Process document into optimized chunks with advanced preprocessing."""
        if not content or not content.strip():
            return []

        metadata = metadata or {}

        # Preprocess content if enabled
        if self.enable_preprocessing:
            content, extracted_metadata = self._preprocess_content(content, document_type)
            metadata.update(extracted_metadata)

        # Choose chunking method based on document type and strategy
        chunks = self._create_chunks(content, document_id, document_type, metadata)

        # Post-process chunks (filter, enhance metadata)
        chunks = self._post_process_chunks(chunks)

        self.logger.debug(
            f"Processed document {document_id} ({document_type.value}) into {len(chunks)} chunks "
            f"using {self.chunking_strategy.value} strategy"
        )
        return chunks

    def _preprocess_content(self, content: str, document_type: DocumentType) -> Tuple[str, Dict[str, Any]]:
        """Preprocess content with type-specific optimizations."""
        extracted_metadata = {}
        original_length = len(content)

        # Clean whitespace and normalize line endings
        content = self._normalize_whitespace(content)

        # Extract and preserve important elements based on document type
        if document_type == DocumentType.HTML:
            content, html_metadata = self._process_html_content(content)
            extracted_metadata.update(html_metadata)
        elif document_type == DocumentType.CODE:
            content, code_metadata = self._process_code_content(content)
            extracted_metadata.update(code_metadata)
        elif document_type == DocumentType.MARKDOWN:
            content, md_metadata = self._process_markdown_content(content)
            extracted_metadata.update(md_metadata)

        # Language detection
        detected_language = self._detect_language(content)
        if detected_language:
            extracted_metadata["language"] = detected_language

        # Content statistics
        extracted_metadata["preprocessing"] = {
            "original_length": original_length,
            "processed_length": len(content),
            "compression_ratio": len(content) / original_length if original_length > 0 else 1.0
        }

        return content, extracted_metadata

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace while preserving structure."""
        import re

        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)

        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Remove excessive blank lines (keep max 2 consecutive)
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Clean up spaces around punctuation
        text = re.sub(r'\s+([,.;:!?])', r'\1', text)

        return text.strip()

    def _process_html_content(self, content: str) -> Tuple[str, Dict[str, Any]]:
        """Process HTML content, extracting text and metadata."""
        import re

        metadata = {"content_type": "html"}

        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            metadata["title"] = title_match.group(1).strip()

        # Extract meta description
        desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', content, re.IGNORECASE)
        if desc_match:
            metadata["description"] = desc_match.group(1).strip()

        # Remove script and style tags
        content = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', content, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags but preserve structure
        content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'</(div|p|h[1-6])>', '\n\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<[^>]+>', '', content)

        # Decode HTML entities
        import html
        content = html.unescape(content)

        return content, metadata

    def _process_code_content(self, content: str) -> Tuple[str, Dict[str, Any]]:
        """Process code content with syntax awareness."""
        import re

        metadata = {"content_type": "code"}

        # Detect programming language from file extension or patterns
        language = self._detect_code_language(content)
        if language:
            metadata["programming_language"] = language

        # Extract comments and docstrings
        comments = self._extract_code_comments(content, language)
        if comments:
            metadata["comments"] = comments

        # Count lines of code vs comments
        lines = content.split('\n')
        code_lines = 0
        comment_lines = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue
            elif line.startswith('#') or line.startswith('//') or line.startswith('/*'):
                comment_lines += 1
            else:
                code_lines += 1

        metadata["code_stats"] = {
            "total_lines": len(lines),
            "code_lines": code_lines,
            "comment_lines": comment_lines
        }

        return content, metadata

    def _process_markdown_content(self, content: str) -> Tuple[str, Dict[str, Any]]:
        """Process Markdown content, preserving structure."""
        import re

        metadata = {"content_type": "markdown"}

        # Extract headers for document structure
        headers = re.findall(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE)
        if headers:
            metadata["headers"] = [{"level": len(h[0]), "text": h[1].strip()} for h in headers]

        # Extract links
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        if links:
            metadata["links"] = [{"text": link[0], "url": link[1]} for link in links]

        # Convert markdown to clean text while preserving structure
        # Keep headers as is for now (could be enhanced further)
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)

        # Remove markdown formatting
        content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)  # Bold
        content = re.sub(r'\*([^*]+)\*', r'\1', content)      # Italic
        content = re.sub(r'`([^`]+)`', r'\1', content)        # Inline code
        content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)  # Links

        return content, metadata

    def _detect_language(self, text: str) -> Optional[str]:
        """Simple language detection based on character patterns."""
        # Basic language detection (could be enhanced with langdetect library)
        if not text.strip():
            return None

        # Count ASCII vs non-ASCII characters
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        total_chars = len(text)
        ascii_ratio = ascii_chars / total_chars if total_chars > 0 else 0

        # Simple heuristic: mostly ASCII = English
        if ascii_ratio > 0.95:
            return "en"

        return None  # Unknown or non-English

    def _detect_code_language(self, content: str) -> Optional[str]:
        """Detect programming language from code patterns."""
        import re

        # Simple pattern-based detection
        patterns = {
            "python": [r'^import\s+\w+', r'^from\s+\w+\s+import', r'def\s+\w+\(', r'class\s+\w+:'],
            "javascript": [r'^import\s+.*from', r'function\s+\w+\(', r'const\s+\w+\s*=', r'=>'],
            "java": [r'public\s+class\s+\w+', r'import\s+java\.', r'public\s+static\s+void\s+main'],
            "css": [r'[.#]\w+\s*\{', r'\w+\s*:\s*[^;]+;'],
            "sql": [r'^SELECT\s+', r'^INSERT\s+', r'^UPDATE\s+', r'^DELETE\s+'],
            "bash": [r'^#!/bin/(ba)?sh', r'\$\w+', r'if\s*\[.*\]']
        }

        for language, lang_patterns in patterns.items():
            matches = sum(1 for pattern in lang_patterns if re.search(pattern, content, re.MULTILINE | re.IGNORECASE))
            if matches >= 2:  # Require at least 2 pattern matches
                return language

        return None

    def _extract_code_comments(self, content: str, language: Optional[str]) -> List[str]:
        """Extract comments from code based on language."""
        import re

        comments = []

        if language == "python":
            # Python comments and docstrings
            comments.extend(re.findall(r'#\s*(.+)', content))
            comments.extend(re.findall(r'"""(.*?)"""', content, re.DOTALL))
            comments.extend(re.findall(r"'''(.*?)'''", content, re.DOTALL))
        elif language in ["javascript", "java", "css"]:
            # C-style comments
            comments.extend(re.findall(r'//\s*(.+)', content))
            comments.extend(re.findall(r'/\*(.*?)\*/', content, re.DOTALL))

        return [c.strip() for c in comments if c.strip()]

    def _create_chunks(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """Create chunks using the selected strategy."""

        if self.chunking_strategy == ChunkingStrategy.PARAGRAPH_BOUNDARY:
            return self._chunk_by_paragraphs(content, document_id, document_type, metadata)
        elif self.chunking_strategy == ChunkingStrategy.CODE_BLOCKS:
            return self._chunk_by_code_blocks(content, document_id, document_type, metadata)
        elif self.chunking_strategy == ChunkingStrategy.FIXED_SIZE:
            return self._chunk_fixed_size(content, document_id, document_type, metadata)
        else:  # Default: SENTENCE_BOUNDARY
            return self._chunk_by_sentences(content, document_id, document_type, metadata)

    def _chunk_by_sentences(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """Chunk by sentence boundaries (enhanced version of original algorithm)."""
        import re

        # Split into sentences
        sentence_endings = r'[.!?]+\s+'
        sentences = re.split(sentence_endings, content)

        chunks = []
        current_chunk = ""
        chunk_index = 0

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue

            # Check if adding this sentence would exceed chunk size
            potential_chunk = current_chunk + (" " if current_chunk else "") + sentence

            if len(potential_chunk) <= self.chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                # Create chunk from current content
                if current_chunk and len(current_chunk) >= self.min_chunk_size:
                    chunks.append(self._create_chunk(
                        current_chunk, chunk_index, document_id, document_type, metadata
                    ))
                    chunk_index += 1

                # Start new chunk with current sentence
                current_chunk = sentence

        # Add final chunk
        if current_chunk and len(current_chunk) >= self.min_chunk_size:
            chunks.append(self._create_chunk(
                current_chunk, chunk_index, document_id, document_type, metadata
            ))

        return chunks

    def _chunk_by_paragraphs(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """Chunk by paragraph boundaries."""
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        chunks = []
        current_chunk = ""
        chunk_index = 0

        for paragraph in paragraphs:
            potential_chunk = current_chunk + ("\n\n" if current_chunk else "") + paragraph

            if len(potential_chunk) <= self.chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                # Create chunk from current content
                if current_chunk and len(current_chunk) >= self.min_chunk_size:
                    chunks.append(self._create_chunk(
                        current_chunk, chunk_index, document_id, document_type, metadata
                    ))
                    chunk_index += 1

                current_chunk = paragraph

        # Add final chunk
        if current_chunk and len(current_chunk) >= self.min_chunk_size:
            chunks.append(self._create_chunk(
                current_chunk, chunk_index, document_id, document_type, metadata
            ))

        return chunks

    def _chunk_by_code_blocks(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """Chunk code by logical blocks (functions, classes, etc.)."""
        import re

        # For now, fall back to paragraph-based chunking for code
        # This could be enhanced with AST parsing for better code structure awareness
        return self._chunk_by_paragraphs(content, document_id, document_type, metadata)

    def _chunk_fixed_size(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> List[DocumentChunk]:
        """Original fixed-size chunking with overlaps."""
        chunks = []
        start = 0
        chunk_index = 0

        while start < len(content):
            end = min(start + self.chunk_size, len(content))
            chunk_text = content[start:end]

            if chunk_text.strip() and len(chunk_text.strip()) >= self.min_chunk_size:
                chunks.append(self._create_chunk(
                    chunk_text.strip(), chunk_index, document_id, document_type, metadata
                ))
                chunk_index += 1

            # Move start position with overlap
            start = end - self.chunk_overlap
            if start >= len(content):
                break

        return chunks

    def _create_chunk(
        self,
        content: str,
        chunk_index: int,
        document_id: str,
        document_type: DocumentType,
        metadata: Dict[str, Any]
    ) -> DocumentChunk:
        """Create a DocumentChunk with enhanced metadata."""
        chunk_metadata = {
            **metadata,
            "chunk_info": {
                "chunk_index": chunk_index,
                "chunk_size": len(content),
                "chunking_strategy": self.chunking_strategy.value,
                "word_count": len(content.split()),
                "character_count": len(content)
            }
        }

        return DocumentChunk(
            content=content,
            metadata=chunk_metadata,
            chunk_index=chunk_index,
            document_id=document_id,
            document_type=document_type
        )

    def _post_process_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Post-process chunks to enhance quality."""
        if not chunks:
            return chunks

        # Update total chunks count
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk.metadata["chunk_info"]["total_chunks"] = total_chunks

        # Filter out chunks that are too small
        chunks = [chunk for chunk in chunks if len(chunk.content) >= self.min_chunk_size]

        # Add relative positioning information
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_info"]["relative_position"] = i / len(chunks) if chunks else 0

        return chunks

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get current processing configuration and stats."""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunking_strategy": self.chunking_strategy.value,
            "enable_preprocessing": self.enable_preprocessing,
            "min_chunk_size": self.min_chunk_size,
            "max_chunk_size": self.max_chunk_size
        }


class RAGEngine:
    """Main RAG engine combining retrieval and generation with FAISS support."""

    def __init__(
        self,
        vector_store: Union[VectorStore, 'FAISSIntegratedVectorStore'],
        ai_model: AIModelAdapter,
        document_processor: Optional[DocumentProcessor] = None,
        use_faiss: bool = True,
        faiss_config: Optional[Dict[str, Any]] = None
    ):
        self.ai_model = ai_model
        self.document_processor = document_processor or DocumentProcessor()
        self.logger = logging.getLogger(__name__)

        # Initialize vector store (prefer FAISS if available)
        if use_faiss and FAISS_AVAILABLE and FAISSIntegratedVectorStore:
            if isinstance(vector_store, VectorStore):
                # Convert existing VectorStore to FAISS-integrated version
                self.vector_store = self._create_faiss_store(vector_store, faiss_config or {})
                self.logger.info("Using FAISS-integrated vector store for high-performance search")
            else:
                self.vector_store = vector_store
        else:
            self.vector_store = vector_store
            if use_faiss:
                self.logger.warning("FAISS not available, falling back to standard vector store")

    def _create_faiss_store(self, original_store: VectorStore, faiss_config: Dict[str, Any]):
        """Create FAISS-integrated store from existing VectorStore."""
        try:
            return FAISSIntegratedVectorStore(
                session_factory=original_store.connection_pool.session_factory,
                embedding_model=original_store.embedding_model,
                faiss_index_path=faiss_config.get('index_path', './faiss_index'),
                embedding_dim=faiss_config.get('embedding_dim', 768),
                use_gpu=faiss_config.get('use_gpu', False),
                enable_monitoring=faiss_config.get('enable_monitoring', True)
            )
        except Exception as e:
            self.logger.error(f"Failed to create FAISS store, using original: {e}")
            return original_store

    async def add_document(
        self,
        content: str,
        document_id: str,
        document_type: DocumentType,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Add document to RAG system."""
        try:
            # Process document into chunks
            chunks = self.document_processor.process_document(
                content, document_id, document_type, metadata
            )

            if not chunks:
                return []

            # Add chunks to vector store
            embedding_ids = await self.vector_store.add_documents(
                chunks, workspace_id, team_id, user_id
            )

            self.logger.info(f"Added document {document_id} with {len(chunks)} chunks to RAG system")
            return embedding_ids

        except Exception as e:
            self.logger.error(f"Failed to add document to RAG system: {e}")
            raise

    async def query(
        self,
        query: str,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        document_types: Optional[List[DocumentType]] = None,
        max_results: int = 5,
        include_sources: bool = True,
        **generation_kwargs
    ) -> Dict[str, Any]:
        """Query RAG system and generate response."""
        try:
            # Retrieve relevant documents
            retrieved_chunks = await self.vector_store.similarity_search(
                query=query,
                workspace_id=workspace_id,
                team_id=team_id,
                document_types=document_types,
                limit=max_results
            )

            if not retrieved_chunks:
                # No relevant documents found, provide general response
                return {
                    "response": "I don't have specific information about that topic in this workspace. Could you provide more context or try a different question?",
                    "sources": [],
                    "confidence": 0.0,
                    "metadata": {
                        "retrieved_chunks": 0,
                        "query": query
                    }
                }

            # Build context from retrieved chunks
            context = self._build_context(retrieved_chunks)

            # Generate response using AI model
            messages = [
                ChatMessage(
                    role="system",
                    content=self._get_system_prompt()
                ),
                ChatMessage(
                    role="user",
                    content=self._build_user_prompt(query, context)
                )
            ]

            response = await self.ai_model.chat_completion(messages, **generation_kwargs)

            # Prepare result
            result = {
                "response": response.content,
                "confidence": self._calculate_confidence(retrieved_chunks),
                "metadata": {
                    "retrieved_chunks": len(retrieved_chunks),
                    "query": query,
                    "model": response.model,
                    "usage": response.usage
                }
            }

            if include_sources:
                result["sources"] = [
                    {
                        "document_id": chunk.chunk.document_id,
                        "document_type": chunk.chunk.document_type.value,
                        "content_preview": chunk.chunk.content[:200] + "..." if len(chunk.chunk.content) > 200 else chunk.chunk.content,
                        "similarity_score": chunk.similarity_score,
                        "metadata": chunk.chunk.metadata
                    }
                    for chunk in retrieved_chunks
                ]

            return result

        except Exception as e:
            self.logger.error(f"RAG query failed: {e}")
            return {
                "response": "I'm sorry, I encountered an error while processing your request. Please try again.",
                "sources": [],
                "confidence": 0.0,
                "metadata": {"error": str(e), "query": query}
            }

    def _build_context(self, retrieved_chunks: List[RetrievalResult]) -> str:
        """Build context string from retrieved chunks."""
        context_parts = []

        for i, result in enumerate(retrieved_chunks):
            chunk = result.chunk
            source_info = f"[Source {i+1}] "
            if chunk.metadata.get("title"):
                source_info += f"{chunk.metadata['title']} - "
            source_info += f"({chunk.document_type.value})"

            context_parts.append(f"{source_info}\n{chunk.content}\n")

        return "\n".join(context_parts)

    def _get_system_prompt(self) -> str:
        """Get system prompt for RAG generation."""
        return """You are an AI assistant helping users with questions about their workspace content.

You have access to relevant documents and conversations from the workspace. Use this information to provide accurate, helpful responses.

Guidelines:
- Base your answers primarily on the provided context
- If the context doesn't contain relevant information, say so clearly
- Be concise but comprehensive
- If you're not certain about something, express that uncertainty
- Cite specific sources when possible
- Focus on being helpful and accurate"""

    def _build_user_prompt(self, query: str, context: str) -> str:
        """Build user prompt combining query and context."""
        return f"""Based on the following context from the workspace, please answer the user's question.

Context:
{context}

User Question: {query}

Answer:"""

    def _calculate_confidence(self, retrieved_chunks: List[RetrievalResult]) -> float:
        """Calculate confidence score based on retrieval results."""
        if not retrieved_chunks:
            return 0.0

        # Use average similarity score as confidence indicator
        avg_similarity = sum(chunk.similarity_score for chunk in retrieved_chunks) / len(retrieved_chunks)

        # Adjust based on number of sources (more sources = higher confidence)
        source_bonus = min(len(retrieved_chunks) * 0.1, 0.3)

        return min(avg_similarity + source_bonus, 1.0)

    async def delete_document(
        self,
        document_id: str,
        workspace_id: Optional[int] = None
    ) -> int:
        """Delete document from RAG system."""
        return await self.vector_store.delete_documents([document_id], workspace_id)

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        stats = {
            "using_faiss": isinstance(self.vector_store, FAISSIntegratedVectorStore) if FAISSIntegratedVectorStore else False,
            "vector_store_type": type(self.vector_store).__name__
        }

        # Get vector store specific stats
        if hasattr(self.vector_store, 'get_stats'):
            stats.update(self.vector_store.get_stats())

        return stats

    def optimize_for_production(self) -> Dict[str, Any]:
        """Optimize RAG engine for production performance."""
        results = {
            "optimizations_applied": [],
            "performance_improvements": {}
        }

        # Optimize FAISS index if available
        if isinstance(self.vector_store, FAISSIntegratedVectorStore) if FAISSIntegratedVectorStore else False:
            try:
                if self.vector_store.optimize_index():
                    results["optimizations_applied"].append("faiss_index_optimization")
                    results["performance_improvements"]["faiss"] = "Index rebuilt for optimal performance"
            except Exception as e:
                self.logger.error(f"FAISS optimization failed: {e}")

        # Memory cleanup
        try:
            if hasattr(self.vector_store, '_cleanup_caches'):
                self.vector_store._cleanup_caches()
                results["optimizations_applied"].append("cache_cleanup")
        except Exception as e:
            self.logger.error(f"Cache cleanup failed: {e}")

        self.logger.info(f"Applied {len(results['optimizations_applied'])} optimizations")
        return results

    async def benchmark_search_performance(
        self,
        test_queries: List[str],
        workspace_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Benchmark search performance with test queries."""
        import time

        results = {
            "queries_tested": len(test_queries),
            "average_response_time_ms": 0,
            "min_response_time_ms": float('inf'),
            "max_response_time_ms": 0,
            "total_time_ms": 0,
            "using_faiss": isinstance(self.vector_store, FAISSIntegratedVectorStore) if FAISSIntegratedVectorStore else False
        }

        response_times = []

        for query in test_queries:
            start_time = time.time()

            try:
                await self.query(
                    query=query,
                    workspace_id=workspace_id,
                    max_results=5
                )

                response_time = (time.time() - start_time) * 1000  # Convert to ms
                response_times.append(response_time)

            except Exception as e:
                self.logger.error(f"Benchmark query failed: {e}")

        if response_times:
            results["average_response_time_ms"] = sum(response_times) / len(response_times)
            results["min_response_time_ms"] = min(response_times)
            results["max_response_time_ms"] = max(response_times)
            results["total_time_ms"] = sum(response_times)

        return results