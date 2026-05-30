"""
FAISS-based vector store for efficient similarity search in RAG systems.

Provides high-performance vector similarity search using Facebook's FAISS library
with proper memory management, indexing strategies, and production optimizations.
"""

import os
import pickle
import logging
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import json
import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    faiss = None

from .types import DocumentChunk, RetrievalResult, DocumentType
from .models import VectorEmbedding


logger = logging.getLogger(__name__)


class IndexType(Enum):
    """FAISS index types for different use cases."""

    FLAT = "Flat"              # Exact search, best quality
    IVF_FLAT = "IVFFlat"      # Inverted file, good balance
    IVF_PQ = "IVFPQ"          # Product quantization, memory efficient
    HNSW = "HNSW"             # Hierarchical NSW, fast approximate search
    AUTO = "Auto"             # Auto-select based on collection size


@dataclass
class IndexConfig:
    """Configuration for FAISS index."""

    index_type: IndexType = IndexType.AUTO
    embedding_dim: int = 768  # Default for sentence transformers
    nlist: int = 100          # Number of clusters for IVF
    m: int = 8                # Subvector size for PQ
    nbits: int = 8           # Bits per subvector for PQ
    hnsw_m: int = 32         # Connections per element for HNSW
    ef_construction: int = 200  # HNSW construction parameter
    ef_search: int = 128      # HNSW search parameter

    def get_index_string(self, nvecs: int) -> str:
        """Get FAISS index factory string based on config and collection size."""
        if self.index_type == IndexType.AUTO:
            # Auto-select based on collection size
            if nvecs < 1000:
                return f"Flat"
            elif nvecs < 10000:
                return f"IVF{min(self.nlist, nvecs // 10)},Flat"
            elif nvecs < 100000:
                return f"IVF{min(self.nlist, nvecs // 10)},PQ{self.m}x{self.nbits}"
            else:
                return f"HNSW{self.hnsw_m}"

        elif self.index_type == IndexType.FLAT:
            return "Flat"

        elif self.index_type == IndexType.IVF_FLAT:
            return f"IVF{min(self.nlist, nvecs // 10)},Flat"

        elif self.index_type == IndexType.IVF_PQ:
            return f"IVF{min(self.nlist, nvecs // 10)},PQ{self.m}x{self.nbits}"

        elif self.index_type == IndexType.HNSW:
            return f"HNSW{self.hnsw_m}"

        else:
            return "Flat"


class FAISSVectorStore:
    """
    FAISS-based vector store with high-performance similarity search.

    Features:
    - Multiple index types (Flat, IVF, PQ, HNSW)
    - Automatic index selection based on data size
    - Persistent storage and loading
    - Thread-safe operations
    - Memory-efficient batch processing
    - GPU support (when available)
    """

    def __init__(
        self,
        session_factory,
        embedding_dim: int = 768,
        index_config: Optional[IndexConfig] = None,
        index_path: Optional[str] = None,
        use_gpu: bool = False,
        enable_monitoring: bool = True
    ):
        self.session_factory = session_factory
        self.embedding_dim = embedding_dim
        self.index_config = index_config or IndexConfig(embedding_dim=embedding_dim)
        self.use_gpu = use_gpu and FAISS_AVAILABLE and faiss.get_num_gpus() > 0
        self.logger = logging.getLogger(__name__ + ".FAISSVectorStore")

        # Check FAISS availability and provide graceful fallback
        if not FAISS_AVAILABLE:
            self.logger.warning(
                "FAISS not available. FAISSVectorStore will operate in fallback mode. "
                "Install FAISS with: pip install faiss-cpu or pip install faiss-gpu"
            )
            self._initialize_fallback_mode()
            return

        # Normal FAISS initialization
        # Index storage
        self.index: Optional[faiss.Index] = None
        self.document_map: Dict[int, Dict[str, Any]] = {}  # FAISS ID -> document info
        self.id_counter = 0
        self.index_path = index_path

        # Thread safety
        self.lock = threading.RLock()

        # Performance tracking
        self.search_times = []
        self.index_times = []

        # Initialize index
        self._initialize_index()

        # Load existing index if available
        if self.index_path and os.path.exists(self.index_path):
            self.load_index()
    
    def _initialize_fallback_mode(self):
        """Initialize fallback mode when FAISS is not available."""
        self.index = None
        self.document_map = {}
        self.id_counter = 0
        self.index_path = None
        self.use_gpu = False
        self.lock = threading.RLock()
        self.search_times = []
        self.index_times = []
        self._fallback_mode = True
        
        self.logger.info("FAISSVectorStore initialized in fallback mode (no FAISS operations will be performed)")

    def _initialize_index(self):
        """Initialize empty FAISS index."""
        with self.lock:
            # Start with Flat index, will rebuild when we have data
            if self.use_gpu:
                res = faiss.StandardGpuResources()
                self.index = faiss.GpuIndexFlatL2(res, self.embedding_dim)
                self.logger.info("Initialized GPU FAISS index")
            else:
                self.index = faiss.IndexFlatL2(self.embedding_dim)
                self.logger.info("Initialized CPU FAISS index")

            self.document_map = {}
            self.id_counter = 0

    def _rebuild_index_if_needed(self) -> bool:
        """Rebuild index with optimal configuration based on current size."""
        if not self.index or self.index.ntotal == 0:
            return False

        current_size = self.index.ntotal

        # Check if we should rebuild for better performance
        should_rebuild = False

        if (isinstance(self.index, faiss.IndexFlatL2) or
            isinstance(self.index, faiss.GpuIndexFlatL2)) and current_size > 1000:
            should_rebuild = True
            self.logger.info(f"Rebuilding index for better performance with {current_size} vectors")

        if not should_rebuild:
            return False

        try:
            # Get all vectors from current index
            all_vectors = np.zeros((current_size, self.embedding_dim), dtype=np.float32)
            for i in range(current_size):
                all_vectors[i] = self.index.reconstruct(i)

            # Create optimized index
            index_string = self.index_config.get_index_string(current_size)
            new_index = faiss.index_factory(self.embedding_dim, index_string)

            # Configure HNSW parameters if applicable
            if "HNSW" in index_string:
                faiss.ParameterSpace().set_index_parameters(
                    new_index,
                    f"efConstruction={self.index_config.ef_construction},efSearch={self.index_config.ef_search}"
                )

            # Train index if needed (for IVF variants)
            if hasattr(new_index, 'is_trained') and not new_index.is_trained:
                self.logger.info("Training FAISS index...")
                new_index.train(all_vectors)

            # Add vectors to new index
            new_index.add(all_vectors)

            # Move to GPU if configured
            if self.use_gpu and not hasattr(new_index, 'getResources'):
                res = faiss.StandardGpuResources()
                new_index = faiss.index_cpu_to_gpu(res, 0, new_index)

            self.index = new_index
            self.logger.info(f"Successfully rebuilt index as {index_string} with {current_size} vectors")
            return True

        except Exception as e:
            self.logger.error(f"Failed to rebuild index: {e}")
            return False

    def add_vectors(
        self,
        embeddings: np.ndarray,
        metadata_list: List[Dict[str, Any]]
    ) -> List[int]:
        """Add vectors to FAISS index with metadata."""
        if embeddings.shape[0] != len(metadata_list):
            raise ValueError("Number of embeddings must match metadata list length")

        if embeddings.shape[1] != self.embedding_dim:
            raise ValueError(f"Embedding dimension {embeddings.shape[1]} doesn't match expected {self.embedding_dim}")

        # Fallback mode - return mock IDs without actually storing anything
        if hasattr(self, '_fallback_mode') and self._fallback_mode:
            self.logger.debug(f"FAISS fallback mode: Skipping storage of {len(embeddings)} vectors")
            # Return mock IDs
            start_id = self.id_counter
            faiss_ids = list(range(start_id, start_id + len(embeddings)))
            self.id_counter += len(embeddings)
            return faiss_ids

        with self.lock:
            start_time = time.time()

            # Ensure vectors are float32 (FAISS requirement)
            embeddings = embeddings.astype(np.float32)

            # Get starting IDs for new vectors
            start_id = self.id_counter
            faiss_ids = list(range(start_id, start_id + len(embeddings)))

            # Add vectors to index
            self.index.add(embeddings)

            # Store metadata mapping
            for i, metadata in enumerate(metadata_list):
                self.document_map[start_id + i] = metadata

            self.id_counter += len(embeddings)

            # Track timing
            add_time = time.time() - start_time
            self.index_times.append(add_time)

            self.logger.info(f"Added {len(embeddings)} vectors to FAISS index in {add_time:.3f}s")

            # Rebuild index for better performance if needed
            self._rebuild_index_if_needed()

            return faiss_ids

    def search(
        self,
        query_vector: np.ndarray,
        k: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[Tuple[int, float]]:
        """Search for similar vectors using FAISS."""
        # Fallback mode - return empty results
        if hasattr(self, '_fallback_mode') and self._fallback_mode:
            self.logger.debug("FAISS fallback mode: Returning empty search results")
            return []

        if self.index.ntotal == 0:
            return []

        with self.lock:
            start_time = time.time()

            # Ensure query is correct shape and type
            if query_vector.ndim == 1:
                query_vector = query_vector.reshape(1, -1)
            query_vector = query_vector.astype(np.float32)

            # Perform search
            distances, indices = self.index.search(query_vector, min(k, self.index.ntotal))

            # Convert distances to similarity scores (cosine similarity)
            # FAISS L2 distance: d = ||a-b||^2 = ||a||^2 + ||b||^2 - 2*a·b
            # For normalized vectors: similarity = 1 - d/2
            similarities = 1 - distances[0] / 2

            # Filter results by threshold and valid indices
            results = []
            for idx, sim in zip(indices[0], similarities):
                if idx != -1 and sim >= similarity_threshold:  # -1 indicates no result
                    results.append((int(idx), float(sim)))

            # Track search time
            search_time = time.time() - start_time
            self.search_times.append(search_time)

            self.logger.debug(f"FAISS search took {search_time:.4f}s, found {len(results)} results")
            return results

    def get_metadata(self, faiss_id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a FAISS vector ID."""
        return self.document_map.get(faiss_id)

    def remove_vectors(self, faiss_ids: List[int]) -> int:
        """Remove vectors from index (limited FAISS support)."""
        # Note: FAISS doesn't support efficient removal from most index types
        # This would require rebuilding the index without these vectors
        # For now, we'll just remove from metadata and mark as removed

        removed_count = 0
        with self.lock:
            for faiss_id in faiss_ids:
                if faiss_id in self.document_map:
                    self.document_map[faiss_id]["_removed"] = True
                    removed_count += 1

        self.logger.warning(f"Marked {removed_count} vectors as removed (FAISS doesn't support efficient deletion)")
        return removed_count

    def save_index(self, path: Optional[str] = None) -> str:
        """Save FAISS index and metadata to disk."""
        save_path = path or self.index_path
        if not save_path:
            raise ValueError("No path specified for saving index")

        # Fallback mode - just log and return path
        if hasattr(self, '_fallback_mode') and self._fallback_mode:
            self.logger.info(f"FAISS fallback mode: Skipping index save to {save_path}")
            return save_path

        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with self.lock:
            try:
                # Save FAISS index
                index_file = f"{save_path}.index"

                if self.use_gpu and hasattr(self.index, 'getResources'):
                    # Move to CPU for saving
                    cpu_index = faiss.index_gpu_to_cpu(self.index)
                    faiss.write_index(cpu_index, index_file)
                else:
                    faiss.write_index(self.index, index_file)

                # Save metadata
                metadata_file = f"{save_path}.metadata"
                with open(metadata_file, 'wb') as f:
                    pickle.dump({
                        'document_map': self.document_map,
                        'id_counter': self.id_counter,
                        'embedding_dim': self.embedding_dim,
                        'index_config': self.index_config
                    }, f)

                self.logger.info(f"Saved FAISS index with {self.index.ntotal} vectors to {save_path}")
                return save_path

            except Exception as e:
                self.logger.error(f"Failed to save FAISS index: {e}")
                raise

    def load_index(self, path: Optional[str] = None) -> bool:
        """Load FAISS index and metadata from disk."""
        load_path = path or self.index_path
        if not load_path:
            raise ValueError("No path specified for loading index")

        # Fallback mode - just log and return False
        if hasattr(self, '_fallback_mode') and self._fallback_mode:
            self.logger.info(f"FAISS fallback mode: Skipping index load from {load_path}")
            return False

        index_file = f"{load_path}.index"
        metadata_file = f"{load_path}.metadata"

        if not (os.path.exists(index_file) and os.path.exists(metadata_file)):
            self.logger.warning(f"Index files not found at {load_path}")
            return False

        with self.lock:
            try:
                # Load FAISS index
                cpu_index = faiss.read_index(index_file)

                if self.use_gpu and faiss.get_num_gpus() > 0:
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, 0, cpu_index)
                else:
                    self.index = cpu_index

                # Load metadata
                with open(metadata_file, 'rb') as f:
                    metadata = pickle.load(f)
                    self.document_map = metadata['document_map']
                    self.id_counter = metadata['id_counter']
                    self.embedding_dim = metadata['embedding_dim']
                    self.index_config = metadata.get('index_config', self.index_config)

                self.logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors from {load_path}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to load FAISS index: {e}")
                return False

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the vector store."""
        with self.lock:
            active_vectors = sum(1 for meta in self.document_map.values() if not meta.get("_removed", False))

            # Calculate average search time
            avg_search_time = sum(self.search_times[-100:]) / len(self.search_times[-100:]) if self.search_times else 0
            avg_index_time = sum(self.index_times[-100:]) / len(self.index_times[-100:]) if self.index_times else 0

            return {
                "total_vectors": self.index.ntotal if self.index else 0,
                "active_vectors": active_vectors,
                "removed_vectors": len(self.document_map) - active_vectors,
                "embedding_dimension": self.embedding_dim,
                "index_type": type(self.index).__name__ if self.index else None,
                "using_gpu": self.use_gpu and hasattr(self.index, 'getResources') if self.index else False,
                "average_search_time_ms": avg_search_time * 1000,
                "average_index_time_ms": avg_index_time * 1000,
                "total_searches": len(self.search_times),
                "memory_usage_mb": self._estimate_memory_usage()
            }

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB."""
        if not self.index:
            return 0.0

        # Rough estimates based on FAISS documentation
        vector_memory = self.index.ntotal * self.embedding_dim * 4 / (1024 * 1024)  # 4 bytes per float32
        metadata_memory = len(self.document_map) * 1024 / (1024 * 1024)  # ~1KB per metadata entry

        return vector_memory + metadata_memory

    def optimize_index(self) -> bool:
        """Optimize index for better search performance."""
        with self.lock:
            if not self.index or self.index.ntotal < 1000:
                return False

            self.logger.info("Optimizing FAISS index for better performance...")
            return self._rebuild_index_if_needed()

    def clear(self):
        """Clear all vectors and metadata."""
        with self.lock:
            self._initialize_index()
            self.logger.info("Cleared all vectors from FAISS index")


class FAISSIntegratedVectorStore:
    """
    Integration wrapper that combines FAISS with database storage.

    Provides the same interface as the original VectorStore but uses FAISS
    for high-performance similarity search while maintaining database integration.
    """

    def __init__(
        self,
        session_factory,
        embedding_model,
        faiss_index_path: Optional[str] = None,
        embedding_dim: int = 768,
        use_gpu: bool = False,
        enable_monitoring: bool = True
    ):
        self.session_factory = session_factory
        self.embedding_model = embedding_model
        self.logger = logging.getLogger(__name__ + ".FAISSIntegratedVectorStore")

        # Initialize FAISS store
        self.faiss_store = FAISSVectorStore(
            session_factory=session_factory,
            embedding_dim=embedding_dim,
            index_path=faiss_index_path,
            use_gpu=use_gpu,
            enable_monitoring=enable_monitoring
        )

        # Sync FAISS index with database on startup
        self._sync_with_database()

    def _sync_with_database(self):
        """Sync FAISS index with database records."""
        try:
            session = self.session_factory()

            # Get all embeddings from database
            embeddings = session.query(VectorEmbedding).all()

            if not embeddings:
                self.logger.info("No embeddings found in database")
                return

            # Check if FAISS index needs rebuilding
            if self.faiss_store.index.ntotal != len(embeddings):
                self.logger.info(f"Rebuilding FAISS index: DB has {len(embeddings)}, FAISS has {self.faiss_store.index.ntotal}")

                # Rebuild FAISS index from database
                vectors = []
                metadata_list = []

                for embedding in embeddings:
                    vector = embedding.get_embedding_vector()
                    if vector and len(vector) == self.faiss_store.embedding_dim:
                        vectors.append(vector)
                        metadata_list.append({
                            'db_id': embedding.id,
                            'document_id': embedding.document_id,
                            'document_type': embedding.document_type,
                            'chunk_index': embedding.chunk_index,
                            'content': embedding.content,
                            'metadata': embedding.get_metadata(),
                            'workspace_id': embedding.workspace_id,
                            'team_id': embedding.team_id,
                            'user_id': embedding.user_id
                        })

                if vectors:
                    # Clear and rebuild FAISS index
                    self.faiss_store.clear()
                    vectors_array = np.array(vectors, dtype=np.float32)
                    self.faiss_store.add_vectors(vectors_array, metadata_list)

                    self.logger.info(f"Rebuilt FAISS index with {len(vectors)} vectors")

        except Exception as e:
            self.logger.error(f"Failed to sync FAISS with database: {e}")
        finally:
            session.close()

    async def add_documents(
        self,
        chunks: List[DocumentChunk],
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        user_id: Optional[int] = None
    ) -> List[str]:
        """Add document chunks using FAISS for vector storage."""
        try:
            # Generate embeddings
            contents = [chunk.content for chunk in chunks]
            embeddings = await self.embedding_model.generate_embeddings(contents)

            session = self.session_factory()
            db_ids = []
            vectors = []
            metadata_list = []

            for chunk, embedding in zip(chunks, embeddings):
                # Store in database
                content_hash = chunk.get_content_hash()

                # Check for existing embedding
                existing = session.query(VectorEmbedding).filter_by(
                    content_hash=content_hash,
                    workspace_id=workspace_id
                ).first()

                if existing:
                    db_ids.append(str(existing.id))
                    continue

                # Create database record
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
                session.flush()

                db_ids.append(str(vector_embedding.id))

                # Prepare for FAISS
                vectors.append(embedding)
                metadata_list.append({
                    'db_id': vector_embedding.id,
                    'document_id': chunk.document_id,
                    'document_type': chunk.document_type.value,
                    'chunk_index': chunk.chunk_index,
                    'content': chunk.content,
                    'metadata': chunk.metadata,
                    'workspace_id': workspace_id,
                    'team_id': team_id,
                    'user_id': user_id
                })

            session.commit()

            # Add to FAISS index
            if vectors:
                vectors_array = np.array(vectors, dtype=np.float32)
                self.faiss_store.add_vectors(vectors_array, metadata_list)

            self.logger.info(f"Added {len(db_ids)} documents to integrated vector store")
            return db_ids

        except Exception as e:
            if session:
                session.rollback()
            self.logger.error(f"Failed to add documents: {e}")
            raise
        finally:
            if session:
                session.close()

    async def similarity_search(
        self,
        query: str,
        workspace_id: Optional[int] = None,
        team_id: Optional[int] = None,
        document_types: Optional[List[DocumentType]] = None,
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> List[RetrievalResult]:
        """High-performance similarity search using FAISS."""
        try:
            # Generate query embedding
            query_embeddings = await self.embedding_model.generate_embeddings([query])
            query_vector = np.array(query_embeddings[0], dtype=np.float32)

            # Search using FAISS
            faiss_results = self.faiss_store.search(
                query_vector,
                k=limit * 2,  # Get more results to allow for filtering
                similarity_threshold=similarity_threshold
            )

            # Convert FAISS results to RetrievalResult objects with filtering
            results = []

            for faiss_id, similarity_score in faiss_results:
                metadata = self.faiss_store.get_metadata(faiss_id)
                if not metadata or metadata.get("_removed"):
                    continue

                # Apply filters
                if workspace_id and metadata.get('workspace_id') != workspace_id:
                    continue

                if team_id and metadata.get('team_id') != team_id:
                    continue

                if document_types:
                    doc_type = metadata.get('document_type')
                    if doc_type not in [dt.value for dt in document_types]:
                        continue

                # Create DocumentChunk from metadata
                chunk = DocumentChunk(
                    content=metadata['content'],
                    metadata=metadata.get('metadata', {}),
                    chunk_index=metadata['chunk_index'],
                    document_id=metadata['document_id'],
                    document_type=DocumentType(metadata['document_type'])
                )

                result = RetrievalResult(
                    chunk=chunk,
                    similarity_score=similarity_score,
                    metadata={
                        "db_id": metadata['db_id'],
                        "faiss_id": faiss_id,
                        "content_length": len(metadata['content'])
                    }
                )

                results.append(result)

                if len(results) >= limit:
                    break

            self.logger.debug(f"FAISS similarity search returned {len(results)} results")
            return results

        except Exception as e:
            self.logger.error(f"FAISS similarity search failed: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics from both FAISS and database."""
        faiss_stats = self.faiss_store.get_stats()

        try:
            session = self.session_factory()
            db_count = session.query(VectorEmbedding).count()
            session.close()
        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            db_count = 0

        return {
            **faiss_stats,
            "database_embeddings": db_count,
            "integration_status": "active"
        }

    def save_index(self, path: Optional[str] = None) -> str:
        """Save FAISS index to disk."""
        return self.faiss_store.save_index(path)

    def optimize_index(self) -> bool:
        """Optimize FAISS index for better performance."""
        return self.faiss_store.optimize_index()

    def shutdown(self):
        """Shutdown the integrated vector store."""
        # Save index before shutdown
        if self.faiss_store.index_path:
            try:
                self.faiss_store.save_index()
            except Exception as e:
                self.logger.error(f"Failed to save index during shutdown: {e}")

        self.logger.info("FAISS integrated vector store shutdown completed")