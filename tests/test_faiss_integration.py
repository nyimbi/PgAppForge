"""
Comprehensive tests for FAISS integration with RAG system.

Tests cover performance benchmarks, index types, GPU acceleration,
persistence, and compatibility with the existing PgAppForge framework.
"""

import os
import time
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any

# PgAppForge imports
from flask import Flask
from pgappforge import AppBuilder
from pgappforge.models.sqla import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# RAG system imports
from pgappforge.collaborative.ai.rag_engine import (
    RAGEngine, VectorStore, DocumentProcessor, DocumentChunk,
    DocumentType, ChunkingStrategy, MemoryMonitor, ConnectionPool, LRUCache
)
from pgappforge.collaborative.ai.rag_factory import RAGFactory, RAGConfig
from pgappforge.collaborative.ai.ai_models import AIModelAdapter, ChatMessage, ModelResponse

# Test if FAISS is available
try:
    from pgappforge.collaborative.ai.faiss_vector_store import (
        FAISSVectorStore, FAISSIntegratedVectorStore, IndexConfig, FAISS_AVAILABLE
    )
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    FAISSVectorStore = None
    FAISSIntegratedVectorStore = None
    IndexConfig = None


class MockEmbeddingModel(AIModelAdapter):
    """Mock AI model for testing purposes."""

    def __init__(self, embedding_dim: int = 768):
        self.embedding_dim = embedding_dim

    async def get_embedding(self, text: str) -> List[float]:
        """Generate mock embedding based on text hash."""
        import hashlib
        # Create deterministic embedding from text hash
        hash_obj = hashlib.md5(text.encode())
        hash_int = int(hash_obj.hexdigest(), 16)

        # Generate embedding vector
        embedding = []
        for i in range(self.embedding_dim):
            embedding.append(((hash_int >> (i % 32)) & 1) * 2.0 - 1.0)

        # Normalize to unit vector
        norm = sum(x * x for x in embedding) ** 0.5
        return [x / norm for x in embedding] if norm > 0 else embedding

    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Mock chat completion."""
        return ModelResponse(
            content="Mock response based on retrieved context.",
            model="mock-model",
            usage={"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20}
        )


class TestFAISSIntegration(unittest.TestCase):
    """Test suite for FAISS integration with RAG system."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.temp_dir, "test.db")
        cls.faiss_index_path = os.path.join(cls.temp_dir, "faiss_test_index")

        # Create Flask app and SQLAlchemy setup
        cls.app = Flask(__name__)
        cls.app.config["SECRET_KEY"] = "test_secret_key_for_faiss_testing"
        cls.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{cls.db_path}"
        cls.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        # Create database engine and session factory
        cls.engine = create_engine(f"sqlite:///{cls.db_path}", echo=False)
        cls.session_factory = sessionmaker(bind=cls.engine)

        # Create mock AI model
        cls.mock_ai_model = MockEmbeddingModel()

        # Test data
        cls.test_documents = [
            {
                "content": "PgAppForge is a rapid application development framework built on Flask.",
                "document_id": "doc1",
                "document_type": DocumentType.TEXT,
                "metadata": {"title": "PgAppForge Overview"}
            },
            {
                "content": "FAISS (Facebook AI Similarity Search) is a library for efficient similarity search and clustering of dense vectors.",
                "document_id": "doc2",
                "document_type": DocumentType.TEXT,
                "metadata": {"title": "FAISS Introduction"}
            },
            {
                "content": "Vector databases enable semantic search by storing and querying high-dimensional embeddings.",
                "document_id": "doc3",
                "document_type": DocumentType.TEXT,
                "metadata": {"title": "Vector Database Concepts"}
            },
            {
                "content": """
                def calculate_similarity(embedding1, embedding2):
                    '''Calculate cosine similarity between two embeddings.'''
                    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
                    norm1 = sum(a * a for a in embedding1) ** 0.5
                    norm2 = sum(b * b for b in embedding2) ** 0.5
                    return dot_product / (norm1 * norm2) if norm1 * norm2 > 0 else 0
                """,
                "document_id": "doc4",
                "document_type": DocumentType.CODE,
                "metadata": {"title": "Similarity Calculation", "language": "python"}
            },
            {
                "content": "<h1>Machine Learning Embeddings</h1><p>Embeddings are dense vector representations of text, images, or other data types that capture semantic relationships.</p>",
                "document_id": "doc5",
                "document_type": DocumentType.HTML,
                "metadata": {"title": "ML Embeddings"}
            }
        ]

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment."""
        try:
            shutil.rmtree(cls.temp_dir)
        except Exception as e:
            print(f"Warning: Could not clean up temp directory: {e}")

    def setUp(self):
        """Set up each test."""
        # Create tables
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        """Clean up after each test."""
        # Drop tables
        Base.metadata.drop_all(self.engine)

        # Clean up FAISS index files
        if os.path.exists(self.faiss_index_path):
            try:
                shutil.rmtree(self.faiss_index_path)
            except Exception:
                pass

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    def test_faiss_vector_store_creation(self):
        """Test FAISS vector store can be created and configured."""
        config = IndexConfig(
            index_type="Flat",
            embedding_dim=768,
            use_gpu=False
        )

        store = FAISSVectorStore(
            session_factory=self.session_factory,
            embedding_dim=768,
            index_config=config,
            index_path=self.faiss_index_path
        )

        self.assertIsNotNone(store)
        self.assertEqual(store.embedding_dim, 768)
        self.assertFalse(store.use_gpu)
        self.assertEqual(store.index_config.index_type, "Flat")

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_faiss_integrated_vector_store(self):
        """Test FAISS integrated vector store with database sync."""
        store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        # Add test documents
        for doc in self.test_documents[:3]:  # Use first 3 for quick test
            chunks = await store.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )
            self.assertGreater(len(chunks), 0)

        # Test search
        results = await store.similarity_search(
            query="Flask application framework",
            limit=2
        )

        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 2)

        # Verify results contain expected document
        found_flask_doc = any(
            result.chunk.document_id == "doc1" for result in results
        )
        self.assertTrue(found_flask_doc, "Should find PgAppForge document")

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    def test_rag_factory_faiss_configurations(self):
        """Test RAG factory creates different FAISS configurations."""

        # Test development configuration
        dev_rag = RAGFactory.create_development_rag(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model
        )
        self.assertIsNotNone(dev_rag)

        # Test production configuration
        prod_rag = RAGFactory.create_production_rag(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model
        )
        self.assertIsNotNone(prod_rag)

        # Test high-throughput configuration
        ht_rag = RAGFactory.create_high_throughput_rag(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model
        )
        self.assertIsNotNone(ht_rag)

        # Test memory-efficient configuration
        mem_rag = RAGFactory.create_memory_efficient_rag(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model
        )
        self.assertIsNotNone(mem_rag)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    def test_rag_config_validation(self):
        """Test RAG configuration validation."""

        # Valid configuration
        config = RAGConfig(
            use_faiss=True,
            embedding_dim=768,
            chunk_size=1000,
            similarity_threshold=0.7
        )
        self.assertTrue(config.use_faiss)
        self.assertEqual(config.embedding_dim, 768)

        # Invalid embedding dimension
        with self.assertRaises(ValueError):
            RAGConfig(embedding_dim=0)

        # Invalid chunk size
        with self.assertRaises(ValueError):
            RAGConfig(chunk_size=-100)

        # Invalid similarity threshold
        with self.assertRaises(ValueError):
            RAGConfig(similarity_threshold=1.5)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_faiss_index_persistence(self):
        """Test FAISS index can be saved and loaded."""

        # Create store and add documents
        store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        # Add documents
        for doc in self.test_documents[:2]:
            await store.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )

        # Save index
        save_success = store.save_index()
        self.assertTrue(save_success, "Index should be saved successfully")

        # Verify index files exist
        index_files = os.listdir(self.faiss_index_path)
        self.assertGreater(len(index_files), 0, "Index files should exist")

        # Create new store and load index
        store2 = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        load_success = store2.load_index()
        self.assertTrue(load_success, "Index should be loaded successfully")

        # Test search on loaded index
        results = await store2.similarity_search(
            query="application development",
            limit=1
        )
        self.assertGreater(len(results), 0, "Should find results from loaded index")

    def test_document_processor_enhancements(self):
        """Test enhanced document processing capabilities."""

        # Test different chunking strategies
        strategies = [
            ChunkingStrategy.SENTENCE_BOUNDARY,
            ChunkingStrategy.PARAGRAPH_BOUNDARY,
            ChunkingStrategy.FIXED_SIZE,
            ChunkingStrategy.CODE_BLOCKS
        ]

        for strategy in strategies:
            processor = DocumentProcessor(
                chunk_size=500,
                chunk_overlap=100,
                chunking_strategy=strategy,
                enable_preprocessing=True
            )

            # Test HTML processing
            html_chunks = processor.process_document(
                content=self.test_documents[4]["content"],
                document_id=self.test_documents[4]["document_id"],
                document_type=self.test_documents[4]["document_type"],
                metadata=self.test_documents[4]["metadata"]
            )
            self.assertGreater(len(html_chunks), 0)

            # Verify metadata extraction
            chunk = html_chunks[0]
            self.assertIn("content_type", chunk.metadata)
            self.assertEqual(chunk.metadata["content_type"], "html")

            # Test code processing
            code_chunks = processor.process_document(
                content=self.test_documents[3]["content"],
                document_id=self.test_documents[3]["document_id"],
                document_type=self.test_documents[3]["document_type"],
                metadata=self.test_documents[3]["metadata"]
            )
            self.assertGreater(len(code_chunks), 0)

            # Verify code-specific metadata
            code_chunk = code_chunks[0]
            self.assertIn("content_type", code_chunk.metadata)
            self.assertEqual(code_chunk.metadata["content_type"], "code")
            self.assertIn("programming_language", code_chunk.metadata)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_performance_benchmarking(self):
        """Test performance benchmarking functionality."""

        # Create RAG engine with FAISS
        rag_engine = RAGFactory.create_production_rag(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model
        )

        # Add test documents
        for doc in self.test_documents:
            await rag_engine.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )

        # Run benchmark
        test_queries = [
            "What is PgAppForge?",
            "How does FAISS work?",
            "Vector database applications",
            "Python similarity calculation",
            "Machine learning embeddings"
        ]

        benchmark_results = await rag_engine.benchmark_search_performance(
            test_queries=test_queries
        )

        # Verify benchmark results
        self.assertEqual(benchmark_results["queries_tested"], len(test_queries))
        self.assertGreater(benchmark_results["average_response_time_ms"], 0)
        self.assertTrue(benchmark_results["using_faiss"])
        self.assertIn("total_time_ms", benchmark_results)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_faiss_vs_standard_performance_comparison(self):
        """Compare performance between FAISS and standard vector store."""

        # Create standard vector store
        standard_store = VectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            enable_monitoring=False
        )

        # Create FAISS-integrated store
        faiss_store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        # Add same documents to both stores
        for doc in self.test_documents:
            await standard_store.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )
            await faiss_store.add_document(
                content=doc["content"],
                document_id=doc["document_id"] + "_faiss",
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )

        # Benchmark search performance
        test_queries = ["Flask application", "vector similarity", "machine learning"]

        # Time standard search
        start_time = time.time()
        for query in test_queries:
            await standard_store.similarity_search(query, limit=3)
        standard_time = time.time() - start_time

        # Time FAISS search
        start_time = time.time()
        for query in test_queries:
            await faiss_store.similarity_search(query, limit=3)
        faiss_time = time.time() - start_time

        # Log performance comparison
        performance_ratio = standard_time / faiss_time if faiss_time > 0 else float('inf')

        print(f"\nPerformance Comparison:")
        print(f"Standard Vector Store: {standard_time:.4f}s")
        print(f"FAISS Vector Store: {faiss_time:.4f}s")
        print(f"Performance Ratio: {performance_ratio:.2f}x")

        # FAISS should generally be faster, but this depends on data size
        # For small datasets, the overhead might make it slower
        self.assertGreater(standard_time, 0)
        self.assertGreater(faiss_time, 0)

    def test_memory_monitoring_integration(self):
        """Test memory monitoring with FAISS integration."""

        monitor = MemoryMonitor(max_memory_mb=256, check_interval=1)

        # Test memory monitoring functionality
        usage = monitor.get_memory_usage()
        self.assertIn("rss_mb", usage)
        self.assertIn("vms_mb", usage)
        self.assertIn("percent", usage)
        self.assertIn("available_mb", usage)

        # Test pressure detection
        is_pressure = monitor.is_memory_pressure()
        self.assertIsInstance(is_pressure, bool)

        # Test cleanup callback registration
        cleanup_called = []
        def test_cleanup():
            cleanup_called.append(True)

        monitor.register_cleanup_callback(test_cleanup)
        self.assertEqual(len(monitor.callbacks), 1)

    def test_lru_cache_functionality(self):
        """Test LRU cache used in vector stores."""

        cache = LRUCache(max_size=3, ttl_seconds=1)

        # Test basic operations
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        self.assertEqual(cache.get("key1"), "value1")
        self.assertEqual(cache.get("key2"), "value2")
        self.assertEqual(cache.get("key3"), "value3")

        # Test size limit (should evict oldest)
        cache.put("key4", "value4")
        self.assertIsNone(cache.get("key1"))  # Should be evicted
        self.assertEqual(cache.get("key4"), "value4")

        # Test TTL expiration
        time.sleep(1.1)  # Wait for TTL to expire
        self.assertIsNone(cache.get("key2"))

        # Test cache statistics
        stats = cache.get_stats()
        self.assertIn("size", stats)
        self.assertIn("hits", stats)
        self.assertIn("misses", stats)
        self.assertIn("hit_rate", stats)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    def test_faiss_gpu_detection(self):
        """Test GPU detection and configuration."""

        config = RAGConfig(use_gpu=True)  # Will be set to False if GPU not available

        # Test GPU availability detection
        gpu_available = config._gpu_available()
        self.assertIsInstance(gpu_available, bool)

        # If GPU is available, test GPU configuration
        if gpu_available:
            print(f"\nGPU detected: {gpu_available}")
            gpu_config = RAGConfig(use_gpu=True)
            self.assertTrue(gpu_config.use_gpu)
        else:
            print(f"\nNo GPU available for testing")
            # Should fall back to CPU
            cpu_config = RAGConfig(use_gpu=True)  # Will be set to False internally
            self.assertFalse(cpu_config.use_gpu)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    def test_index_optimization(self):
        """Test FAISS index optimization functionality."""

        store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        # Test optimization on empty index
        optimization_result = store.optimize_index()
        self.assertIsInstance(optimization_result, bool)

    def test_environment_configuration(self):
        """Test environment-based RAG configuration."""

        # Set environment variables
        os.environ["RAG_DEPLOYMENT_TYPE"] = "production"
        os.environ["RAG_USE_FAISS"] = "true"
        os.environ["RAG_USE_GPU"] = "false"
        os.environ["RAG_MEMORY_LIMIT_MB"] = "512"
        os.environ["RAG_CHUNK_SIZE"] = "800"

        try:
            from pgappforge.collaborative.ai.rag_factory import create_rag_from_environment

            rag_engine = create_rag_from_environment(
                session_factory=self.session_factory,
                embedding_model=self.mock_ai_model
            )

            self.assertIsNotNone(rag_engine)

        finally:
            # Clean up environment variables
            for key in ["RAG_DEPLOYMENT_TYPE", "RAG_USE_FAISS", "RAG_USE_GPU",
                       "RAG_MEMORY_LIMIT_MB", "RAG_CHUNK_SIZE"]:
                os.environ.pop(key, None)

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_faiss_error_handling(self):
        """Test error handling in FAISS integration."""

        # Test with invalid index path
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_path = os.path.join(temp_dir, "nonexistent", "path")

            store = FAISSIntegratedVectorStore(
                session_factory=self.session_factory,
                embedding_model=self.mock_ai_model,
                faiss_index_path=invalid_path,
                embedding_dim=768,
                use_gpu=False,
                enable_monitoring=False
            )

            # Should handle path creation gracefully
            self.assertIsNotNone(store)

        # Test search with empty index
        empty_store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        results = await empty_store.similarity_search("test query", limit=5)
        self.assertEqual(len(results), 0)


class TestFAISSIntegrationPerformance(unittest.TestCase):
    """Performance-focused tests for FAISS integration."""

    def setUp(self):
        """Set up performance testing environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "perf_test.db")
        self.faiss_index_path = os.path.join(self.temp_dir, "faiss_perf_index")

        # Create engine and session factory
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self.session_factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        # Mock AI model
        self.mock_ai_model = MockEmbeddingModel()

    def tearDown(self):
        """Clean up performance test environment."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Warning: Could not clean up temp directory: {e}")

    @unittest.skipUnless(HAS_FAISS, "FAISS not available")
    async def test_large_dataset_performance(self):
        """Test FAISS performance with larger dataset."""

        # Create FAISS store
        store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.mock_ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=False,
            enable_monitoring=False
        )

        # Generate test documents
        large_dataset = []
        for i in range(100):  # 100 documents for performance testing
            content = f"This is test document number {i}. " * 10  # Make it longer
            large_dataset.append({
                "content": content,
                "document_id": f"perf_doc_{i}",
                "document_type": DocumentType.TEXT,
                "metadata": {"test_id": i}
            })

        # Measure insertion time
        start_time = time.time()
        for doc in large_dataset[:50]:  # First 50 docs
            await store.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )
        insertion_time = time.time() - start_time

        # Measure search time
        search_queries = ["test document", "number", "performance test"]
        start_time = time.time()
        for query in search_queries:
            await store.similarity_search(query, limit=10)
        search_time = time.time() - start_time

        print(f"\nLarge Dataset Performance:")
        print(f"Insertion time (50 docs): {insertion_time:.4f}s")
        print(f"Search time (3 queries): {search_time:.4f}s")
        print(f"Insertion rate: {50/insertion_time:.2f} docs/sec")

        self.assertGreater(insertion_time, 0)
        self.assertGreater(search_time, 0)


if __name__ == "__main__":
    # Configure logging for tests
    import logging
    logging.basicConfig(level=logging.INFO)

    # Run tests
    unittest.main(verbosity=2)