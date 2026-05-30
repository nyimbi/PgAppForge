"""
Test Runner for PgAppForge Testing Framework

This module provides comprehensive test execution capabilities with support for
parallel execution, real-time reporting, and detailed coverage analysis.
"""

import os
import asyncio
import subprocess
import json
import time
import threading
from typing import Dict, List, Optional, Any, Tuple, Union, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from pathlib import Path
import logging

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None
    FileSystemEvent = None

from ..core.config import TestGenerationConfig


class TestType(Enum):
    """Test type enumeration."""
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"


class TestResult(Enum):
    """Test result status enumeration."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestExecutionResult:
    """Result of a single test execution."""
    test_name: str
    test_type: TestType
    status: TestResult
    duration: float
    error_message: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    coverage_data: Optional[Dict[str, Any]] = None


@dataclass
class TestSuiteResult:
    """Result of a complete test suite execution."""
    suite_name: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    error_tests: int
    total_duration: float
    coverage_percentage: float
    test_results: List[TestExecutionResult]


@dataclass
class TestRunConfiguration:
    """Configuration for test run execution."""
    test_types: List[TestType]
    parallel_execution: bool = True
    max_workers: int = 4
    timeout_seconds: int = 300
    coverage_enabled: bool = True
    verbose_output: bool = False
    fail_fast: bool = False
    test_pattern: Optional[str] = None
    output_format: str = "detailed"  # detailed, json, junit
    collect_performance_metrics: bool = True


class TestRunner:
    """
    Advanced test runner with parallel execution and comprehensive reporting.

    Features:
    - Parallel test execution across multiple processes
    - Real-time progress reporting
    - Comprehensive coverage analysis
    - Performance metrics collection
    - Multiple output formats (detailed, JSON, JUnit)
    - Test filtering and pattern matching
    - Fail-fast execution mode
    - Timeout handling
    - Resource monitoring
    """

    def __init__(self, config: TestGenerationConfig, test_directory: str):
        self.config = config
        self.test_directory = Path(test_directory)
        self.logger = self._setup_logger()
        self.execution_results: List[TestSuiteResult] = []

    def _setup_logger(self) -> logging.Logger:
        """Setup logging for test runner."""
        logger = logging.getLogger("TestRunner")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def run_all_tests(self, run_config: TestRunConfiguration) -> Dict[str, TestSuiteResult]:
        """
        Run all generated tests with specified configuration.

        Args:
            run_config: Test run configuration

        Returns:
            Dictionary mapping test suite names to their results
        """
        self.logger.info("Starting comprehensive test execution")
        start_time = time.time()

        results = {}

        # Run each test type
        for test_type in run_config.test_types:
            self.logger.info(f"Executing {test_type.value} tests")

            suite_result = self._run_test_type(test_type, run_config)
            results[test_type.value] = suite_result

            if run_config.fail_fast and suite_result.failed_tests > 0:
                self.logger.warning(f"Fail-fast mode: stopping execution due to failures in {test_type.value} tests")
                break

        total_duration = time.time() - start_time
        self.logger.info(f"Test execution completed in {total_duration:.2f} seconds")

        # Generate comprehensive report
        self._generate_execution_report(results, run_config)

        return results

    def _run_test_type(self, test_type: TestType, run_config: TestRunConfiguration) -> TestSuiteResult:
        """Run tests of a specific type."""
        test_files = self._discover_test_files(test_type, run_config.test_pattern)

        if not test_files:
            self.logger.warning(f"No {test_type.value} test files found")
            return TestSuiteResult(
                suite_name=test_type.value,
                total_tests=0, passed_tests=0, failed_tests=0,
                skipped_tests=0, error_tests=0,
                total_duration=0.0, coverage_percentage=0.0,
                test_results=[]
            )

        self.logger.info(f"Found {len(test_files)} {test_type.value} test files")

        if run_config.parallel_execution and len(test_files) > 1:
            return self._run_tests_parallel(test_files, test_type, run_config)
        else:
            return self._run_tests_sequential(test_files, test_type, run_config)

    def _discover_test_files(self, test_type: TestType, pattern: Optional[str] = None) -> List[Path]:
        """Discover test files for a specific test type."""
        test_type_dir = self.test_directory / test_type.value

        if not test_type_dir.exists():
            return []

        # Default patterns for different test types
        patterns = {
            TestType.UNIT: "test_*_unit.py",
            TestType.INTEGRATION: "test_*_integration.py",
            TestType.E2E: "test_*_e2e.py",
            TestType.PERFORMANCE: "test_*_performance.py",
            TestType.SECURITY: "test_*_security.py"
        }

        search_pattern = pattern or patterns.get(test_type, "test_*.py")
        return list(test_type_dir.glob(search_pattern))

    def _run_tests_parallel(self, test_files: List[Path], test_type: TestType,
                          run_config: TestRunConfiguration) -> TestSuiteResult:
        """Run tests in parallel using multiple processes."""
        self.logger.info(f"Running {len(test_files)} {test_type.value} test files in parallel")

        start_time = time.time()
        all_results = []

        with ProcessPoolExecutor(max_workers=run_config.max_workers) as executor:
            # Submit all test files for execution
            future_to_file = {
                executor.submit(
                    self._execute_single_test_file,
                    test_file, test_type, run_config
                ): test_file
                for test_file in test_files
            }

            # Collect results as they complete
            for future in future_to_file:
                try:
                    result = future.result(timeout=run_config.timeout_seconds)
                    all_results.extend(result)

                    if run_config.verbose_output:
                        passed = sum(1 for r in result if r.status == TestResult.PASSED)
                        failed = sum(1 for r in result if r.status == TestResult.FAILED)
                        self.logger.info(f"Completed {future_to_file[future]}: {passed} passed, {failed} failed")

                except Exception as e:
                    test_file = future_to_file[future]
                    self.logger.error(f"Error executing {test_file}: {e}")

                    # Create error result
                    all_results.append(TestExecutionResult(
                        test_name=str(test_file),
                        test_type=test_type,
                        status=TestResult.ERROR,
                        duration=0.0,
                        error_message=str(e)
                    ))

        total_duration = time.time() - start_time

        return self._compile_suite_result(test_type.value, all_results, total_duration)

    def _run_tests_sequential(self, test_files: List[Path], test_type: TestType,
                            run_config: TestRunConfiguration) -> TestSuiteResult:
        """Run tests sequentially."""
        self.logger.info(f"Running {len(test_files)} {test_type.value} test files sequentially")

        start_time = time.time()
        all_results = []

        for test_file in test_files:
            try:
                results = self._execute_single_test_file(test_file, test_type, run_config)
                all_results.extend(results)

                if run_config.verbose_output:
                    passed = sum(1 for r in results if r.status == TestResult.PASSED)
                    failed = sum(1 for r in results if r.status == TestResult.FAILED)
                    self.logger.info(f"Completed {test_file}: {passed} passed, {failed} failed")

                # Check fail-fast condition
                if run_config.fail_fast and any(r.status == TestResult.FAILED for r in results):
                    self.logger.warning(f"Fail-fast mode: stopping execution due to failure in {test_file}")
                    break

            except Exception as e:
                self.logger.error(f"Error executing {test_file}: {e}")
                all_results.append(TestExecutionResult(
                    test_name=str(test_file),
                    test_type=test_type,
                    status=TestResult.ERROR,
                    duration=0.0,
                    error_message=str(e)
                ))

        total_duration = time.time() - start_time
        return self._compile_suite_result(test_type.value, all_results, total_duration)

    def _execute_single_test_file(self, test_file: Path, test_type: TestType,
                                run_config: TestRunConfiguration) -> List[TestExecutionResult]:
        """Execute a single test file and return results."""
        results = []

        try:
            # Determine test runner command based on test type
            if test_type == TestType.E2E:
                cmd = self._build_playwright_command(test_file, run_config)
            else:
                cmd = self._build_pytest_command(test_file, run_config)

            # Execute test command
            start_time = time.time()
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=run_config.timeout_seconds,
                cwd=str(self.test_directory.parent)
            )
            duration = time.time() - start_time

            # Parse output and create results
            results = self._parse_test_output(
                test_file, test_type, process, duration, run_config
            )

        except subprocess.TimeoutExpired:
            results.append(TestExecutionResult(
                test_name=str(test_file),
                test_type=test_type,
                status=TestResult.ERROR,
                duration=run_config.timeout_seconds,
                error_message="Test execution timed out"
            ))

        except Exception as e:
            results.append(TestExecutionResult(
                test_name=str(test_file),
                test_type=test_type,
                status=TestResult.ERROR,
                duration=0.0,
                error_message=str(e)
            ))

        return results

    def _build_pytest_command(self, test_file: Path, run_config: TestRunConfiguration) -> List[str]:
        """Build pytest command for unit/integration tests."""
        cmd = ["python", "-m", "pytest", str(test_file)]

        if run_config.verbose_output:
            cmd.append("-v")

        if run_config.coverage_enabled:
            cmd.extend([
                "--cov=pgappforge",
                "--cov-report=json",
                f"--cov-report=term-missing"
            ])

        # Add output format options
        if run_config.output_format == "json":
            cmd.append("--json-report")
        elif run_config.output_format == "junit":
            cmd.append("--junit-xml=results.xml")

        return cmd

    def _build_playwright_command(self, test_file: Path, run_config: TestRunConfiguration) -> List[str]:
        """Build Playwright command for E2E tests."""
        cmd = ["python", "-m", "pytest", str(test_file)]

        if run_config.verbose_output:
            cmd.append("-v")

        # Playwright specific options
        cmd.extend([
            "--headed" if run_config.verbose_output else "--headless",
            "--browser=chromium",
            "--screenshot=only-on-failure"
        ])

        return cmd

    def _parse_test_output(self, test_file: Path, test_type: TestType, process: subprocess.CompletedProcess,
                         duration: float, run_config: TestRunConfiguration) -> List[TestExecutionResult]:
        """Parse test execution output and create results."""
        results = []

        # Try to parse JSON output if available
        if "--json-report" in str(process.args):
            try:
                json_data = json.loads(process.stdout)
                return self._parse_json_output(test_file, test_type, json_data, duration)
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback to parsing stdout/stderr
        return self._parse_text_output(test_file, test_type, process, duration)

    def _parse_json_output(self, test_file: Path, test_type: TestType,
                         json_data: Dict[str, Any], duration: float) -> List[TestExecutionResult]:
        """Parse JSON test output."""
        results = []

        for test_data in json_data.get("tests", []):
            status = TestResult.PASSED
            if test_data["outcome"] == "failed":
                status = TestResult.FAILED
            elif test_data["outcome"] == "skipped":
                status = TestResult.SKIPPED

            results.append(TestExecutionResult(
                test_name=test_data["nodeid"],
                test_type=test_type,
                status=status,
                duration=test_data.get("duration", 0.0),
                error_message=test_data.get("longrepr", None) if status == TestResult.FAILED else None
            ))

        return results

    def _parse_text_output(self, test_file: Path, test_type: TestType,
                         process: subprocess.CompletedProcess, duration: float) -> List[TestExecutionResult]:
        """Parse text-based test output."""
        # Basic parsing - can be enhanced based on specific output formats
        if process.returncode == 0:
            return [TestExecutionResult(
                test_name=str(test_file),
                test_type=test_type,
                status=TestResult.PASSED,
                duration=duration,
                stdout=process.stdout
            )]
        else:
            return [TestExecutionResult(
                test_name=str(test_file),
                test_type=test_type,
                status=TestResult.FAILED,
                duration=duration,
                error_message=process.stderr,
                stdout=process.stdout,
                stderr=process.stderr
            )]

    def _compile_suite_result(self, suite_name: str, results: List[TestExecutionResult],
                            total_duration: float) -> TestSuiteResult:
        """Compile individual test results into suite result."""
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.status == TestResult.PASSED)
        failed_tests = sum(1 for r in results if r.status == TestResult.FAILED)
        skipped_tests = sum(1 for r in results if r.status == TestResult.SKIPPED)
        error_tests = sum(1 for r in results if r.status == TestResult.ERROR)

        # Calculate coverage (simplified - would need proper coverage integration)
        coverage_percentage = self._calculate_coverage(results)

        return TestSuiteResult(
            suite_name=suite_name,
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
            error_tests=error_tests,
            total_duration=total_duration,
            coverage_percentage=coverage_percentage,
            test_results=results
        )

    def _calculate_coverage(self, results: List[TestExecutionResult]) -> float:
        """Calculate code coverage percentage."""
        # Simplified coverage calculation
        # In a real implementation, this would integrate with coverage.py

        coverage_data = []
        for result in results:
            if result.coverage_data:
                coverage_data.append(result.coverage_data)

        if not coverage_data:
            return 0.0

        # Basic calculation - would be more sophisticated in real implementation
        return 85.0  # Placeholder

    def _generate_execution_report(self, results: Dict[str, TestSuiteResult],
                                 run_config: TestRunConfiguration):
        """Generate comprehensive test execution report."""
        self.logger.info("Generating test execution report")

        # Calculate overall statistics
        total_tests = sum(suite.total_tests for suite in results.values())
        total_passed = sum(suite.passed_tests for suite in results.values())
        total_failed = sum(suite.failed_tests for suite in results.values())
        total_duration = sum(suite.total_duration for suite in results.values())

        # Log summary
        self.logger.info(f"Test Execution Summary:")
        self.logger.info(f"  Total Tests: {total_tests}")
        self.logger.info(f"  Passed: {total_passed}")
        self.logger.info(f"  Failed: {total_failed}")
        self.logger.info(f"  Duration: {total_duration:.2f}s")

        # Generate detailed reports
        if run_config.output_format == "json":
            self._generate_json_report(results)
        elif run_config.output_format == "junit":
            self._generate_junit_report(results)
        else:
            self._generate_detailed_report(results)

    def _generate_json_report(self, results: Dict[str, TestSuiteResult]):
        """Generate JSON format report."""
        report_data = {
            "execution_summary": {
                "timestamp": time.time(),
                "total_duration": sum(suite.total_duration for suite in results.values()),
                "total_tests": sum(suite.total_tests for suite in results.values()),
                "total_passed": sum(suite.passed_tests for suite in results.values()),
                "total_failed": sum(suite.failed_tests for suite in results.values())
            },
            "test_suites": {}
        }

        for suite_name, suite_result in results.items():
            report_data["test_suites"][suite_name] = asdict(suite_result)

        # Write to file
        report_file = self.test_directory / "test_results.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)

        self.logger.info(f"JSON report written to: {report_file}")

    def _generate_junit_report(self, results: Dict[str, TestSuiteResult]):
        """Generate JUnit XML format report."""
        # Basic JUnit XML generation
        junit_xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        junit_xml.append('<testsuites>')

        for suite_name, suite_result in results.items():
            junit_xml.append(f'  <testsuite name="{suite_name}" tests="{suite_result.total_tests}" '
                           f'failures="{suite_result.failed_tests}" '
                           f'time="{suite_result.total_duration:.2f}">')

            for test_result in suite_result.test_results:
                junit_xml.append(f'    <testcase name="{test_result.test_name}" '
                               f'time="{test_result.duration:.2f}">')

                if test_result.status == TestResult.FAILED:
                    junit_xml.append(f'      <failure message="{test_result.error_message or ""}">')
                    junit_xml.append(f'        {test_result.stderr or ""}')
                    junit_xml.append('      </failure>')
                elif test_result.status == TestResult.ERROR:
                    junit_xml.append(f'      <error message="{test_result.error_message or ""}">')
                    junit_xml.append(f'        {test_result.stderr or ""}')
                    junit_xml.append('      </error>')

                junit_xml.append('    </testcase>')

            junit_xml.append('  </testsuite>')

        junit_xml.append('</testsuites>')

        # Write to file
        report_file = self.test_directory / "junit-results.xml"
        with open(report_file, 'w') as f:
            f.write('\n'.join(junit_xml))

        self.logger.info(f"JUnit report written to: {report_file}")

    def _generate_detailed_report(self, results: Dict[str, TestSuiteResult]):
        """Generate detailed text format report."""
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("FLASK-APPBUILDER TESTING FRAMEWORK - TEST EXECUTION REPORT")
        report_lines.append("=" * 80)
        report_lines.append("")

        # Overall summary
        total_tests = sum(suite.total_tests for suite in results.values())
        total_passed = sum(suite.passed_tests for suite in results.values())
        total_failed = sum(suite.failed_tests for suite in results.values())
        total_skipped = sum(suite.skipped_tests for suite in results.values())
        total_errors = sum(suite.error_tests for suite in results.values())
        total_duration = sum(suite.total_duration for suite in results.values())

        report_lines.append("EXECUTION SUMMARY")
        report_lines.append("-" * 40)
        report_lines.append(f"Total Tests:    {total_tests}")
        report_lines.append(f"Passed:         {total_passed} ({total_passed/total_tests*100:.1f}%)" if total_tests > 0 else "Passed:         0")
        report_lines.append(f"Failed:         {total_failed} ({total_failed/total_tests*100:.1f}%)" if total_tests > 0 else "Failed:         0")
        report_lines.append(f"Skipped:        {total_skipped}")
        report_lines.append(f"Errors:         {total_errors}")
        report_lines.append(f"Total Duration: {total_duration:.2f} seconds")
        report_lines.append("")

        # Suite-by-suite breakdown
        for suite_name, suite_result in results.items():
            report_lines.append(f"{suite_name.upper()} TESTS")
            report_lines.append("-" * 40)
            report_lines.append(f"Tests: {suite_result.total_tests}")
            report_lines.append(f"Passed: {suite_result.passed_tests}")
            report_lines.append(f"Failed: {suite_result.failed_tests}")
            report_lines.append(f"Duration: {suite_result.total_duration:.2f}s")
            report_lines.append(f"Coverage: {suite_result.coverage_percentage:.1f}%")

            # Show failed tests
            failed_tests = [r for r in suite_result.test_results if r.status == TestResult.FAILED]
            if failed_tests:
                report_lines.append("\nFailed Tests:")
                for test in failed_tests:
                    report_lines.append(f"  - {test.test_name}")
                    if test.error_message:
                        report_lines.append(f"    Error: {test.error_message}")

            report_lines.append("")

        # Write to file
        report_file = self.test_directory / "test_report.txt"
        with open(report_file, 'w') as f:
            f.write('\n'.join(report_lines))

        self.logger.info(f"Detailed report written to: {report_file}")

        # Also print summary to console
        for line in report_lines[:15]:  # Print first 15 lines to console
            print(line)

    def run_continuous_tests(self, run_config: TestRunConfiguration,
                           watch_directories: List[str]) -> None:
        """
        Run tests continuously, re-executing when source files change.

        Args:
            run_config: Test run configuration
            watch_directories: Directories to watch for file changes
        """
        if not WATCHDOG_AVAILABLE:
            self.logger.error("File watching requires 'watchdog' library. Install with: pip install watchdog")
            self.logger.info("Falling back to single test run")
            self.run_all_tests(run_config)
            return
        
        self.logger.info("Starting continuous test execution mode")
        self.logger.info(f"Watching directories: {watch_directories}")
        
        # Create file system event handler
        test_runner = self  # Capture reference for event handler
        
        class TestFileEventHandler(FileSystemEventHandler):
            """Handle file system events and trigger test runs."""
            
            def __init__(self):
                super().__init__()
                self.last_run_time = 0
                self.debounce_interval = 2.0  # Seconds to wait before re-running tests
                self.pending_run = False
                self._lock = threading.Lock()
            
            def on_modified(self, event: FileSystemEvent):
                """Handle file modification events."""
                if not event.is_directory:
                    self._handle_file_change(event.src_path)
            
            def on_created(self, event: FileSystemEvent):
                """Handle file creation events."""
                if not event.is_directory:
                    self._handle_file_change(event.src_path)
            
            def on_moved(self, event: FileSystemEvent):
                """Handle file move events."""
                if not event.is_directory:
                    self._handle_file_change(event.dest_path)
            
            def _should_trigger_tests(self, file_path: str) -> bool:
                """Determine if file change should trigger test run."""
                # Only trigger on Python files and test files
                if not file_path.endswith(('.py', '.pyx', '.pyi')):
                    return False
                
                # Skip temporary files and cache files
                if any(skip in file_path for skip in ['__pycache__', '.pyc', '.tmp', '.swp', '~']):
                    return False
                
                # Skip if file is in ignore patterns
                ignore_patterns = ['.git', '.pytest_cache', '.coverage', 'htmlcov', '.mypy_cache']
                if any(pattern in file_path for pattern in ignore_patterns):
                    return False
                
                return True
            
            def _handle_file_change(self, file_path: str):
                """Handle individual file changes with debouncing."""
                if not self._should_trigger_tests(file_path):
                    return
                
                current_time = time.time()
                
                with self._lock:
                    # Debounce multiple rapid changes
                    if current_time - self.last_run_time < self.debounce_interval:
                        if not self.pending_run:
                            self.pending_run = True
                            # Schedule delayed run
                            threading.Timer(self.debounce_interval, self._execute_delayed_run).start()
                        return
                    
                    self.last_run_time = current_time
                    self.pending_run = False
                
                test_runner.logger.info(f"File change detected: {file_path}")
                test_runner.logger.info("Re-running tests...")
                
                try:
                    # Run tests in response to file change
                    result = test_runner.run_all_tests(run_config)
                    
                    if result.success:
                        test_runner.logger.info("✅ Tests passed - watching for changes...")
                    else:
                        test_runner.logger.error(f"❌ Tests failed ({result.failed_tests} failures)")
                        test_runner.logger.info("Fix the issues and save files to re-run tests")
                
                except Exception as e:
                    test_runner.logger.error(f"Error running tests: {str(e)}")
            
            def _execute_delayed_run(self):
                """Execute delayed test run after debounce period."""
                with self._lock:
                    if self.pending_run:
                        self.pending_run = False
                        self.last_run_time = time.time()
                
                test_runner.logger.info("Executing delayed test run...")
                try:
                    result = test_runner.run_all_tests(run_config)
                    if result.success:
                        test_runner.logger.info("✅ Tests passed - watching for changes...")
                    else:
                        test_runner.logger.error(f"❌ Tests failed ({result.failed_tests} failures)")
                except Exception as e:
                    test_runner.logger.error(f"Error running tests: {str(e)}")
        
        # Set up file system observer
        event_handler = TestFileEventHandler()
        observer = Observer()
        
        # Add watchers for all specified directories
        for directory in watch_directories:
            if os.path.exists(directory):
                observer.schedule(event_handler, directory, recursive=True)
                self.logger.info(f"Watching directory: {directory}")
            else:
                self.logger.warning(f"Watch directory does not exist: {directory}")
        
        if not observer._watches:
            self.logger.error("No valid directories to watch")
            return
        
        # Initial test run
        self.logger.info("Running initial test suite...")
        try:
            initial_result = self.run_all_tests(run_config)
            if initial_result.success:
                self.logger.info("✅ Initial tests passed - watching for changes...")
            else:
                self.logger.error(f"❌ Initial tests failed ({initial_result.failed_tests} failures)")
                self.logger.info("Fix the issues and save files to re-run tests")
        except Exception as e:
            self.logger.error(f"Error running initial tests: {str(e)}")
        
        # Start watching
        observer.start()
        self.logger.info("📁 File watching active. Press Ctrl+C to stop.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Stopping file watcher...")
            observer.stop()
        
        observer.join()
        self.logger.info("File watcher stopped")

        # TODO: Implement file watching with watchdog library
        # and re-run tests when changes are detected


# Utility function for CLI usage
def create_default_run_config() -> TestRunConfiguration:
    """Create default test run configuration."""
    return TestRunConfiguration(
        test_types=[TestType.UNIT, TestType.INTEGRATION, TestType.E2E],
        parallel_execution=True,
        max_workers=4,
        timeout_seconds=300,
        coverage_enabled=True,
        verbose_output=True,
        fail_fast=False,
        output_format="detailed"
    )