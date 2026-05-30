#!/usr/bin/env python3
"""
FAISS Performance Benchmarking Script

This script benchmarks FAISS integration performance against standard vector store
across different scenarios including various dataset sizes, query patterns, and
configuration options.

Usage:
    python benchmark_faiss_performance.py [--dataset-size SIZE] [--with-gpu] [--index-type TYPE]

Examples:
    python benchmark_faiss_performance.py --dataset-size 1000
    python benchmark_faiss_performance.py --dataset-size 5000 --index-type hnsw
    python benchmark_faiss_performance.py --with-gpu
"""

import argparse
import asyncio
import os
import sys
import time
import tempfile
import shutil
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import statistics

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pgappforge.collaborative.ai.rag_engine import (
    RAGEngine, VectorStore, DocumentProcessor, DocumentType
)
from pgappforge.collaborative.ai.rag_factory import RAGFactory, RAGConfig
from pgappforge.collaborative.ai.ai_models import AIModelAdapter, ChatMessage, ModelResponse

# Test FAISS availability
try:
    from pgappforge.collaborative.ai.faiss_vector_store import (
        FAISSIntegratedVectorStore, IndexConfig, FAISS_AVAILABLE
    )
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    print("Warning: FAISS not available. Only standard vector store will be tested.")

# SQLAlchemy setup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pgappforge.models.sqla import Base


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""
    scenario: str
    dataset_size: int
    index_type: str
    use_gpu: bool
    insertion_time_ms: float
    search_time_ms: float
    memory_usage_mb: float
    accuracy_score: float
    throughput_qps: float  # Queries per second


class MockEmbeddingModel(AIModelAdapter):
    """High-performance mock AI model for benchmarking."""

    def __init__(self, embedding_dim: int = 768):
        self.embedding_dim = embedding_dim
        self._embedding_cache = {}

    async def get_embedding(self, text: str) -> List[float]:
        """Generate deterministic embeddings for consistent benchmarking."""
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        import hashlib
        import struct

        # Create reproducible embedding from text
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []

        for i in range(0, min(len(hash_bytes), self.embedding_dim * 4), 4):
            if i + 4 <= len(hash_bytes):
                float_val = struct.unpack('f', hash_bytes[i:i+4])[0]
                embedding.append(float_val)

        # Pad or truncate to desired dimension
        while len(embedding) < self.embedding_dim:
            embedding.append(0.0)
        embedding = embedding[:self.embedding_dim]

        # Normalize
        norm = sum(x * x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]

        self._embedding_cache[text] = embedding
        return embedding

    async def chat_completion(self, messages: List[ChatMessage], **kwargs) -> ModelResponse:
        """Mock chat completion for RAG testing."""
        return ModelResponse(
            content="Benchmark response",
            model="mock-benchmark",
            usage={"total_tokens": 50, "prompt_tokens": 40, "completion_tokens": 10}
        )


class FAISSBenchmark:
    """Main benchmarking class for FAISS integration."""

    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        self.db_path = os.path.join(temp_dir, "benchmark.db")
        self.faiss_index_path = os.path.join(temp_dir, "faiss_benchmark_index")

        # Setup database
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self.session_factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

        # Setup AI model
        self.ai_model = MockEmbeddingModel()

        # Benchmark results storage
        self.results: List[BenchmarkResult] = []

    def generate_test_dataset(self, size: int) -> List[Dict[str, Any]]:
        """Generate synthetic test dataset of specified size."""
        import random
        import string

        datasets = []
        categories = [
            ("technology", ["AI", "machine learning", "algorithms", "data science", "programming"]),
            ("science", ["physics", "chemistry", "biology", "research", "experiments"]),
            ("business", ["strategy", "marketing", "finance", "operations", "management"]),
            ("literature", ["novels", "poetry", "writing", "storytelling", "analysis"]),
            ("history", ["ancient", "modern", "civilization", "culture", "events"])
        ]

        for i in range(size):
            category, keywords = random.choice(categories)

            # Generate content with varied lengths
            content_length = random.choice([100, 300, 500, 800, 1200])
            keywords_sample = random.sample(keywords, min(3, len(keywords)))

            content = f"This document discusses {category} topics including {', '.join(keywords_sample)}. "

            # Fill to desired length with random sentences
            sentences = [
                f"The research in {random.choice(keywords_sample)} shows significant progress.",
                f"Modern approaches to {category} are evolving rapidly.",
                f"Key concepts include {random.choice(keywords_sample)} and related methodologies.",
                f"Applications in this field demonstrate {random.choice(keywords_sample)} principles.",
                f"Future developments in {category} will likely focus on {random.choice(keywords_sample)}."
            ]

            while len(content) < content_length:
                content += " " + random.choice(sentences)

            datasets.append({
                "content": content[:content_length],
                "document_id": f"doc_{i:06d}",
                "document_type": DocumentType.TEXT,
                "metadata": {
                    "category": category,
                    "keywords": keywords_sample,
                    "length": content_length,
                    "synthetic": True
                }
            })

        return datasets

    def generate_test_queries(self, dataset_size: int) -> List[str]:
        """Generate test queries based on dataset size."""
        base_queries = [
            "machine learning algorithms",
            "artificial intelligence research",
            "data science applications",
            "programming methodologies",
            "scientific experiments",
            "business strategy planning",
            "financial analysis methods",
            "literature analysis techniques",
            "historical events significance",
            "modern technology trends"
        ]

        # Scale queries based on dataset size
        if dataset_size <= 100:
            return base_queries[:5]
        elif dataset_size <= 1000:
            return base_queries[:8]
        else:
            return base_queries

    async def benchmark_standard_vector_store(
        self,
        dataset: List[Dict[str, Any]],
        queries: List[str]
    ) -> BenchmarkResult:
        """Benchmark standard vector store performance."""
        print("Benchmarking standard vector store...")

        # Create standard vector store
        store = VectorStore(
            session_factory=self.session_factory,
            embedding_model=self.ai_model,
            enable_monitoring=True
        )

        # Measure insertion time
        insertion_start = time.time()
        for doc in dataset:
            await store.add_document(
                content=doc["content"],
                document_id=doc["document_id"],
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )
        insertion_time = (time.time() - insertion_start) * 1000

        # Measure search time
        search_start = time.time()
        all_results = []
        for query in queries:
            results = await store.similarity_search(query, limit=5)
            all_results.extend(results)
        search_time = (time.time() - search_start) * 1000

        # Calculate metrics
        throughput = len(queries) / (search_time / 1000) if search_time > 0 else 0
        memory_stats = store.get_stats()
        memory_usage = memory_stats.get("memory_usage", {}).get("rss_mb", 0)

        return BenchmarkResult(
            scenario="standard",
            dataset_size=len(dataset),
            index_type="cosine_similarity",
            use_gpu=False,
            insertion_time_ms=insertion_time,
            search_time_ms=search_time,
            memory_usage_mb=memory_usage,
            accuracy_score=1.0,  # Reference accuracy
            throughput_qps=throughput
        )

    async def benchmark_faiss_vector_store(
        self,
        dataset: List[Dict[str, Any]],
        queries: List[str],
        index_type: str = "Flat",
        use_gpu: bool = False
    ) -> Optional[BenchmarkResult]:
        """Benchmark FAISS vector store performance."""
        if not HAS_FAISS:
            print("FAISS not available, skipping FAISS benchmark")
            return None

        print(f"Benchmarking FAISS vector store (index: {index_type}, GPU: {use_gpu})...")

        # Create FAISS-integrated store
        store = FAISSIntegratedVectorStore(
            session_factory=self.session_factory,
            embedding_model=self.ai_model,
            faiss_index_path=self.faiss_index_path,
            embedding_dim=768,
            use_gpu=use_gpu,
            enable_monitoring=True
        )

        # Configure index type
        if hasattr(store, 'index_config'):
            store.index_config.index_type = index_type

        # Measure insertion time
        insertion_start = time.time()
        for doc in dataset:
            await store.add_document(
                content=doc["content"],
                document_id=doc["document_id"] + "_faiss",
                document_type=doc["document_type"],
                metadata=doc["metadata"]
            )
        insertion_time = (time.time() - insertion_start) * 1000

        # Measure search time
        search_start = time.time()
        all_results = []
        for query in queries:
            results = await store.similarity_search(query, limit=5)
            all_results.extend(results)
        search_time = (time.time() - search_start) * 1000

        # Calculate metrics
        throughput = len(queries) / (search_time / 1000) if search_time > 0 else 0

        # Get memory usage
        try:
            stats = store.get_stats()
            memory_usage = stats.get("memory_usage", {}).get("rss_mb", 0)
        except:
            memory_usage = 0

        return BenchmarkResult(
            scenario="faiss",
            dataset_size=len(dataset),
            index_type=index_type,
            use_gpu=use_gpu,
            insertion_time_ms=insertion_time,
            search_time_ms=search_time,
            memory_usage_mb=memory_usage,
            accuracy_score=0.95,  # Approximate accuracy for FAISS
            throughput_qps=throughput
        )

    async def run_comprehensive_benchmark(
        self,
        dataset_size: int,
        index_types: List[str],
        use_gpu: bool = False
    ) -> List[BenchmarkResult]:
        """Run comprehensive benchmark across multiple configurations."""
        print(f"\n{'='*60}")
        print(f"Running Comprehensive FAISS Benchmark")
        print(f"Dataset Size: {dataset_size}")
        print(f"Index Types: {', '.join(index_types)}")
        print(f"GPU Acceleration: {use_gpu}")
        print(f"{'='*60}")

        # Generate test data
        print(f"Generating {dataset_size} test documents...")
        dataset = self.generate_test_dataset(dataset_size)
        queries = self.generate_test_queries(dataset_size)
        print(f"Generated {len(queries)} test queries")

        results = []

        # Benchmark standard vector store
        try:
            standard_result = await self.benchmark_standard_vector_store(dataset, queries)
            results.append(standard_result)
            self.results.append(standard_result)
        except Exception as e:
            print(f"Standard vector store benchmark failed: {e}")

        # Benchmark FAISS with different index types
        if HAS_FAISS:
            for index_type in index_types:
                try:
                    faiss_result = await self.benchmark_faiss_vector_store(
                        dataset, queries, index_type, use_gpu
                    )
                    if faiss_result:
                        results.append(faiss_result)
                        self.results.append(faiss_result)

                    # Clean up index files between runs
                    if os.path.exists(self.faiss_index_path):
                        shutil.rmtree(self.faiss_index_path)

                except Exception as e:
                    print(f"FAISS benchmark failed for {index_type}: {e}")

        return results

    def analyze_results(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Analyze benchmark results and generate performance insights."""
        if not results:
            return {"error": "No results to analyze"}

        analysis = {
            "summary": {},
            "performance_comparison": {},
            "recommendations": []
        }

        # Find standard baseline
        standard_results = [r for r in results if r.scenario == "standard"]
        faiss_results = [r for r in results if r.scenario == "faiss"]

        if standard_results and faiss_results:
            standard = standard_results[0]

            # Performance comparison
            analysis["performance_comparison"] = {
                "insertion_speedup": {},
                "search_speedup": {},
                "memory_efficiency": {},
                "throughput_improvement": {}
            }

            for faiss_result in faiss_results:
                config_name = f"{faiss_result.index_type}_{'gpu' if faiss_result.use_gpu else 'cpu'}"

                # Calculate speedups
                insertion_speedup = standard.insertion_time_ms / faiss_result.insertion_time_ms if faiss_result.insertion_time_ms > 0 else 0
                search_speedup = standard.search_time_ms / faiss_result.search_time_ms if faiss_result.search_time_ms > 0 else 0
                memory_ratio = faiss_result.memory_usage_mb / standard.memory_usage_mb if standard.memory_usage_mb > 0 else 1
                throughput_improvement = faiss_result.throughput_qps / standard.throughput_qps if standard.throughput_qps > 0 else 1

                analysis["performance_comparison"]["insertion_speedup"][config_name] = insertion_speedup
                analysis["performance_comparison"]["search_speedup"][config_name] = search_speedup
                analysis["performance_comparison"]["memory_efficiency"][config_name] = memory_ratio
                analysis["performance_comparison"]["throughput_improvement"][config_name] = throughput_improvement

        # Generate recommendations
        if faiss_results:
            best_search = max(faiss_results, key=lambda x: x.throughput_qps)
            best_memory = min(faiss_results, key=lambda x: x.memory_usage_mb)

            analysis["recommendations"] = [
                f"For best search performance: {best_search.index_type} ({'GPU' if best_search.use_gpu else 'CPU'})",
                f"For memory efficiency: {best_memory.index_type} ({'GPU' if best_memory.use_gpu else 'CPU'})",
            ]

            if len(faiss_results) > 1:
                analysis["recommendations"].append(
                    f"Dataset size {results[0].dataset_size}: Consider {best_search.index_type} for production"
                )

        # Summary statistics
        if results:
            analysis["summary"] = {
                "total_configurations": len(results),
                "dataset_size": results[0].dataset_size,
                "best_throughput_qps": max(r.throughput_qps for r in results),
                "lowest_memory_mb": min(r.memory_usage_mb for r in results if r.memory_usage_mb > 0),
                "average_search_time_ms": statistics.mean([r.search_time_ms for r in results])
            }

        return analysis

    def print_results(self, results: List[BenchmarkResult]):
        """Print benchmark results in a readable format."""
        if not results:
            print("No results to display")
            return

        print(f"\n{'='*80}")
        print(f"BENCHMARK RESULTS")
        print(f"{'='*80}")

        # Results table
        print(f"{'Scenario':<12} {'Index Type':<15} {'GPU':<5} {'Insert(ms)':<12} {'Search(ms)':<12} {'Throughput':<12} {'Memory(MB)':<12}")
        print(f"{'-'*80}")

        for result in results:
            print(f"{result.scenario:<12} {result.index_type:<15} {str(result.use_gpu):<5} "
                  f"{result.insertion_time_ms:<12.2f} {result.search_time_ms:<12.2f} "
                  f"{result.throughput_qps:<12.2f} {result.memory_usage_mb:<12.2f}")

        # Analysis
        analysis = self.analyze_results(results)
        if "error" not in analysis:
            print(f"\n{'='*80}")
            print(f"PERFORMANCE ANALYSIS")
            print(f"{'='*80}")

            summary = analysis.get("summary", {})
            print(f"Dataset Size: {summary.get('dataset_size', 'N/A')}")
            print(f"Best Throughput: {summary.get('best_throughput_qps', 'N/A'):.2f} QPS")
            print(f"Lowest Memory: {summary.get('lowest_memory_mb', 'N/A'):.2f} MB")
            print(f"Average Search Time: {summary.get('average_search_time_ms', 'N/A'):.2f} ms")

            if analysis.get("recommendations"):
                print(f"\nRECOMMENDATIONS:")
                for i, rec in enumerate(analysis["recommendations"], 1):
                    print(f"{i}. {rec}")

    def save_results(self, output_file: str):
        """Save benchmark results to JSON file."""
        output_data = {
            "benchmark_info": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_runs": len(self.results),
                "faiss_available": HAS_FAISS
            },
            "results": [
                {
                    "scenario": r.scenario,
                    "dataset_size": r.dataset_size,
                    "index_type": r.index_type,
                    "use_gpu": r.use_gpu,
                    "insertion_time_ms": r.insertion_time_ms,
                    "search_time_ms": r.search_time_ms,
                    "memory_usage_mb": r.memory_usage_mb,
                    "accuracy_score": r.accuracy_score,
                    "throughput_qps": r.throughput_qps
                }
                for r in self.results
            ],
            "analysis": self.analyze_results(self.results)
        }

        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        print(f"\nResults saved to: {output_file}")


async def main():
    """Main benchmark execution function."""
    parser = argparse.ArgumentParser(description="FAISS Performance Benchmark")
    parser.add_argument("--dataset-size", type=int, default=500,
                       help="Number of documents in test dataset (default: 500)")
    parser.add_argument("--index-types", nargs="+", default=["Flat", "IVF"],
                       help="FAISS index types to test (default: Flat IVF)")
    parser.add_argument("--with-gpu", action="store_true",
                       help="Test GPU acceleration (if available)")
    parser.add_argument("--output", type=str, default="faiss_benchmark_results.json",
                       help="Output file for results (default: faiss_benchmark_results.json)")

    args = parser.parse_args()

    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        benchmark = FAISSBenchmark(temp_dir)

        print(f"FAISS Availability: {HAS_FAISS}")
        if HAS_FAISS:
            try:
                import faiss
                print(f"FAISS Version: {faiss.__version__ if hasattr(faiss, '__version__') else 'Unknown'}")
                print(f"GPU Available: {faiss.get_num_gpus() > 0}")
            except:
                print("FAISS GPU status unknown")

        # Run benchmarks
        results = await benchmark.run_comprehensive_benchmark(
            dataset_size=args.dataset_size,
            index_types=args.index_types,
            use_gpu=args.with_gpu
        )

        # Display and save results
        benchmark.print_results(results)
        benchmark.save_results(args.output)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBenchmark interrupted by user")
    except Exception as e:
        print(f"Benchmark failed: {e}")
        import traceback
        traceback.print_exc()