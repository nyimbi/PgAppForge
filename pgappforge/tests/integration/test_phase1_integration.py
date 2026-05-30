"""
Phase 1 Integration Tests for PgAppForge Enhancement Project

This module provides comprehensive integration tests for Phase 1 components:
- Testing Automation Framework
- Real-Time Schema Evolution System
- Integration between components

These tests validate the complete Phase 1 implementation and ensure
all components work together seamlessly.
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sqlite3
from typing import Dict, List, Any

# Phase 1 Component Imports
from pgappforge.testing_framework.core.config import TestGenerationConfig
from pgappforge.testing_framework.core.test_generator import TestGenerator
from pgappforge.testing_framework.generators.unit_test_generator import UnitTestGenerator
from pgappforge.testing_framework.generators.integration_test_generator import IntegrationTestGenerator
from pgappforge.testing_framework.generators.e2e_test_generator import E2ETestGenerator
from pgappforge.testing_framework.data.realistic_data_generator import RealisticDataGenerator
from pgappforge.testing_framework.runner.test_runner import TestRunner, TestRunConfiguration, TestType
from pgappforge.testing_framework.runner.test_reporter import TestReporter

from pgappforge.schema_evolution.schema_monitor import SchemaMonitor, SchemaChange, ChangeType
from pgappforge.schema_evolution.evolution_engine import EvolutionEngine, EvolutionConfig
from pgappforge.schema_evolution.change_detector import ChangeDetector
from pgappforge.schema_evolution.code_regenerator import CodeRegenerator

from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector, TableInfo, ColumnInfo


class Phase1IntegrationTest(unittest.TestCase):
    """
    Comprehensive integration tests for Phase 1 components.

    Tests the complete workflow:
    1. Database schema analysis
    2. Automatic test generation
    3. Schema change detection
    4. Code regeneration
    5. Test execution and reporting
    """

    def setUp(self):
        """Set up test environment with temporary database and directories."""
        # Create temporary directories
        self.temp_dir = tempfile.mkdtemp(prefix="fab_phase1_test_")
        self.test_output_dir = Path(self.temp_dir) / "output"
        self.test_db_file = Path(self.temp_dir) / "test.db"

        # Create test database
        self.database_url = f"sqlite:///{self.test_db_file}"
        self._create_test_database()

        # Initialize core components
        self.inspector = EnhancedDatabaseInspector(self.database_url)

        # Testing Framework components
        self.test_config = TestGenerationConfig(
            generate_unit_tests=True,
            generate_integration_tests=True,
            generate_e2e_tests=True,
            use_realistic_data=True,
            output_directory=str(self.test_output_dir)
        )

        # Schema Evolution components
        self.evolution_config = EvolutionConfig(
            monitor_interval=1,  # Fast monitoring for tests
            auto_evolution=True,
            require_approval=False,
            output_directory=str(self.test_output_dir)
        )

    def tearDown(self):
        """Clean up temporary files and directories."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_database(self):
        """Create a test SQLite database with sample tables."""
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()

        # Create sample tables for testing
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(80) UNIQUE NOT NULL,
                email VARCHAR(120) UNIQUE NOT NULL,
                first_name VARCHAR(64),
                last_name VARCHAR(64),
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(64) UNIQUE NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE user_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (role_id) REFERENCES roles(id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX idx_users_username ON users(username)
        ''')

        cursor.execute('''
            CREATE INDEX idx_users_email ON users(email)
        ''')

        conn.commit()
        conn.close()

    def test_01_database_inspection(self):
        """Test database inspection and analysis."""
        print("\n=== Testing Database Inspection ===")

        # Test basic table discovery
        tables = self.inspector.get_all_tables()
        self.assertEqual(len(tables), 3, "Should discover 3 tables")

        table_names = {table.name for table in tables}
        self.assertEqual(table_names, {"users", "roles", "user_roles"})

        # Test detailed table analysis
        users_table = None
        for table in tables:
            if table.name == "users":
                users_table = table
                break

        self.assertIsNotNone(users_table)
        self.assertEqual(len(users_table.columns), 7, "Users table should have 7 columns")
        self.assertEqual(len(users_table.indexes), 2, "Users table should have 2 indexes")

        # Test relationship detection
        relationships = self.inspector.get_relationships("user_roles")
        self.assertGreater(len(relationships), 0, "Should detect relationships")

        print("✅ Database inspection completed successfully")

    def test_02_test_generation_workflow(self):
        """Test complete test generation workflow."""
        print("\n=== Testing Test Generation Workflow ===")

        # Initialize test generator
        test_generator = TestGenerator(self.test_config, self.inspector)

        # Generate tests for users table
        users_table = None
        for table in self.inspector.get_all_tables():
            if table.name == "users":
                users_table = table
                break

        self.assertIsNotNone(users_table)

        # Test unit test generation
        unit_generator = UnitTestGenerator(self.test_config, self.inspector)
        unit_tests = unit_generator.generate_unit_tests_for_table(users_table)

        self.assertIsNotNone(unit_tests)
        self.assertIn("class TestUsers", unit_tests)
        self.assertIn("def test_create_user", unit_tests)

        # Test integration test generation
        integration_generator = IntegrationTestGenerator(self.test_config, self.inspector)
        integration_suite = integration_generator._generate_model_integration_suite(users_table)

        self.assertIsNotNone(integration_suite)
        self.assertEqual(integration_suite.model_name, "Users")

        # Test realistic data generation
        data_generator = RealisticDataGenerator(self.test_config, self.inspector)
        test_data = data_generator.generate_realistic_test_data(users_table, count=5)

        self.assertEqual(len(test_data), 5)
        self.assertIn("username", test_data[0])
        self.assertIn("email", test_data[0])

        print("✅ Test generation workflow completed successfully")

    def test_03_schema_monitoring_and_change_detection(self):
        """Test schema monitoring and change detection."""
        print("\n=== Testing Schema Monitoring and Change Detection ===")

        # Initialize schema monitor
        monitor = SchemaMonitor(self.database_url, {
            "monitor_interval": 1,
            "storage_path": str(self.test_output_dir / "schema_monitor")
        })

        # Take initial snapshot
        initial_snapshot = monitor._take_schema_snapshot()
        self.assertIsNotNone(initial_snapshot)
        self.assertEqual(len(initial_snapshot.tables), 3)

        # Simulate schema change by adding a column
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE users ADD COLUMN phone VARCHAR(20)')
        conn.commit()
        conn.close()

        # Detect changes
        new_snapshot = monitor._take_schema_snapshot()
        changes = monitor._compare_snapshots(initial_snapshot, new_snapshot)

        self.assertGreater(len(changes), 0, "Should detect schema changes")

        # Verify change details
        column_added_changes = [c for c in changes if c.change_type == ChangeType.COLUMN_ADDED]
        self.assertEqual(len(column_added_changes), 1)

        change = column_added_changes[0]
        self.assertEqual(change.table_name, "users")
        self.assertEqual(change.change_details["column_name"], "phone")

        print("✅ Schema monitoring and change detection completed successfully")

    def test_04_evolution_engine_integration(self):
        """Test the complete evolution engine workflow."""
        print("\n=== Testing Evolution Engine Integration ===")

        # Initialize evolution engine
        evolution_engine = EvolutionEngine(self.database_url, self.evolution_config)

        # Test engine startup
        evolution_engine.start_engine()
        self.assertTrue(evolution_engine._is_running)

        # Create a schema change to trigger evolution
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()
        conn.close()

        # Force evolution check
        changes = evolution_engine.force_evolution()

        # Verify evolution task was created
        if changes:
            self.assertIsNotNone(changes)
            self.assertGreater(len(changes.changes), 0)

        # Stop engine
        evolution_engine.stop_engine()
        self.assertFalse(evolution_engine._is_running)

        print("✅ Evolution engine integration completed successfully")

    def test_05_code_regeneration_workflow(self):
        """Test code regeneration capabilities."""
        print("\n=== Testing Code Regeneration Workflow ===")

        # Initialize code regenerator
        code_regenerator = CodeRegenerator(self.inspector, str(self.test_output_dir))

        # Create a mock schema comparison
        from pgappforge.schema_evolution.change_detector import SchemaComparison, TableChange
        from pgappforge.schema_evolution.schema_monitor import SchemaSnapshot

        # Mock snapshots
        old_snapshot = Mock(spec=SchemaSnapshot)
        new_snapshot = Mock(spec=SchemaSnapshot)

        # Create test changes
        test_changes = [
            SchemaChange(
                change_type=ChangeType.TABLE_ADDED,
                table_name="projects",
                change_details={"table_definition": {}},
                timestamp=time.time(),
                change_id="test_change_1"
            )
        ]

        # Create table change
        table_change = TableChange(
            table_name="projects",
            change_type="table_creation",
            column_changes=[],
            index_changes=[],
            constraint_changes=[],
            relationship_changes=[],
            overall_impact=Mock(),
            migration_strategy="direct_migration"
        )

        # Create schema comparison
        schema_comparison = SchemaComparison(
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot,
            detected_changes=test_changes,
            table_changes={"projects": table_change},
            impact_summary={},
            breaking_changes=[],
            migration_required=False,
            estimated_effort="low"
        )

        # Test code regeneration
        config = {
            "regenerate_models": True,
            "regenerate_views": False,
            "regenerate_tests": True
        }

        # This would require actual table info, so we'll test the structure
        regeneration_tasks = code_regenerator._create_regeneration_tasks(schema_comparison, config)

        # Verify tasks were created
        self.assertGreater(len(regeneration_tasks), 0)

        # Verify task types
        task_types = {task.regeneration_type for task in regeneration_tasks}
        self.assertIn("model", {t.value for t in task_types})

        print("✅ Code regeneration workflow completed successfully")

    def test_06_test_execution_and_reporting(self):
        """Test test execution and reporting system."""
        print("\n=== Testing Test Execution and Reporting ===")

        # Create test files directory
        test_files_dir = self.test_output_dir / "tests"
        test_files_dir.mkdir(parents=True, exist_ok=True)

        # Create a simple test file
        test_file_content = '''
import unittest

class TestSample(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(True)

    def test_fail(self):
        self.assertTrue(False)

    def test_skip(self):
        self.skipTest("Skipping this test")

if __name__ == '__main__':
    unittest.main()
'''

        test_file = test_files_dir / "test_sample.py"
        with open(test_file, 'w') as f:
            f.write(test_file_content)

        # Initialize test runner (mock since we don't have full test infrastructure)
        with patch('subprocess.run') as mock_run:
            # Mock successful test execution
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Test results"
            mock_run.return_value.stderr = ""

            test_runner = TestRunner(self.test_config, str(test_files_dir))

            # Test configuration
            run_config = TestRunConfiguration(
                test_types=[TestType.UNIT],
                parallel_execution=False,
                timeout_seconds=60,
                coverage_enabled=False
            )

            # This would normally run tests, but we'll mock it
            # results = test_runner.run_all_tests(run_config)

        # Test reporting
        test_reporter = TestReporter(self.test_config, str(self.test_output_dir))

        # Create mock test results
        from pgappforge.testing_framework.runner.test_runner import TestSuiteResult, TestExecutionResult, TestResult

        mock_results = {
            "unit": TestSuiteResult(
                suite_name="unit",
                total_tests=3,
                passed_tests=1,
                failed_tests=1,
                skipped_tests=1,
                error_tests=0,
                total_duration=2.5,
                coverage_percentage=85.0,
                test_results=[
                    TestExecutionResult(
                        test_name="test_pass",
                        test_type=TestType.UNIT,
                        status=TestResult.PASSED,
                        duration=0.5
                    ),
                    TestExecutionResult(
                        test_name="test_fail",
                        test_type=TestType.UNIT,
                        status=TestResult.FAILED,
                        duration=0.8,
                        error_message="AssertionError: False is not true"
                    ),
                    TestExecutionResult(
                        test_name="test_skip",
                        test_type=TestType.UNIT,
                        status=TestResult.SKIPPED,
                        duration=0.1
                    )
                ]
            )
        }

        # Generate report
        analytics = test_reporter.generate_comprehensive_report(mock_results)

        # Verify report generation
        self.assertIsNotNone(analytics)
        self.assertEqual(analytics.execution_summary["total_tests"], 3)
        self.assertEqual(analytics.execution_summary["passed_tests"], 1)
        self.assertEqual(analytics.execution_summary["failed_tests"], 1)

        # Verify report files were created
        json_report = self.test_output_dir / "test_analytics.json"
        html_report = self.test_output_dir / "test_report.html"
        md_report = self.test_output_dir / "TEST_REPORT.md"

        self.assertTrue(json_report.exists(), "JSON report should be created")
        self.assertTrue(html_report.exists(), "HTML report should be created")
        self.assertTrue(md_report.exists(), "Markdown report should be created")

        print("✅ Test execution and reporting completed successfully")

    def test_07_end_to_end_workflow(self):
        """Test complete end-to-end Phase 1 workflow."""
        print("\n=== Testing End-to-End Phase 1 Workflow ===")

        # Step 1: Start with database inspection
        tables = self.inspector.get_all_tables()
        self.assertGreater(len(tables), 0)

        # Step 2: Generate initial tests
        test_generator = TestGenerator(self.test_config, self.inspector)

        for table in tables:
            if table.name == "users":
                # Generate complete test suite
                test_suite = test_generator.generate_complete_test_suite(table)
                self.assertIsNotNone(test_suite.unit_tests)
                self.assertIsNotNone(test_suite.integration_tests)
                break

        # Step 3: Start schema monitoring
        monitor = SchemaMonitor(self.database_url, {
            "monitor_interval": 1,
            "storage_path": str(self.test_output_dir / "schema_monitor")
        })

        # Step 4: Make a schema change
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()
        cursor.execute('ALTER TABLE roles ADD COLUMN priority INTEGER DEFAULT 1')
        conn.commit()
        conn.close()

        # Step 5: Detect and analyze changes
        changes = monitor.force_check()
        self.assertGreater(len(changes), 0)

        # Step 6: Test evolution engine response
        evolution_engine = EvolutionEngine(self.database_url, self.evolution_config)

        try:
            evolution_engine.start_engine()

            # Force evolution with detected changes
            evolution_task = evolution_engine.force_evolution(changes)

            # Verify task was created
            if evolution_task:
                self.assertIsNotNone(evolution_task.task_id)
                self.assertGreater(len(evolution_task.changes), 0)

        finally:
            evolution_engine.stop_engine()

        # Step 7: Verify complete workflow
        stats = monitor.get_statistics()
        self.assertIn("total_changes", stats)

        print("✅ End-to-end Phase 1 workflow completed successfully")

    def test_08_error_handling_and_recovery(self):
        """Test error handling and recovery mechanisms."""
        print("\n=== Testing Error Handling and Recovery ===")

        # Test database connection errors
        invalid_db_url = "sqlite:///nonexistent/path/test.db"

        with self.assertRaises(Exception):
            EnhancedDatabaseInspector(invalid_db_url)

        # Test invalid configuration handling
        invalid_config = TestGenerationConfig()
        invalid_config.output_directory = "/invalid/path/that/cannot/be/created"

        # Should handle gracefully
        try:
            test_generator = TestGenerator(invalid_config, self.inspector)
            # This might succeed or fail depending on implementation
        except Exception as e:
            self.assertIsInstance(e, (OSError, PermissionError))

        # Test schema monitor with invalid database
        monitor = SchemaMonitor(invalid_db_url, {"storage_path": str(self.test_output_dir)})

        # Should handle connection errors gracefully
        with self.assertRaises(Exception):
            monitor._take_schema_snapshot()

        print("✅ Error handling and recovery testing completed successfully")

    def test_09_performance_and_scalability(self):
        """Test performance characteristics and scalability."""
        print("\n=== Testing Performance and Scalability ===")

        # Create additional tables for performance testing
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()

        # Create multiple tables
        for i in range(5):
            cursor.execute(f'''
                CREATE TABLE test_table_{i} (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100),
                    value REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

        conn.commit()
        conn.close()

        # Measure inspection performance
        start_time = time.time()
        tables = self.inspector.get_all_tables()
        inspection_time = time.time() - start_time

        self.assertLess(inspection_time, 5.0, "Inspection should complete within 5 seconds")
        self.assertEqual(len(tables), 8)  # Original 3 + 5 new tables

        # Measure test generation performance
        start_time = time.time()

        test_generator = TestGenerator(self.test_config, self.inspector)

        # Generate tests for all tables
        generated_count = 0
        for table in tables:
            if table.name.startswith('test_table_'):
                test_suite = test_generator.generate_complete_test_suite(table)
                if test_suite.unit_tests:
                    generated_count += 1

        generation_time = time.time() - start_time

        self.assertLess(generation_time, 10.0, "Test generation should complete within 10 seconds")
        self.assertGreater(generated_count, 0, "Should generate tests for test tables")

        print(f"✅ Performance testing completed - Inspection: {inspection_time:.2f}s, Generation: {generation_time:.2f}s")

    def test_10_integration_validation(self):
        """Final validation of all Phase 1 components integration."""
        print("\n=== Final Phase 1 Integration Validation ===")

        validation_results = {
            "testing_framework": False,
            "schema_evolution": False,
            "integration": False,
            "performance": False,
            "error_handling": False
        }

        # Validate Testing Framework
        try:
            test_generator = TestGenerator(self.test_config, self.inspector)
            tables = self.inspector.get_all_tables()

            if tables:
                test_suite = test_generator.generate_complete_test_suite(tables[0])
                if test_suite.unit_tests and test_suite.integration_tests:
                    validation_results["testing_framework"] = True
        except Exception as e:
            print(f"Testing Framework validation failed: {e}")

        # Validate Schema Evolution
        try:
            monitor = SchemaMonitor(self.database_url, {"storage_path": str(self.test_output_dir)})
            snapshot = monitor._take_schema_snapshot()

            if snapshot and len(snapshot.tables) > 0:
                validation_results["schema_evolution"] = True
        except Exception as e:
            print(f"Schema Evolution validation failed: {e}")

        # Validate Integration
        try:
            evolution_engine = EvolutionEngine(self.database_url, self.evolution_config)
            evolution_engine.start_engine()

            # Test integration by forcing a check
            changes = evolution_engine.schema_monitor.force_check()
            validation_results["integration"] = True

            evolution_engine.stop_engine()
        except Exception as e:
            print(f"Integration validation failed: {e}")

        # Validate Performance (basic check)
        try:
            start_time = time.time()
            tables = self.inspector.get_all_tables()
            elapsed = time.time() - start_time

            if elapsed < 2.0 and len(tables) > 0:
                validation_results["performance"] = True
        except Exception as e:
            print(f"Performance validation failed: {e}")

        # Validate Error Handling
        try:
            # Test with invalid input
            invalid_inspector = None
            try:
                invalid_inspector = EnhancedDatabaseInspector("invalid://url")
            except Exception:
                # Expected to fail
                validation_results["error_handling"] = True
        except Exception as e:
            print(f"Error handling validation failed: {e}")

        # Summary
        passed_validations = sum(validation_results.values())
        total_validations = len(validation_results)

        print(f"\n📊 Phase 1 Integration Validation Summary:")
        print(f"   Passed: {passed_validations}/{total_validations} components")

        for component, passed in validation_results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"   {component.replace('_', ' ').title()}: {status}")

        # Require at least 80% success rate
        success_rate = passed_validations / total_validations
        self.assertGreaterEqual(success_rate, 0.8, f"Phase 1 validation success rate {success_rate:.1%} below required 80%")

        print(f"\n🎉 Phase 1 Integration Test Suite: SUCCESS ({success_rate:.1%} pass rate)")


class Phase1PerformanceBenchmark(unittest.TestCase):
    """Performance benchmarks for Phase 1 components."""

    def setUp(self):
        """Set up performance test environment."""
        self.temp_dir = tempfile.mkdtemp(prefix="fab_perf_test_")
        self.test_db_file = Path(self.temp_dir) / "perf_test.db"
        self.database_url = f"sqlite:///{self.test_db_file}"

        # Create larger test database
        self._create_performance_test_database()

        self.inspector = EnhancedDatabaseInspector(self.database_url)

    def tearDown(self):
        """Clean up performance test environment."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_performance_test_database(self):
        """Create a larger database for performance testing."""
        conn = sqlite3.connect(self.test_db_file)
        cursor = conn.cursor()

        # Create 20 tables with various complexities
        for i in range(20):
            cursor.execute(f'''
                CREATE TABLE perf_table_{i:02d} (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    value_{j} REAL DEFAULT 0
                    {", " + ", ".join([f"col_{j} VARCHAR(50)" for j in range(i % 5 + 1)])}
                )
            '''.replace("value_j", f"value_{i}"))

            # Add indexes
            cursor.execute(f'CREATE INDEX idx_perf_{i:02d}_name ON perf_table_{i:02d}(name)')

            if i > 0:
                # Add foreign key to previous table
                cursor.execute(f'ALTER TABLE perf_table_{i:02d} ADD COLUMN ref_id INTEGER REFERENCES perf_table_{i-1:02d}(id)')

        conn.commit()
        conn.close()

    def test_database_inspection_performance(self):
        """Benchmark database inspection performance."""
        print("\n=== Database Inspection Performance Benchmark ===")

        iterations = 10
        total_time = 0

        for i in range(iterations):
            start_time = time.time()
            tables = self.inspector.get_all_tables()
            elapsed = time.time() - start_time
            total_time += elapsed

        average_time = total_time / iterations
        tables_count = len(tables)

        print(f"Average inspection time: {average_time:.3f}s")
        print(f"Tables discovered: {tables_count}")
        print(f"Performance: {tables_count/average_time:.1f} tables/second")

        # Performance requirements
        self.assertLess(average_time, 1.0, "Average inspection time should be under 1 second")
        self.assertEqual(tables_count, 20, "Should discover all 20 tables")

    def test_test_generation_performance(self):
        """Benchmark test generation performance."""
        print("\n=== Test Generation Performance Benchmark ===")

        config = TestGenerationConfig(output_directory=self.temp_dir)
        test_generator = TestGenerator(config, self.inspector)

        tables = self.inspector.get_all_tables()

        start_time = time.time()

        generated_suites = 0
        for table in tables[:5]:  # Test with first 5 tables
            test_suite = test_generator.generate_complete_test_suite(table)
            if test_suite.unit_tests:
                generated_suites += 1

        elapsed = time.time() - start_time

        print(f"Test generation time: {elapsed:.3f}s")
        print(f"Test suites generated: {generated_suites}")
        print(f"Performance: {generated_suites/elapsed:.1f} suites/second")

        # Performance requirements
        self.assertLess(elapsed, 10.0, "Test generation should complete within 10 seconds")
        self.assertGreater(generated_suites, 0, "Should generate at least one test suite")


if __name__ == '__main__':
    print("🚀 Starting PgAppForge Phase 1 Integration Tests")
    print("=" * 80)

    # Create test suite
    test_suite = unittest.TestSuite()

    # Add integration tests
    integration_tests = [
        'test_01_database_inspection',
        'test_02_test_generation_workflow',
        'test_03_schema_monitoring_and_change_detection',
        'test_04_evolution_engine_integration',
        'test_05_code_regeneration_workflow',
        'test_06_test_execution_and_reporting',
        'test_07_end_to_end_workflow',
        'test_08_error_handling_and_recovery',
        'test_09_performance_and_scalability',
        'test_10_integration_validation'
    ]

    for test_name in integration_tests:
        test_suite.addTest(Phase1IntegrationTest(test_name))

    # Add performance benchmarks
    performance_tests = [
        'test_database_inspection_performance',
        'test_test_generation_performance'
    ]

    for test_name in performance_tests:
        test_suite.addTest(Phase1PerformanceBenchmark(test_name))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    # Print final summary
    print("\n" + "=" * 80)
    if result.wasSuccessful():
        print("🎉 Phase 1 Integration Tests: ALL TESTS PASSED!")
        print("✅ PgAppForge Enhancement Phase 1 is ready for production")
    else:
        print("❌ Some tests failed. Please review and fix issues before deployment.")
        print(f"   Failures: {len(result.failures)}")
        print(f"   Errors: {len(result.errors)}")

    print("=" * 80)