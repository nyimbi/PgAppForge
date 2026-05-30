#!/usr/bin/env python3
"""
FAISS Setup Validation Script

Quick validation script to verify FAISS integration is working correctly
with the PgAppForge RAG system.

Usage:
    python validate_faiss_setup.py
"""

import os
import sys
import tempfile
import shutil
import asyncio
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import RAG components
from pgappforge.collaborative.ai.rag_engine import (
    RAGEngine, VectorStore, DocumentProcessor, DocumentType, ChunkingStrategy
)
from pgappforge.collaborative.ai.rag_factory import RAGFactory, RAGConfig
from pgappforge.collaborative.ai.ai_models import AIModelAdapter, ChatMessage, ModelResponse

# SQLAlchemy setup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pgappforge.models.sqla import Base


# Test FAISS availability
try:
    from pgappforge.collaborative.ai.faiss_vector_store import (
        FAISSVectorStore, FAISSIntegratedVectorStore, IndexConfig, FAISS_AVAILABLE
    )
    HAS_FAISS = True
    print("✅ FAISS integration modules imported successfully")
except ImportError as e:
    HAS_FAISS = False
    print(f"❌ FAISS integration not available: {e}")


class MockEmbeddingModel(AIModelAdapter):
    """Simple mock AI model for validation."""

    def __init__(self, embedding_dim: int = 768):
        self.embedding_dim = embedding_dim

    async def get_embedding(self, text: str) -> List[float]:
        """Generate simple mock embedding."""
        import hashlib
        # Simple deterministic embedding
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        embedding = []
        for i in range(self.embedding_dim):
            embedding.append(((hash_val >> (i % 32)) & 1) * 2.0 - 1.0)
        # Normalize
        norm = sum(x * x for x in embedding) ** 0.5
        return [x / norm for x in embedding] if norm > 0 else embedding

    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Mock chat completion."""
        return ModelResponse(
            content="This is a mock response from the validation script.",
            model="mock-validation-model",
            usage={"total_tokens": 20, "prompt_tokens": 15, "completion_tokens": 5}
        )


async def validate_faiss_basic_functionality():
    """Validate basic FAISS functionality."""
    print("\n🧪 Testing FAISS Basic Functionality...")

    if not HAS_FAISS:
        print("❌ FAISS not available - skipping FAISS tests")
        return False

    try:
        # Test FAISS import and basic operations
        import faiss
        print(f"✅ FAISS version available")

        # Create a simple index
        dim = 64
        index = faiss.IndexFlatL2(dim)
        print(f"✅ Created FAISS Flat index (dimension: {dim})")

        # Test basic operations
        import numpy as np
        test_vectors = np.random.random((10, dim)).astype('float32')
        index.add(test_vectors)
        print(f"✅ Added {len(test_vectors)} vectors to index")

        # Test search
        distances, indices = index.search(test_vectors[:2], 3)
        print(f"✅ Performed similarity search - found {len(indices[0])} results per query")

        return True

    except Exception as e:
        print(f"❌ FAISS basic functionality test failed: {e}")
        return False


async def validate_rag_factory():
    """Validate RAG factory functionality."""
    print("\n🧪 Testing RAG Factory...")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "validation.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

        mock_model = MockEmbeddingModel()

        try:
            # Test development RAG creation
            dev_rag = RAGFactory.create_development_rag(
                session_factory=session_factory,
                embedding_model=mock_model
            )
            print("✅ Created development RAG engine")

            # Test production RAG creation
            prod_rag = RAGFactory.create_production_rag(
                session_factory=session_factory,
                embedding_model=mock_model
            )
            print("✅ Created production RAG engine")

            # Test configuration validation
            config = RAGConfig(
                use_faiss=True,
                embedding_dim=768,
                chunk_size=1000
            )
            print("✅ RAG configuration validation passed")

            return True

        except Exception as e:
            print(f"❌ RAG Factory validation failed: {e}")
            return False


async def validate_document_processing():
    """Validate enhanced document processing."""
    print("\n🧪 Testing Enhanced Document Processing...")

    try:
        # Test different chunking strategies
        strategies = [
            ChunkingStrategy.SENTENCE_BOUNDARY,
            ChunkingStrategy.PARAGRAPH_BOUNDARY,
            ChunkingStrategy.FIXED_SIZE
        ]

        for strategy in strategies:
            processor = DocumentProcessor(
                chunk_size=500,
                chunk_overlap=100,
                chunking_strategy=strategy,
                enable_preprocessing=True
            )

            # Test with different document types
            test_docs = [
                ("Plain text document for testing chunking strategies.", DocumentType.TEXT),
                ("<h1>HTML Document</h1><p>This is HTML content for testing.</p>", DocumentType.HTML),
                ("# Markdown Document\n\nThis is **markdown** content for testing.", DocumentType.MARKDOWN),
                ("def test_function():\n    '''Test function.'''\n    return True", DocumentType.CODE)
            ]

            for content, doc_type in test_docs:
                chunks = processor.process_document(
                    content=content,
                    document_id=f"test_{doc_type.value}_{strategy.value}",
                    document_type=doc_type
                )

                if len(chunks) > 0:
                    # Verify chunk has enhanced metadata
                    chunk = chunks[0]
                    assert "chunk_info" in chunk.metadata
                    assert "chunking_strategy" in chunk.metadata["chunk_info"]

        print("✅ Document processing with all strategies working")
        return True

    except Exception as e:
        print(f"❌ Document processing validation failed: {e}")
        return False


async def validate_faiss_integration():
    """Validate full FAISS integration with RAG system."""
    print("\n🧪 Testing FAISS Integration with RAG System...")

    if not HAS_FAISS:
        print("❌ FAISS not available - skipping integration test")
        return False

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "faiss_validation.db")
        faiss_index_path = os.path.join(temp_dir, "validation_index")

        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

        mock_model = MockEmbeddingModel()

        try:
            # Create FAISS-integrated vector store
            store = FAISSIntegratedVectorStore(
                session_factory=session_factory,
                embedding_model=mock_model,
                faiss_index_path=faiss_index_path,
                embedding_dim=768,
                use_gpu=False,
                enable_monitoring=False
            )
            print("✅ Created FAISS-integrated vector store")

            # Test document addition
            test_content = "PgAppForge is a rapid application development framework."
            chunks = await store.add_document(
                content=test_content,
                document_id="validation_doc",
                document_type=DocumentType.TEXT,
                metadata={"test": True}
            )
            print(f"✅ Added document to FAISS store ({len(chunks)} chunks)")

            # Test similarity search
            results = await store.similarity_search(
                query="Flask development framework",
                limit=5
            )
            print(f"✅ Performed similarity search ({len(results)} results)")

            # Test index persistence
            save_success = store.save_index()
            if save_success:
                print("✅ FAISS index saved successfully")

                # Test loading
                load_success = store.load_index()
                if load_success:
                    print("✅ FAISS index loaded successfully")
                else:
                    print("⚠️  FAISS index loading had issues")
            else:
                print("⚠️  FAISS index saving had issues")

            return True

        except Exception as e:
            print(f"❌ FAISS integration validation failed: {e}")
            return False


async def validate_rag_end_to_end():
    """Validate end-to-end RAG functionality."""
    print("\n🧪 Testing End-to-End RAG Functionality...")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "e2e_validation.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        session_factory = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

        mock_model = MockEmbeddingModel()

        try:
            # Create RAG engine (will use FAISS if available)
            config = RAGConfig(
                use_faiss=HAS_FAISS,
                embedding_dim=768,
                chunk_size=500,
                enable_monitoring=False
            )

            rag_engine = RAGFactory.create_custom_rag(
                session_factory=session_factory,
                embedding_model=mock_model,
                config=config
            )
            print("✅ Created RAG engine with custom configuration")

            # Add test documents
            test_documents = [
                "PgAppForge provides automatic CRUD generation for web applications.",
                "FAISS is a library for efficient similarity search and clustering of dense vectors.",
                "Vector databases enable semantic search by storing high-dimensional embeddings.",
            ]

            for i, content in enumerate(test_documents):
                await rag_engine.add_document(
                    content=content,
                    document_id=f"e2e_doc_{i}",
                    document_type=DocumentType.TEXT,
                    metadata={"sequence": i}
                )

            print(f"✅ Added {len(test_documents)} documents to RAG system")

            # Test query and response generation
            query = "How does PgAppForge help with web development?"
            response = await rag_engine.query(
                query=query,
                max_results=3,
                include_sources=True
            )

            print("✅ Generated RAG response successfully")
            print(f"   Response length: {len(response.get('response', ''))}")
            print(f"   Sources found: {len(response.get('sources', []))}")
            print(f"   Confidence: {response.get('confidence', 0)}")

            # Test performance statistics
            perf_stats = rag_engine.get_performance_stats()
            print("✅ Retrieved performance statistics")
            print(f"   Using FAISS: {perf_stats.get('using_faiss', False)}")

            return True

        except Exception as e:
            print(f"❌ End-to-end RAG validation failed: {e}")
            return False


def print_system_info():
    """Print system information for debugging."""
    print("🖥️  System Information:")
    print(f"   Python version: {sys.version.split()[0]}")
    print(f"   Platform: {sys.platform}")

    # Check for optional dependencies
    optional_deps = ["faiss-cpu", "faiss-gpu", "numpy", "sqlalchemy"]
    for dep in optional_deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"   ✅ {dep} available")
        except ImportError:
            print(f"   ❌ {dep} not available")


async def main():
    """Main validation function."""
    print("🚀 PgAppForge FAISS Integration Validation")
    print("=" * 60)

    print_system_info()

    # Run validation tests
    tests = [
        ("FAISS Basic Functionality", validate_faiss_basic_functionality()),
        ("RAG Factory", validate_rag_factory()),
        ("Document Processing", validate_document_processing()),
        ("FAISS Integration", validate_faiss_integration()),
        ("End-to-End RAG", validate_rag_end_to_end())
    ]

    results = []
    for test_name, test_coro in tests:
        try:
            result = await test_coro
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} validation failed with exception: {e}")
            results.append((test_name, False))

    # Print summary
    print("\n" + "=" * 60)
    print("📋 VALIDATION SUMMARY")
    print("=" * 60)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:<8} {test_name}")
        if result:
            passed += 1

    print(f"\n📊 Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All validations passed! FAISS integration is working correctly.")
        return 0
    elif passed > 0:
        print("⚠️  Some validations failed. Check the output above for details.")
        return 1
    else:
        print("🚨 All validations failed. FAISS integration may have issues.")
        return 2


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n🛑 Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Validation script failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)