#!/usr/bin/env python3
"""
Phase 1 Validation Script for Flask-AppBuilder Enhancement Project

This script validates the complete Phase 1 implementation including:
- Testing Automation Framework
- Real-Time Schema Evolution System
- Integration and performance benchmarks

Usage:
    python validate_phase1.py [--verbose] [--skip-performance] [--output-dir DIR]
"""

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    # Import Phase 1 components
    from flask_appbuilder.testing_framework.core.config import TestGenerationConfig
    from flask_appbuilder.testing_framework.core.test_generator import TestGenerator
    from flask_appbuilder.testing_framework.runners import TestRunner, TestReporter
    from flask_appbuilder.schema_evolution.schema_monitor import SchemaMonitor
    from flask_appbuilder.schema_evolution.evolution_engine import EvolutionEngine, EvolutionConfig
    from flask_appbuilder.cli.generators.database_inspector import EnhancedDatabaseInspector

    IMPORTS_SUCCESSFUL = True
except ImportError as e:
    IMPORTS_SUCCESSFUL = False
    IMPORT_ERROR = str(e)


class Phase1Validator:
    """Phase 1 implementation validator."""

    def __init__(self, verbose: bool = False, output_dir: Optional[str] = None):
        self.verbose = verbose
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="fab_validation_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Results tracking
        self.results = {
            "timestamp": time.time(),
            "version": "Phase 1",
            "status": "unknown",
            "components": {},
            "performance": {},
            "errors": [],
            "warnings": []
        }

        # Test database
        self.test_db = self.output_dir / "validation.db"
        self.database_url = f"sqlite:///{self.test_db}"

    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"[{timestamp}] {level.upper()}: "

        if level == "ERROR":
            print(f"\033[91m{prefix}{message}\033[0m")  # Red
        elif level == "WARN":
            print(f"\033[93m{prefix}{message}\033[0m")  # Yellow
        elif level == "SUCCESS":
            print(f"\033[92m{prefix}{message}\033[0m")  # Green
        elif self.verbose:
            print(f"{prefix}{message}")

    def create_test_database(self):
        """Create a test database for validation."""
        try:
            import sqlite3

            conn = sqlite3.connect(self.test_db)
            cursor = conn.cursor()

            # Create test schema
            cursor.execute('''
                CREATE TABLE validation_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    email VARCHAR(120) UNIQUE NOT NULL,
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE validation_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(64) UNIQUE NOT NULL,
                    description TEXT
                )
            ''')

            cursor.execute('''
                CREATE INDEX idx_validation_users_email ON validation_users(email)
            ''')

            conn.commit()
            conn.close()

            self.log("Test database created successfully")
            return True

        except Exception as e:
            self.log(f"Failed to create test database: {e}", "ERROR")
            return False

    def validate_imports(self) -> bool:
        """Validate that all required imports are available."""
        self.log("Validating Phase 1 component imports...")

        if not IMPORTS_SUCCESSFUL:
            self.log(f"Import validation failed: {IMPORT_ERROR}", "ERROR")
            self.results["components"]["imports"] = {
                "status": "failed",
                "error": IMPORT_ERROR
            }
            return False

        # Test specific imports
        required_components = [
            ("TestGenerationConfig", TestGenerationConfig),
            ("TestGenerator", TestGenerator),
            ("SchemaMonitor", SchemaMonitor),
            ("EvolutionEngine", EvolutionEngine),
            ("EnhancedDatabaseInspector", EnhancedDatabaseInspector)
        ]

        failed_imports = []
        for name, component in required_components:
            try:
                # Try to instantiate or call basic methods
                if name == "TestGenerationConfig":
                    TestGenerationConfig()
                elif name == "EvolutionConfig":
                    EvolutionConfig()
                # Others require database connection, so just check they exist
                elif hasattr(component, '__name__'):
                    pass
                else:
                    raise ImportError(f"Component {name} not properly imported")

                self.log(f"✓ {name} import successful", "SUCCESS" if self.verbose else "INFO")

            except Exception as e:
                failed_imports.append((name, str(e)))
                self.log(f"✗ {name} import failed: {e}", "ERROR")

        if failed_imports:
            self.results["components"]["imports"] = {
                "status": "failed",
                "failed_components": failed_imports
            }
            return False

        self.results["components"]["imports"] = {
            "status": "passed",
            "components_validated": len(required_components)
        }

        self.log("All component imports validated successfully", "SUCCESS")
        return True

    def validate_database_inspector(self) -> bool:
        """Validate database inspector functionality."""
        self.log("Validating Database Inspector...")

        try:
            inspector = EnhancedDatabaseInspector(self.database_url)

            # Test basic functionality
            start_time = time.time()
            tables = inspector.get_all_tables()
            inspection_time = time.time() - start_time

            if len(tables) != 2:
                raise ValueError(f"Expected 2 tables, found {len(tables)}")

            # Test detailed analysis
            table_names = {table.name for table in tables}
            expected_tables = {"validation_users", "validation_roles"}

            if table_names != expected_tables:
                raise ValueError(f"Table names mismatch. Expected {expected_tables}, got {table_names}")

            # Test column analysis
            users_table = next(table for table in tables if table.name == "validation_users")
            if len(users_table.columns) != 5:
                raise ValueError(f"Expected 5 columns in users table, found {len(users_table.columns)}")

            # Test index detection
            if len(users_table.indexes) == 0:
                self.results["warnings"].append("No indexes detected in users table")

            self.results["components"]["database_inspector"] = {
                "status": "passed",
                "tables_discovered": len(tables),
                "inspection_time": inspection_time,
                "columns_analyzed": sum(len(table.columns) for table in tables),
                "indexes_found": sum(len(table.indexes) for table in tables)
            }

            self.log(f"Database Inspector validation successful ({inspection_time:.3f}s)", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Database Inspector validation failed: {e}", "ERROR")
            self.results["components"]["database_inspector"] = {
                "status": "failed",
                "error": str(e)
            }
            return False

    def validate_testing_framework(self) -> bool:
        """Validate Testing Automation Framework."""
        self.log("Validating Testing Automation Framework...")

        try:
            inspector = EnhancedDatabaseInspector(self.database_url)
            config = TestGenerationConfig(
                generate_unit_tests=True,
                generate_integration_tests=True,
                output_directory=str(self.output_dir / "tests")
            )

            test_generator = TestGenerator(config, inspector)

            # Test basic functionality
            tables = inspector.get_all_tables()
            users_table = next(table for table in tables if table.name == "validation_users")

            start_time = time.time()
            test_suite = test_generator.generate_complete_test_suite(users_table)
            generation_time = time.time() - start_time

            # Validate generated tests
            tests_generated = []
            if test_suite.unit_tests:
                tests_generated.append("unit")
            if test_suite.integration_tests:
                tests_generated.append("integration")

            if not tests_generated:
                raise ValueError("No tests were generated")

            # Test realistic data generation
            from flask_appbuilder.testing_framework.data.realistic_data_generator import RealisticDataGenerator

            data_generator = RealisticDataGenerator(config, inspector)
            test_data = data_generator.generate_realistic_test_data(users_table, count=3)

            if len(test_data) != 3:
                raise ValueError(f"Expected 3 test data records, got {len(test_data)}")

            self.results["components"]["testing_framework"] = {
                "status": "passed",
                "generation_time": generation_time,
                "test_types_generated": tests_generated,
                "test_data_records": len(test_data)
            }

            self.log(f"Testing Framework validation successful ({generation_time:.3f}s)", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Testing Framework validation failed: {e}", "ERROR")
            self.results["components"]["testing_framework"] = {
                "status": "failed",
                "error": str(e)
            }
            if self.verbose:
                traceback.print_exc()
            return False

    def validate_schema_evolution(self) -> bool:
        """Validate Schema Evolution System."""
        self.log("Validating Schema Evolution System...")

        try:
            # Test Schema Monitor
            monitor = SchemaMonitor(self.database_url, {
                "monitor_interval": 1,
                "storage_path": str(self.output_dir / "schema_monitor")
            })

            start_time = time.time()
            initial_snapshot = monitor._take_schema_snapshot()
            snapshot_time = time.time() - start_time

            if not initial_snapshot:
                raise ValueError("Failed to take initial schema snapshot")

            if len(initial_snapshot.tables) != 2:
                raise ValueError(f"Snapshot should contain 2 tables, found {len(initial_snapshot.tables)}")

            # Test change detection by modifying schema
            import sqlite3
            conn = sqlite3.connect(self.test_db)
            cursor = conn.cursor()
            cursor.execute('ALTER TABLE validation_users ADD COLUMN phone VARCHAR(20)')
            conn.commit()
            conn.close()

            # Detect changes
            new_snapshot = monitor._take_schema_snapshot()
            changes = monitor._compare_snapshots(initial_snapshot, new_snapshot)

            if len(changes) == 0:
                raise ValueError("Schema change was not detected")

            # Test Evolution Engine
            evolution_config = EvolutionConfig(
                monitor_interval=1,
                auto_evolution=False,
                output_directory=str(self.output_dir / "evolution")
            )

            evolution_engine = EvolutionEngine(self.database_url, evolution_config)

            # Test engine startup/shutdown
            evolution_engine.start_engine()
            if not evolution_engine._is_running:
                raise ValueError("Evolution engine failed to start")

            evolution_engine.stop_engine()
            if evolution_engine._is_running:
                raise ValueError("Evolution engine failed to stop")

            self.results["components"]["schema_evolution"] = {
                "status": "passed",
                "snapshot_time": snapshot_time,
                "changes_detected": len(changes),
                "engine_startup": True
            }

            self.log(f"Schema Evolution validation successful ({snapshot_time:.3f}s)", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Schema Evolution validation failed: {e}", "ERROR")
            self.results["components"]["schema_evolution"] = {
                "status": "failed",
                "error": str(e)
            }
            if self.verbose:
                traceback.print_exc()
            return False

    def validate_integration(self) -> bool:
        """Validate integration between components."""
        self.log("Validating component integration...")

        try:
            # Test full workflow integration
            inspector = EnhancedDatabaseInspector(self.database_url)
            test_config = TestGenerationConfig(output_directory=str(self.output_dir))

            # Initialize all components
            test_generator = TestGenerator(test_config, inspector)
            monitor = SchemaMonitor(self.database_url, {"storage_path": str(self.output_dir / "monitor")})
            evolution_config = EvolutionConfig(output_directory=str(self.output_dir))
            evolution_engine = EvolutionEngine(self.database_url, evolution_config)

            # Test data flow
            tables = inspector.get_all_tables()
            if len(tables) == 0:
                raise ValueError("No tables found for integration test")

            # Test schema monitoring integration
            changes = monitor.force_check()

            # Test evolution engine integration
            evolution_engine.start_engine()

            try:
                # Force evolution with changes
                if changes:
                    task = evolution_engine.force_evolution(changes)
                    if task and task.task_id:
                        integration_success = True
                    else:
                        integration_success = False
                else:
                    # No changes is also valid
                    integration_success = True

            finally:
                evolution_engine.stop_engine()

            self.results["components"]["integration"] = {
                "status": "passed" if integration_success else "failed",
                "workflow_tested": True,
                "components_connected": 4
            }

            self.log("Component integration validation successful", "SUCCESS")
            return integration_success

        except Exception as e:
            self.log(f"Integration validation failed: {e}", "ERROR")
            self.results["components"]["integration"] = {
                "status": "failed",
                "error": str(e)
            }
            if self.verbose:
                traceback.print_exc()
            return False

    def run_performance_benchmarks(self) -> bool:
        """Run performance benchmarks."""
        self.log("Running performance benchmarks...")

        try:
            benchmarks = {}

            # Database Inspection Benchmark
            inspector = EnhancedDatabaseInspector(self.database_url)

            times = []
            for i in range(5):
                start = time.time()
                tables = inspector.get_all_tables()
                elapsed = time.time() - start
                times.append(elapsed)

            benchmarks["database_inspection"] = {
                "average_time": sum(times) / len(times),
                "min_time": min(times),
                "max_time": max(times),
                "tables_discovered": len(tables)
            }

            # Test Generation Benchmark
            config = TestGenerationConfig(output_directory=str(self.output_dir))
            test_generator = TestGenerator(config, inspector)

            users_table = next(table for table in tables if table.name == "validation_users")

            start = time.time()
            test_suite = test_generator.generate_complete_test_suite(users_table)
            generation_time = time.time() - start

            benchmarks["test_generation"] = {
                "generation_time": generation_time,
                "unit_tests_generated": bool(test_suite.unit_tests),
                "integration_tests_generated": bool(test_suite.integration_tests)
            }

            # Schema Monitoring Benchmark
            monitor = SchemaMonitor(self.database_url, {"storage_path": str(self.output_dir / "monitor")})

            times = []
            for i in range(3):
                start = time.time()
                snapshot = monitor._take_schema_snapshot()
                elapsed = time.time() - start
                times.append(elapsed)

            benchmarks["schema_monitoring"] = {
                "average_snapshot_time": sum(times) / len(times),
                "tables_in_snapshot": len(snapshot.tables) if snapshot else 0
            }

            self.results["performance"] = benchmarks

            # Check performance requirements
            performance_ok = (
                benchmarks["database_inspection"]["average_time"] < 1.0 and
                benchmarks["test_generation"]["generation_time"] < 5.0 and
                benchmarks["schema_monitoring"]["average_snapshot_time"] < 1.0
            )

            if performance_ok:
                self.log("Performance benchmarks passed", "SUCCESS")
            else:
                self.log("Performance benchmarks show some slowdowns", "WARN")

            return performance_ok

        except Exception as e:
            self.log(f"Performance benchmarks failed: {e}", "ERROR")
            self.results["performance"] = {"error": str(e)}
            return False

    def generate_report(self) -> str:
        """Generate validation report."""
        report_file = self.output_dir / "validation_report.json"

        # Calculate overall status
        component_statuses = [
            comp.get("status") == "passed"
            for comp in self.results["components"].values()
        ]

        if all(component_statuses):
            self.results["status"] = "passed"
        elif any(component_statuses):
            self.results["status"] = "partial"
        else:
            self.results["status"] = "failed"

        # Add summary
        self.results["summary"] = {
            "total_components": len(self.results["components"]),
            "passed_components": sum(1 for comp in self.results["components"].values()
                                   if comp.get("status") == "passed"),
            "failed_components": sum(1 for comp in self.results["components"].values()
                                   if comp.get("status") == "failed"),
            "validation_time": time.time() - self.results["timestamp"],
            "performance_ok": "error" not in self.results.get("performance", {})
        }

        # Write report
        with open(report_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)

        return str(report_file)

    def print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print("🧪 FLASK-APPBUILDER PHASE 1 VALIDATION SUMMARY")
        print("=" * 80)

        status_color = {
            "passed": "\033[92m",  # Green
            "partial": "\033[93m", # Yellow
            "failed": "\033[91m"   # Red
        }

        status = self.results["status"]
        color = status_color.get(status, "")
        print(f"Overall Status: {color}{status.upper()}\033[0m")

        print(f"\nComponents Tested: {self.results['summary']['total_components']}")
        print(f"✅ Passed: {self.results['summary']['passed_components']}")
        print(f"❌ Failed: {self.results['summary']['failed_components']}")

        print(f"\nValidation Time: {self.results['summary']['validation_time']:.2f} seconds")

        print("\nComponent Results:")
        for component, result in self.results["components"].items():
            status_icon = "✅" if result.get("status") == "passed" else "❌"
            component_name = component.replace("_", " ").title()
            print(f"  {status_icon} {component_name}")

            if result.get("status") == "failed" and result.get("error"):
                print(f"      Error: {result['error']}")

        if self.results.get("performance"):
            print("\nPerformance Metrics:")
            perf = self.results["performance"]

            if "database_inspection" in perf:
                avg_time = perf["database_inspection"]["average_time"]
                print(f"  📊 Database Inspection: {avg_time:.3f}s average")

            if "test_generation" in perf:
                gen_time = perf["test_generation"]["generation_time"]
                print(f"  🧪 Test Generation: {gen_time:.3f}s")

            if "schema_monitoring" in perf:
                snap_time = perf["schema_monitoring"]["average_snapshot_time"]
                print(f"  🔍 Schema Monitoring: {snap_time:.3f}s average")

        if self.results.get("warnings"):
            print(f"\nWarnings ({len(self.results['warnings'])}):")
            for warning in self.results["warnings"][:5]:
                print(f"  ⚠️  {warning}")

        print("\n" + "=" * 80)

        if status == "passed":
            print("🎉 Phase 1 validation completed successfully!")
            print("✅ Flask-AppBuilder Enhancement Phase 1 is ready for production use.")
        elif status == "partial":
            print("⚠️  Phase 1 validation completed with some issues.")
            print("📋 Review failed components before production deployment.")
        else:
            print("❌ Phase 1 validation failed.")
            print("🔧 Fix critical issues before proceeding to production.")

        print("=" * 80)

    def run_validation(self, skip_performance: bool = False) -> bool:
        """Run complete Phase 1 validation."""
        self.log("🚀 Starting Flask-AppBuilder Phase 1 Validation")

        validation_steps = [
            ("Creating test database", self.create_test_database),
            ("Validating imports", self.validate_imports),
            ("Validating Database Inspector", self.validate_database_inspector),
            ("Validating Testing Framework", self.validate_testing_framework),
            ("Validating Schema Evolution", self.validate_schema_evolution),
            ("Validating Integration", self.validate_integration),
        ]

        if not skip_performance:
            validation_steps.append(("Running performance benchmarks", self.run_performance_benchmarks))

        # Run validation steps
        for step_name, step_func in validation_steps:
            self.log(f"Step: {step_name}")

            try:
                success = step_func()
                if not success:
                    self.log(f"Validation step failed: {step_name}", "ERROR")
                    # Continue with other steps for complete assessment

            except Exception as e:
                self.log(f"Validation step crashed: {step_name} - {e}", "ERROR")
                self.results["errors"].append(f"{step_name}: {str(e)}")

        # Generate final report
        report_file = self.generate_report()
        self.log(f"Validation report saved to: {report_file}")

        # Print summary
        self.print_summary()

        return self.results["status"] == "passed"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Phase 1 Validation Script")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--skip-performance", action="store_true", help="Skip performance benchmarks")
    parser.add_argument("--output-dir", help="Output directory for test results")

    args = parser.parse_args()

    validator = Phase1Validator(
        verbose=args.verbose,
        output_dir=args.output_dir
    )

    try:
        success = validator.run_validation(skip_performance=args.skip_performance)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n⚠️  Validation interrupted by user")
        sys.exit(130)

    except Exception as e:
        print(f"\n💥 Validation crashed: {e}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()