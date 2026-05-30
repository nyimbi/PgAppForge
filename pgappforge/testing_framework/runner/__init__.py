"""
Test Runner and Reporter Components for PgForge Testing Framework

This package provides comprehensive test execution and reporting capabilities
with parallel execution, detailed analytics, and multiple report formats.
"""

from .test_runner import (
    TestRunner,
    TestType,
    TestResult,
    TestExecutionResult,
    TestSuiteResult,
    TestRunConfiguration,
    create_default_run_config
)

from .test_reporter import (
    TestReporter,
    TestAnalytics,
    CoverageReport,
    PerformanceMetrics,
    TrendAnalysis
)

__version__ = "1.0.0"
__author__ = "PgForge Testing Framework Team"

__all__ = [
    # Test Runner Components
    "TestRunner",
    "TestType",
    "TestResult",
    "TestExecutionResult",
    "TestSuiteResult",
    "TestRunConfiguration",
    "create_default_run_config",

    # Test Reporter Components
    "TestReporter",
    "TestAnalytics",
    "CoverageReport",
    "PerformanceMetrics",
    "TrendAnalysis"
]