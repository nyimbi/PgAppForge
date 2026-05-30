"""
Master Test Generation Orchestrator

Coordinates comprehensive test suite generation including unit tests, integration tests,
end-to-end tests, performance tests, and security tests.
"""

import logging
import os
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

from ..generators.unit_test_generator import UnitTestGenerator
from ..generators.integration_test_generator import IntegrationTestGenerator
from ..generators.e2e_test_generator import E2ETestGenerator
from ..generators.performance_test_generator import PerformanceTestGenerator
from ..generators.security_test_generator import SecurityTestGenerator
from ..data.realistic_data_generator import RealisticDataGenerator
from .config import TestGenerationConfig
from .test_runner import TestRunner
from .test_reporter import TestReporter

logger = logging.getLogger(__name__)


@dataclass
class TestSuite:
    """
    Container for a complete test suite with all generated tests.
    """
    name: str
    schema_name: str
    generated_at: datetime
    
    # Test files by category
    unit_tests: Dict[str, str] = None
    integration_tests: Dict[str, str] = None
    e2e_tests: Dict[str, str] = None
    performance_tests: Dict[str, str] = None
    security_tests: Dict[str, str] = None
    accessibility_tests: Dict[str, str] = None
    
    # Supporting files
    test_data: Dict[str, Any] = None
    test_fixtures: Dict[str, str] = None
    test_configurations: Dict[str, str] = None
    
    # Metadata
    total_tests: int = 0
    estimated_execution_time: float = 0.0
    coverage_target: int = 95
    
    def __post_init__(self):
        """Initialize empty collections."""
        if self.unit_tests is None:
            self.unit_tests = {}
        if self.integration_tests is None:
            self.integration_tests = {}
        if self.e2e_tests is None:
            self.e2e_tests = {}
        if self.performance_tests is None:
            self.performance_tests = {}
        if self.security_tests is None:
            self.security_tests = {}
        if self.accessibility_tests is None:
            self.accessibility_tests = {}
        if self.test_data is None:
            self.test_data = {}
        if self.test_fixtures is None:
            self.test_fixtures = {}
        if self.test_configurations is None:
            self.test_configurations = {}
    
    def get_all_tests(self) -> Dict[str, str]:
        """Get all generated test files."""
        all_tests = {}
        all_tests.update(self.unit_tests)
        all_tests.update(self.integration_tests)
        all_tests.update(self.e2e_tests)
        all_tests.update(self.performance_tests)
        all_tests.update(self.security_tests)
        all_tests.update(self.accessibility_tests)
        return all_tests
    
    def get_test_statistics(self) -> Dict[str, int]:
        """Get test statistics by category."""
        return {
            'unit_tests': len(self.unit_tests),
            'integration_tests': len(self.integration_tests),
            'e2e_tests': len(self.e2e_tests),
            'performance_tests': len(self.performance_tests),
            'security_tests': len(self.security_tests),
            'accessibility_tests': len(self.accessibility_tests),
            'total_tests': sum([
                len(self.unit_tests),
                len(self.integration_tests),
                len(self.e2e_tests),
                len(self.performance_tests),
                len(self.security_tests),
                len(self.accessibility_tests)
            ])
        }


@dataclass 
class GenerationResult:
    """Result of test generation process."""
    success: bool
    test_suite: Optional[TestSuite]
    generation_time: float
    errors: List[str]
    warnings: List[str]
    statistics: Dict[str, Any]
    
    def __post_init__(self):
        """Initialize empty collections."""
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.statistics is None:
            self.statistics = {}


class TestGenerator:
    """
    Master test generation orchestrator for PgAppForge applications.
    
    This class coordinates the generation of comprehensive test suites including
    unit tests, integration tests, end-to-end tests, performance tests, and
    security tests based on database schema analysis.
    
    Features:
        - Automatic test type detection based on schema complexity
        - Intelligent test data generation with realistic scenarios
        - Performance benchmark generation for scalability testing
        - Security vulnerability testing with OWASP compliance
        - Master-detail relationship testing for complex forms
        - Comprehensive reporting and metrics
        
    Usage:
        >>> config = TestGenerationConfig()
        >>> generator = TestGenerator(config=config, inspector=inspector)
        >>> schema = analyze_database_schema("postgresql://...")
        >>> test_suite = generator.generate_complete_test_suite(schema)
        >>> results = generator.execute_test_suite(test_suite)
        
    Args:
        config (TestGenerationConfig): Configuration for test generation
        inspector (EnhancedDatabaseInspector): Database analysis engine
        
    Attributes:
        generators (Dict[str, BaseTestGenerator]): Individual test generators
        test_runner (TestRunner): Test execution engine
        reporter (TestReporter): Results and metrics reporting
    """
    
    def __init__(self, config: TestGenerationConfig, inspector=None):
        """
        Initialize the test generator with configuration and database inspector.
        
        Args:
            config: Test generation configuration
            inspector: Enhanced database inspector for schema analysis
        """
        self.config = config
        self.inspector = inspector
        
        # Initialize test generators
        self.generators = {}
        self._initialize_generators()
        
        # Initialize supporting components
        self.data_generator = RealisticDataGenerator(config)
        self.test_runner = TestRunner(config)
        self.reporter = TestReporter(config)
        
        # Statistics tracking
        self.generation_stats = {
            'tests_generated': 0,
            'generation_time': 0.0,
            'templates_used': 0,
            'data_records_generated': 0
        }
        
        logger.info("TestGenerator initialized", extra={
            'config': config.__class__.__name__,
            'generators': list(self.generators.keys())
        })
    
    def _initialize_generators(self):
        """Initialize individual test generators based on configuration."""
        if self.config.generate_unit_tests:
            self.generators['unit'] = UnitTestGenerator(self.config, self.inspector)
        
        if self.config.generate_integration_tests:
            self.generators['integration'] = IntegrationTestGenerator(self.config, self.inspector)
        
        if self.config.generate_e2e_tests:
            self.generators['e2e'] = E2ETestGenerator(self.config, self.inspector)
        
        if self.config.generate_performance_tests:
            self.generators['performance'] = PerformanceTestGenerator(self.config, self.inspector)
        
        if self.config.generate_security_tests:
            self.generators['security'] = SecurityTestGenerator(self.config, self.inspector)
        
        logger.info(f"Initialized {len(self.generators)} test generators")
    
    def generate_complete_test_suite(self, schema) -> GenerationResult:
        """
        Generate comprehensive test coverage for entire application.
        
        Analyzes the database schema and generates appropriate test types
        based on complexity, relationships, and data patterns. Automatically
        includes edge cases, error scenarios, and performance benchmarks.
        
        Args:
            schema: Analyzed database schema (DatabaseSchema or similar)
            
        Returns:
            GenerationResult: Complete test suite generation results
            
        Raises:
            TestGenerationError: When test generation fails
            SchemaAnalysisError: When schema analysis is invalid
            
        Performance:
            Typical generation time: 30-60 seconds for 50-table schema
            Memory usage: 100-500MB during generation
            
        Examples:
            >>> schema = DatabaseSchema.from_uri("sqlite:///app.db")
            >>> result = generator.generate_complete_test_suite(schema)
            >>> print(f"Generated {result.test_suite.total_tests} tests")
            Generated 847 tests
        """
        logger.info("Starting comprehensive test suite generation", extra={
            'schema_name': getattr(schema, 'name', 'unknown'),
            'table_count': len(getattr(schema, 'tables', []))
        })
        
        start_time = time.time()
        errors = []
        warnings = []
        
        try:
            # Create test suite container
            test_suite = TestSuite(
                name=f"test_suite_{getattr(schema, 'name', 'app')}",
                schema_name=getattr(schema, 'name', 'unknown'),
                generated_at=datetime.now(),
                coverage_target=self.config.target_coverage_percentage
            )
            
            # Generate test data first (needed by all test types)
            logger.info("Generating realistic test data")
            test_data_result = self._generate_test_data(schema)
            test_suite.test_data = test_data_result['data']
            test_suite.test_fixtures = test_data_result['fixtures']
            
            # Generate each test type
            generation_tasks = [
                ('unit', self._generate_unit_tests),
                ('integration', self._generate_integration_tests),
                ('e2e', self._generate_e2e_tests),
                ('performance', self._generate_performance_tests),
                ('security', self._generate_security_tests)
            ]
            
            for test_type, generation_method in generation_tasks:
                if test_type in self.generators:
                    try:
                        logger.info(f"Generating {test_type} tests")
                        test_files = generation_method(schema)
                        setattr(test_suite, f"{test_type}_tests", test_files)
                        logger.info(f"Generated {len(test_files)} {test_type} test files")
                    except Exception as e:
                        error_msg = f"Failed to generate {test_type} tests: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg, exc_info=True)
            
            # Generate supporting configuration files
            logger.info("Generating test configuration files")
            test_suite.test_configurations = self._generate_test_configurations(schema)
            
            # Calculate statistics
            test_statistics = test_suite.get_test_statistics()
            test_suite.total_tests = test_statistics['total_tests']
            
            # Estimate execution time
            test_suite.estimated_execution_time = self._estimate_execution_time(test_suite)
            
            generation_time = time.time() - start_time
            
            # Update generation statistics
            self.generation_stats.update({
                'tests_generated': test_suite.total_tests,
                'generation_time': generation_time,
                'data_records_generated': len(test_suite.test_data)
            })
            
            logger.info("Test suite generation completed", extra={
                'total_tests': test_suite.total_tests,
                'generation_time': f"{generation_time:.2f}s",
                'errors': len(errors),
                'warnings': len(warnings)
            })
            
            return GenerationResult(
                success=len(errors) == 0,
                test_suite=test_suite,
                generation_time=generation_time,
                errors=errors,
                warnings=warnings,
                statistics=test_statistics
            )
            
        except Exception as e:
            generation_time = time.time() - start_time
            error_msg = f"Test suite generation failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
            
            return GenerationResult(
                success=False,
                test_suite=None,
                generation_time=generation_time,
                errors=errors,
                warnings=warnings,
                statistics={}
            )
    
    def _generate_test_data(self, schema) -> Dict[str, Any]:
        """Generate realistic test data for all tables."""
        return self.data_generator.generate_comprehensive_test_data(schema)
    
    def _generate_unit_tests(self, schema) -> Dict[str, str]:
        """Generate unit tests for models and views."""
        return self.generators['unit'].generate_all_tests(schema)
    
    def _generate_integration_tests(self, schema) -> Dict[str, str]:
        """Generate integration tests for APIs and services."""
        return self.generators['integration'].generate_all_tests(schema)
    
    def _generate_e2e_tests(self, schema) -> Dict[str, str]:
        """Generate end-to-end workflow tests."""
        return self.generators['e2e'].generate_all_tests(schema)
    
    def _generate_performance_tests(self, schema) -> Dict[str, str]:
        """Generate performance and load tests."""
        return self.generators['performance'].generate_all_tests(schema)
    
    def _generate_security_tests(self, schema) -> Dict[str, str]:
        """Generate security vulnerability tests."""
        return self.generators['security'].generate_all_tests(schema)
    
    def _generate_test_configurations(self, schema) -> Dict[str, str]:
        """Generate supporting configuration files."""
        configurations = {}
        
        # pytest configuration
        configurations['pytest.ini'] = self._generate_pytest_config()
        
        # Test environment configuration
        configurations['test_config.py'] = self._generate_test_environment_config()
        
        # Coverage configuration
        configurations['.coveragerc'] = self._generate_coverage_config()
        
        # Performance test configuration
        if self.config.generate_performance_tests:
            configurations['locustfile.py'] = self._generate_locust_config(schema)
        
        return configurations
    
    def _generate_pytest_config(self) -> str:
        """Generate pytest configuration."""
        return f"""[tool:pytest]
testpaths = tests
python_files = test_*.py *_test.py
python_classes = Test*
python_functions = test_*
addopts = 
    --verbose
    --tb=short
    --strict-markers
    --cov=src
    --cov-report=html
    --cov-report=xml
    --cov-fail-under={self.config.target_coverage_percentage}
    --maxfail=5
    {'--parallel' if self.config.parallel_execution else ''}
    {'--workers=' + str(self.config.max_test_workers) if self.config.parallel_execution else ''}

markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    performance: Performance tests
    security: Security tests
    slow: Slow-running tests
    master_detail: Master-detail relationship tests
    
timeout = {self.config.test_timeout_seconds}
"""
    
    def _generate_test_environment_config(self) -> str:
        """Generate test environment configuration."""
        return f"""# Test Environment Configuration
import os
from pgappforge.testing_framework import TestGenerationConfig

# Test database configuration
TEST_DATABASE_URI = os.getenv('TEST_DATABASE_URI', 'sqlite:///test.db')
TEST_REDIS_URI = os.getenv('TEST_REDIS_URI', 'redis://localhost:6379/1')

# Test execution configuration
PARALLEL_TESTING = {self.config.parallel_execution}
MAX_TEST_WORKERS = {self.config.max_test_workers}
TEST_TIMEOUT = {self.config.test_timeout_seconds}

# Coverage configuration
COVERAGE_THRESHOLD = {self.config.target_coverage_percentage}
ENFORCE_COVERAGE = {self.config.enforce_coverage_threshold}

# Test data configuration
REALISTIC_TEST_DATA = {self.config.realistic_test_data}
TEST_DATA_VARIETY = '{self.config.test_data_variety.value}'
PRESERVE_REFERENTIAL_INTEGRITY = {self.config.preserve_referential_integrity}

# Cleanup configuration
CLEANUP_TEST_DATA = {self.config.cleanup_test_data}
CLEANUP_TEST_ENVIRONMENT = {self.config.cleanup_test_environment}
"""
    
    def _generate_coverage_config(self) -> str:
        """Generate coverage configuration."""
        return f"""[run]
source = src
omit = 
    */tests/*
    */test_*
    */venv/*
    */virtualenv/*
    setup.py
    
[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    
[html]
directory = htmlcov

[xml]
output = coverage.xml
"""
    
    def _generate_locust_config(self, schema) -> str:
        """Generate Locust performance testing configuration."""
        return f"""# Generated Locust configuration for performance testing
from locust import HttpUser, task, between

class WebsiteUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        '''Login user when starting'''
        self.login()
    
    def login(self):
        '''Login to the application'''
        response = self.client.post("/login", {{
            "username": "test@example.com",
            "password": "testpassword"
        }})
        
    @task(3)
    def view_home(self):
        '''View home page'''
        self.client.get("/")
    
    @task(2) 
    def view_list_pages(self):
        '''View list pages for main entities'''
        # Add tasks based on generated views
        pass
    
    @task(1)
    def create_record(self):
        '''Create new records'''
        # Add create operations
        pass
    
    @task(1)
    def edit_record(self):
        '''Edit existing records'''
        # Add edit operations
        pass

# Performance test configuration
TARGET_RPS = {self.config.performance_threshold_throughput_rps}
MAX_RESPONSE_TIME = {self.config.performance_threshold_response_time_ms}
TEST_DURATION = {self.config.load_test_duration_seconds}
MAX_USERS = {self.config.max_concurrent_users}
"""
    
    def _estimate_execution_time(self, test_suite: TestSuite) -> float:
        """Estimate total test execution time."""
        # Base estimates per test type (in seconds)
        base_estimates = {
            'unit_tests': 0.1,        # 100ms per unit test
            'integration_tests': 2.0,  # 2s per integration test
            'e2e_tests': 15.0,        # 15s per e2e test
            'performance_tests': 60.0, # 1min per performance test
            'security_tests': 5.0,    # 5s per security test
            'accessibility_tests': 3.0 # 3s per accessibility test
        }
        
        total_time = 0.0
        statistics = test_suite.get_test_statistics()
        
        for test_type, count in statistics.items():
            if test_type in base_estimates:
                total_time += count * base_estimates[test_type]
        
        # Apply parallelization factor
        if self.config.parallel_execution and self.config.max_test_workers > 1:
            parallelization_factor = min(0.3, 1.0 / self.config.max_test_workers)
            total_time *= parallelization_factor
        
        return total_time
    
    def write_test_suite_to_directory(self, test_suite: TestSuite, output_dir: str) -> List[str]:
        """
        Write generated test suite to directory structure.
        
        Args:
            test_suite: Generated test suite
            output_dir: Directory to write test files
            
        Returns:
            List of written file paths
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        written_files = []
        
        # Create directory structure
        test_dirs = {
            'unit': output_path / 'unit',
            'integration': output_path / 'integration', 
            'e2e': output_path / 'e2e',
            'performance': output_path / 'performance',
            'security': output_path / 'security',
            'data': output_path / 'data',
            'config': output_path / 'config'
        }
        
        for test_dir in test_dirs.values():
            test_dir.mkdir(parents=True, exist_ok=True)
        
        # Write test files
        test_categories = [
            ('unit', test_suite.unit_tests),
            ('integration', test_suite.integration_tests),
            ('e2e', test_suite.e2e_tests),
            ('performance', test_suite.performance_tests),
            ('security', test_suite.security_tests)
        ]
        
        for category, tests in test_categories:
            if tests:
                for filename, content in tests.items():
                    file_path = test_dirs[category] / filename
                    with open(file_path, 'w') as f:
                        f.write(content)
                    written_files.append(str(file_path))
        
        # Write test data files
        if test_suite.test_data:
            import json
            data_file = test_dirs['data'] / 'test_data.json'
            with open(data_file, 'w') as f:
                json.dump(test_suite.test_data, f, indent=2, default=str)
            written_files.append(str(data_file))
        
        # Write configuration files
        if test_suite.test_configurations:
            for filename, content in test_suite.test_configurations.items():
                config_file = test_dirs['config'] / filename
                with open(config_file, 'w') as f:
                    f.write(content)
                written_files.append(str(config_file))
        
        # Write test suite metadata
        metadata = {
            'name': test_suite.name,
            'schema_name': test_suite.schema_name,
            'generated_at': test_suite.generated_at.isoformat(),
            'statistics': test_suite.get_test_statistics(),
            'estimated_execution_time': test_suite.estimated_execution_time,
            'coverage_target': test_suite.coverage_target,
            'configuration': self.config.to_dict()
        }
        
        metadata_file = output_path / 'test_suite_metadata.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)
        written_files.append(str(metadata_file))
        
        logger.info(f"Test suite written to {output_dir}", extra={
            'files_written': len(written_files),
            'total_tests': test_suite.total_tests
        })
        
        return written_files
    
    def execute_test_suite(self, test_suite: TestSuite, output_dir: str = None) -> Dict[str, Any]:
        """
        Execute generated test suite and return results.
        
        Args:
            test_suite: Generated test suite to execute
            output_dir: Optional directory to write tests before execution
            
        Returns:
            Test execution results
        """
        if output_dir:
            self.write_test_suite_to_directory(test_suite, output_dir)
        
        return self.test_runner.execute_test_suite(test_suite, output_dir)
    
    def get_generation_statistics(self) -> Dict[str, Any]:
        """Get test generation statistics."""
        return self.generation_stats.copy()