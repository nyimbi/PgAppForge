"""
PgAppForge Testing Automation Framework

Revolutionary testing system that automatically generates comprehensive test suites
for PgAppForge applications based on database schema analysis.

Features:
- Comprehensive test coverage (unit, integration, e2e, performance, security)
- AI-powered realistic test data generation
- Master-detail relationship testing
- Performance benchmarking and scalability testing
- Security vulnerability testing with OWASP compliance
- Automated test execution and reporting

Usage:
    from pgappforge.testing_framework import TestGenerator, TestGenerationConfig
    
    config = TestGenerationConfig(
        generate_unit_tests=True,
        generate_integration_tests=True,
        generate_e2e_tests=True,
        target_coverage_percentage=95
    )
    
    generator = TestGenerator(config=config, inspector=inspector)
    test_suite = generator.generate_complete_test_suite(schema)
    results = generator.execute_test_suite(test_suite)
"""

from .core.test_generator import TestGenerator
from .core.config import TestGenerationConfig
from .core.test_runner import TestRunner
from .core.test_reporter import TestReporter
from .data.realistic_data_generator import RealisticDataGenerator

__version__ = "1.0.0"
__author__ = "PgAppForge Evolution Team"

__all__ = [
    "TestGenerator",
    "TestGenerationConfig", 
    "TestRunner",
    "TestReporter",
    "RealisticDataGenerator"
]