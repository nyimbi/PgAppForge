"""
RAG Engine Factory with FAISS Integration

Factory methods for creating optimized RAG engines with automatic FAISS
setup and configuration for different use cases and deployment environments.
"""

import os
import logging
from typing import Optional, Dict, Any, Union
from pathlib import Path

from .rag_engine import RAGEngine, VectorStore, DocumentProcessor
from .ai_models import AIModelAdapter

# FAISS integration
try:
    from .faiss_vector_store import FAISSIntegratedVectorStore, FAISS_AVAILABLE
except ImportError:
    FAISS_AVAILABLE = False
    FAISSIntegratedVectorStore = None

logger = logging.getLogger(__name__)


class RAGConfig:
    """Configuration class for RAG engine setup."""

    def __init__(
        self,
        # Vector store configuration
        use_faiss: bool = True,
        faiss_index_path: Optional[str] = None,
        embedding_dim: int = 768,
        use_gpu: bool = False,

        # Document processing
        chunk_size: int = 1000,
        chunk_overlap: int = 200,

        # Search configuration
        similarity_threshold: float = 0.7,
        max_results: int = 5,

        # Performance tuning
        enable_monitoring: bool = True,
        max_memory_mb: int = 512,
        cache_ttl_seconds: int = 3600,
        connection_pool_size: int = 10,

        # FAISS index configuration
        faiss_index_type: str = "auto",  # "flat", "ivf", "hnsw", "auto"
        faiss_nlist: int = 100,
        faiss_nprobe: int = 10,

        **kwargs
    ):
        # Vector store settings
        self.use_faiss = use_faiss and FAISS_AVAILABLE
        self.faiss_index_path = faiss_index_path or self._get_default_index_path()
        self.embedding_dim = embedding_dim
        self.use_gpu = use_gpu and self._gpu_available()

        # Document processing
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Search settings
        self.similarity_threshold = similarity_threshold
        self.max_results = max_results

        # Performance settings
        self.enable_monitoring = enable_monitoring
        self.max_memory_mb = max_memory_mb
        self.cache_ttl_seconds = cache_ttl_seconds
        self.connection_pool_size = connection_pool_size

        # FAISS specific
        self.faiss_index_type = faiss_index_type
        self.faiss_nlist = faiss_nlist
        self.faiss_nprobe = faiss_nprobe

        # Additional configuration
        self.extra_config = kwargs

        # Validate configuration
        self._validate_config()

    def _get_default_index_path(self) -> str:
        """Get default path for FAISS index storage."""
        # Try to use application data directory
        if 'APPDATA' in os.environ:
            base_dir = Path(os.environ['APPDATA']) / 'flask-appbuilder'
        elif 'HOME' in os.environ:
            base_dir = Path(os.environ['HOME']) / '.flask-appbuilder'
        else:
            base_dir = Path('./data')

        base_dir.mkdir(parents=True, exist_ok=True)
        return str(base_dir / 'faiss_index')

    def _gpu_available(self) -> bool:
        """Check if GPU acceleration is available."""
        if not FAISS_AVAILABLE:
            return False

        try:
            import faiss
            return faiss.get_num_gpus() > 0
        except Exception:
            return False

    def _validate_config(self):
        """Validate configuration parameters."""
        if self.use_faiss and not FAISS_AVAILABLE:
            logger.warning("FAISS requested but not available, falling back to standard vector store")
            self.use_faiss = False

        if self.embedding_dim <= 0:
            raise ValueError("Embedding dimension must be positive")

        if self.chunk_size <= 0:
            raise ValueError("Chunk size must be positive")

        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError("Similarity threshold must be between 0 and 1")

    def get_faiss_config(self) -> Dict[str, Any]:
        """Get FAISS-specific configuration."""
        return {
            'index_path': self.faiss_index_path,
            'embedding_dim': self.embedding_dim,
            'use_gpu': self.use_gpu,
            'enable_monitoring': self.enable_monitoring,
            'index_type': self.faiss_index_type,
            'nlist': self.faiss_nlist,
            'nprobe': self.faiss_nprobe
        }

    def get_vector_store_config(self) -> Dict[str, Any]:
        """Get vector store configuration."""
        return {
            'max_memory_mb': self.max_memory_mb,
            'cache_ttl_seconds': self.cache_ttl_seconds,
            'connection_pool_size': self.connection_pool_size,
            'enable_monitoring': self.enable_monitoring
        }

    def get_document_processor_config(self) -> Dict[str, Any]:
        """Get document processor configuration."""
        return {
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap
        }


class RAGFactory:
    """Factory for creating optimized RAG engines."""

    @staticmethod
    def create_development_rag(
        session_factory,
        embedding_model: AIModelAdapter,
        config: Optional[RAGConfig] = None
    ) -> RAGEngine:
        """Create RAG engine optimized for development."""
        config = config or RAGConfig(
            use_faiss=True,
            use_gpu=False,  # Usually not available in dev
            max_memory_mb=256,
            chunk_size=500,
            enable_monitoring=True
        )

        return RAGFactory._create_rag_engine(session_factory, embedding_model, config)

    @staticmethod
    def create_production_rag(
        session_factory,
        embedding_model: AIModelAdapter,
        config: Optional[RAGConfig] = None
    ) -> RAGEngine:
        """Create RAG engine optimized for production."""
        config = config or RAGConfig(
            use_faiss=True,
            use_gpu=True,  # Try to use GPU if available
            max_memory_mb=1024,
            chunk_size=1000,
            chunk_overlap=200,
            similarity_threshold=0.75,
            max_results=10,
            enable_monitoring=True,
            faiss_index_type="auto",  # Let FAISS choose optimal index
            cache_ttl_seconds=7200,  # 2 hours
            connection_pool_size=20
        )

        return RAGFactory._create_rag_engine(session_factory, embedding_model, config)

    @staticmethod
    def create_high_throughput_rag(
        session_factory,
        embedding_model: AIModelAdapter,
        config: Optional[RAGConfig] = None
    ) -> RAGEngine:
        """Create RAG engine optimized for high throughput scenarios."""
        config = config or RAGConfig(
            use_faiss=True,
            use_gpu=True,
            max_memory_mb=2048,
            chunk_size=800,
            chunk_overlap=100,
            similarity_threshold=0.65,  # Slightly lower for more results
            max_results=20,
            enable_monitoring=True,
            faiss_index_type="hnsw",  # Fast approximate search
            cache_ttl_seconds=10800,  # 3 hours
            connection_pool_size=50
        )

        return RAGFactory._create_rag_engine(session_factory, embedding_model, config)

    @staticmethod
    def create_memory_efficient_rag(
        session_factory,
        embedding_model: AIModelAdapter,
        config: Optional[RAGConfig] = None
    ) -> RAGEngine:
        """Create RAG engine optimized for memory efficiency."""
        config = config or RAGConfig(
            use_faiss=True,
            use_gpu=False,  # GPU uses more memory
            max_memory_mb=128,
            chunk_size=400,
            chunk_overlap=50,
            similarity_threshold=0.7,
            max_results=5,
            enable_monitoring=True,
            faiss_index_type="ivf_pq",  # Memory-efficient index
            cache_ttl_seconds=1800,  # 30 minutes
            connection_pool_size=5
        )

        return RAGFactory._create_rag_engine(session_factory, embedding_model, config)

    @staticmethod
    def create_custom_rag(
        session_factory,
        embedding_model: AIModelAdapter,
        config: RAGConfig
    ) -> RAGEngine:
        """Create RAG engine with custom configuration."""
        return RAGFactory._create_rag_engine(session_factory, embedding_model, config)

    @staticmethod
    def _create_rag_engine(
        session_factory,
        embedding_model: AIModelAdapter,
        config: RAGConfig
    ) -> RAGEngine:
        """Internal method to create RAG engine with given configuration."""
        logger.info(f"Creating RAG engine with FAISS: {config.use_faiss}")

        # Create document processor
        doc_processor = DocumentProcessor(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap
        )

        # Create vector store
        if config.use_faiss and FAISSIntegratedVectorStore:
            vector_store = FAISSIntegratedVectorStore(
                session_factory=session_factory,
                embedding_model=embedding_model,
                faiss_index_path=config.faiss_index_path,
                embedding_dim=config.embedding_dim,
                use_gpu=config.use_gpu,
                enable_monitoring=config.enable_monitoring
            )
            logger.info(f"Created FAISS-integrated vector store at {config.faiss_index_path}")
        else:
            # Fallback to standard vector store
            from .rag_engine import MemoryMonitor, ConnectionPool, LRUCache

            memory_monitor = MemoryMonitor(max_memory_mb=config.max_memory_mb)
            connection_pool = ConnectionPool(session_factory, max_connections=config.connection_pool_size)

            vector_store = VectorStore(
                session_factory,
                embedding_model,
                enable_monitoring=config.enable_monitoring
            )
            logger.info("Created standard vector store")

        # Create RAG engine
        rag_engine = RAGEngine(
            vector_store=vector_store,
            ai_model=embedding_model,
            document_processor=doc_processor,
            use_faiss=config.use_faiss,
            faiss_config=config.get_faiss_config() if config.use_faiss else None
        )

        logger.info("RAG engine created successfully")
        return rag_engine

    @staticmethod
    def get_recommended_config(
        deployment_type: str = "production",
        expected_documents: int = 10000,
        memory_limit_mb: int = 1024,
        use_gpu: bool = False
    ) -> RAGConfig:
        """Get recommended configuration based on deployment parameters."""

        if deployment_type == "development":
            return RAGConfig(
                use_faiss=True,
                use_gpu=False,
                max_memory_mb=min(memory_limit_mb, 256),
                chunk_size=500,
                faiss_index_type="flat" if expected_documents < 1000 else "ivf"
            )

        elif deployment_type == "production":
            # Auto-select index type based on expected scale
            if expected_documents < 1000:
                index_type = "flat"
            elif expected_documents < 50000:
                index_type = "ivf"
            else:
                index_type = "hnsw"

            return RAGConfig(
                use_faiss=True,
                use_gpu=use_gpu,
                max_memory_mb=memory_limit_mb,
                chunk_size=1000,
                chunk_overlap=200,
                faiss_index_type=index_type,
                enable_monitoring=True,
                cache_ttl_seconds=7200
            )

        elif deployment_type == "high_throughput":
            return RAGConfig(
                use_faiss=True,
                use_gpu=use_gpu,
                max_memory_mb=min(memory_limit_mb, 2048),
                chunk_size=800,
                chunk_overlap=100,
                faiss_index_type="hnsw",
                similarity_threshold=0.65,
                max_results=20,
                connection_pool_size=50
            )

        else:
            # Default production configuration
            return RAGConfig()


def create_rag_from_environment(
    session_factory,
    embedding_model: AIModelAdapter
) -> RAGEngine:
    """Create RAG engine based on environment variables."""

    # Check environment for configuration
    deployment_type = os.getenv('RAG_DEPLOYMENT_TYPE', 'production')
    use_faiss = os.getenv('RAG_USE_FAISS', 'true').lower() == 'true'
    use_gpu = os.getenv('RAG_USE_GPU', 'false').lower() == 'true'
    memory_limit = int(os.getenv('RAG_MEMORY_LIMIT_MB', '1024'))
    index_path = os.getenv('RAG_FAISS_INDEX_PATH')

    config = RAGConfig(
        use_faiss=use_faiss,
        use_gpu=use_gpu,
        max_memory_mb=memory_limit,
        faiss_index_path=index_path,
        embedding_dim=int(os.getenv('RAG_EMBEDDING_DIM', '768')),
        chunk_size=int(os.getenv('RAG_CHUNK_SIZE', '1000')),
        chunk_overlap=int(os.getenv('RAG_CHUNK_OVERLAP', '200')),
        similarity_threshold=float(os.getenv('RAG_SIMILARITY_THRESHOLD', '0.7')),
        faiss_index_type=os.getenv('RAG_FAISS_INDEX_TYPE', 'auto')
    )

    logger.info(f"Creating RAG engine from environment: {deployment_type}")
    return RAGFactory._create_rag_engine(session_factory, embedding_model, config)