#!/usr/bin/env python3
"""
Comprehensive test runner for PgForge tutorial tests.

This script runs all tutorial tests, generates reports, and validates
that the tutorial examples work correctly without runtime errors.
"""

import os
import sys
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import unittest
import subprocess

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Add tests directory to path
tests_dir = Path(__file__).parent
sys.path.insert(0, str(tests_dir))

try:
    from test_config import TutorialTestSuite, TutorialTestConfig, TestEnvironmentManager
    from fixtures.tutorial_test_data import TutorialTestMetrics
except ImportError as e:
    print(f"❌ Failed to import test modules: {e}")
    print("Please ensure you're running from the tests directory")
    sys.exit(1)


class TutorialTestRunner:
    """Comprehensive test runner for tutorial validation."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / 'test_results'
        self.output_dir.mkdir(exist_ok=True)
        self.start_time = None
        self.results = {}

    def run_all_tests(self, verbosity: int = 2) -> Dict[str, Any]:
        """Run all tutorial tests and return comprehensive results."""
        print("🚀 Starting Comprehensive Tutorial Test Suite")
        print("=" * 60)

        self.start_time = time.time()
        test_results = {
            'start_time': datetime.now().isoformat(),
            'test_categories': {},
            'overall_summary': {},
            'performance_metrics': {},
            'environment_info': self._get_environment_info()
        }

        try:
            # Run basic functionality tests
            print("\n📋 Running Basic Functionality Tests...")
            basic_results = self._run_test_category('basic', 'test_tutorial_getting_started.py', verbosity)
            test_results['test_categories']['basic'] = basic_results

            # Run integration tests
            print("\n🔗 Running Integration Tests...")
            integration_results = self._run_test_category('integration', 'test_tutorial_integration.py', verbosity)
            test_results['test_categories']['integration'] = integration_results

            # Run performance tests
            print("\n⚡ Running Performance Tests...")
            performance_results = self._run_performance_tests(verbosity)
            test_results['test_categories']['performance'] = performance_results

            # Run configuration tests
            print("\n⚙️ Running Configuration Tests...")
            config_results = self._run_configuration_tests(verbosity)
            test_results['test_categories']['configuration'] = config_results

            # Generate overall summary
            test_results['overall_summary'] = self._generate_overall_summary(test_results['test_categories'])
            test_results['end_time'] = datetime.now().isoformat()
            test_results['total_duration'] = time.time() - self.start_time

            # Generate reports
            self._generate_reports(test_results)

            return test_results

        except Exception as e:
            print(f"❌ Critical error during test execution: {e}")
            test_results['critical_error'] = str(e)
            test_results['end_time'] = datetime.now().isoformat()
            return test_results

    def _run_test_category(self, category: str, test_file: str, verbosity: int) -> Dict[str, Any]:
        """Run a specific category of tests."""
        try:
            # Discover and run tests
            loader = unittest.TestLoader()
            suite = loader.discover(
                str(tests_dir),
                pattern=test_file,
                top_level_dir=str(project_root)
            )

            # Run tests with custom result collector
            runner = unittest.TextTestRunner(
                verbosity=verbosity,
                stream=sys.stdout,
                buffer=True
            )

            start_time = time.time()
            result = runner.run(suite)
            duration = time.time() - start_time

            return {
                'category': category,
                'duration': duration,
                'tests_run': result.testsRun,
                'failures': len(result.failures),
                'errors': len(result.errors),
                'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
                'success_rate': self._calculate_success_rate(result),
                'failure_details': [self._format_test_failure(f) for f in result.failures],
                'error_details': [self._format_test_error(e) for e in result.errors],
                'status': 'PASSED' if result.wasSuccessful() else 'FAILED'
            }

        except Exception as e:
            return {
                'category': category,
                'error': str(e),
                'status': 'ERROR'
            }

    def _run_performance_tests(self, verbosity: int) -> Dict[str, Any]:
        """Run performance-specific tests."""
        try:
            # Run performance tests from integration file
            loader = unittest.TestLoader()
            suite = unittest.TestSuite()

            # Load specific performance test classes
            from test_tutorial_integration import TutorialPerformanceTest
            performance_suite = loader.loadTestsFromTestCase(TutorialPerformanceTest)
            suite.addTest(performance_suite)

            runner = unittest.TextTestRunner(verbosity=verbosity, buffer=True)
            start_time = time.time()
            result = runner.run(suite)
            duration = time.time() - start_time

            return {
                'category': 'performance',
                'duration': duration,
                'tests_run': result.testsRun,
                'failures': len(result.failures),
                'errors': len(result.errors),
                'success_rate': self._calculate_success_rate(result),
                'performance_thresholds': {
                    'max_app_startup': TutorialTestConfig.MAX_APP_STARTUP_TIME,
                    'max_db_operation': TutorialTestConfig.MAX_DATABASE_OPERATION_TIME,
                    'max_view_render': TutorialTestConfig.MAX_VIEW_RENDER_TIME
                },
                'status': 'PASSED' if result.wasSuccessful() else 'FAILED'
            }

        except Exception as e:
            return {
                'category': 'performance',
                'error': str(e),
                'status': 'ERROR'
            }

    def _run_configuration_tests(self, verbosity: int) -> Dict[str, Any]:
        """Run configuration and environment tests."""
        results = {
            'category': 'configuration',
            'test_environments': {},
            'status': 'PASSED'
        }

        # Test different configurations
        config_tests = [
            ('base', 'Base configuration'),
            ('ai_disabled', 'AI services disabled'),
            ('redis_disabled', 'Redis disabled')
        ]

        for config_name, description in config_tests:
            print(f"  Testing {description}...")
            try:
                with TestEnvironmentManager(config_name) as config:
                    # Simple validation test
                    test_result = self._validate_configuration(config)
                    results['test_environments'][config_name] = {
                        'description': description,
                        'status': 'PASSED' if test_result else 'FAILED',
                        'config': config_name
                    }
            except Exception as e:
                results['test_environments'][config_name] = {
                    'description': description,
                    'status': 'ERROR',
                    'error': str(e)
                }
                results['status'] = 'FAILED'

        return results

    def _validate_configuration(self, config: Dict[str, Any]) -> bool:
        """Validate a specific configuration."""
        try:
            # Add tutorial path
            tutorial_path = project_root / 'examples' / 'tutorial_getting_started'
            if str(tutorial_path) not in sys.path:
                sys.path.insert(0, str(tutorial_path))

            # Try to import and create app
            import app
            flask_app = app.create_app()

            # Basic validation
            return flask_app is not None and hasattr(flask_app, 'appbuilder')

        except Exception:
            return False

    def _calculate_success_rate(self, result: unittest.TestResult) -> float:
        """Calculate test success rate."""
        if result.testsRun == 0:
            return 0.0
        successful = result.testsRun - len(result.failures) - len(result.errors)
        return (successful / result.testsRun) * 100

    def _format_test_failure(self, failure: tuple) -> Dict[str, str]:
        """Format test failure information."""
        test_case, traceback = failure
        return {
            'test': str(test_case),
            'traceback': traceback,
            'class': test_case.__class__.__name__,
            'method': test_case._testMethodName
        }

    def _format_test_error(self, error: tuple) -> Dict[str, str]:
        """Format test error information."""
        test_case, traceback = error
        return {
            'test': str(test_case),
            'traceback': traceback,
            'class': test_case.__class__.__name__,
            'method': test_case._testMethodName
        }

    def _generate_overall_summary(self, categories: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall test summary."""
        total_tests = sum(cat.get('tests_run', 0) for cat in categories.values())
        total_failures = sum(cat.get('failures', 0) for cat in categories.values())
        total_errors = sum(cat.get('errors', 0) for cat in categories.values())

        successful_categories = sum(1 for cat in categories.values() if cat.get('status') == 'PASSED')
        total_categories = len(categories)

        return {
            'total_tests': total_tests,
            'total_failures': total_failures,
            'total_errors': total_errors,
            'overall_success_rate': ((total_tests - total_failures - total_errors) / total_tests * 100) if total_tests > 0 else 0,
            'categories_passed': successful_categories,
            'total_categories': total_categories,
            'category_success_rate': (successful_categories / total_categories * 100) if total_categories > 0 else 0,
            'overall_status': 'PASSED' if successful_categories == total_categories and total_failures == 0 and total_errors == 0 else 'FAILED'
        }

    def _get_environment_info(self) -> Dict[str, Any]:
        """Get environment information."""
        import platform
        return {
            'python_version': sys.version,
            'platform': platform.platform(),
            'working_directory': str(Path.cwd()),
            'test_runner_version': '1.0.0',
            'project_root': str(project_root)
        }

    def _generate_reports(self, results: Dict[str, Any]):
        """Generate test reports in multiple formats."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # JSON report
        json_file = self.output_dir / f'tutorial_test_results_{timestamp}.json'
        with open(json_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        # HTML report
        html_file = self.output_dir / f'tutorial_test_report_{timestamp}.html'
        self._generate_html_report(results, html_file)

        # Console summary
        self._print_console_summary(results)

        print(f"\n📊 Reports generated:")
        print(f"  JSON: {json_file}")
        print(f"  HTML: {html_file}")

    def _generate_html_report(self, results: Dict[str, Any], html_file: Path):
        """Generate HTML test report."""
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PgForge Tutorial Test Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .header {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .metric {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .metric h3 {{ margin: 0 0 10px 0; color: #333; }}
        .metric .value {{ font-size: 24px; font-weight: bold; }}
        .passed {{ color: #28a745; }}
        .failed {{ color: #dc3545; }}
        .category {{ margin-bottom: 30px; padding: 20px; background: #f8f9fa; border-radius: 8px; }}
        .details {{ margin-top: 15px; }}
        .error {{ background: #f8d7da; padding: 10px; border-radius: 4px; margin: 5px 0; }}
        .failure {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 5px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>PgForge Tutorial Test Report</h1>
        <p>Generated: {results.get('start_time', 'Unknown')}</p>
        <p>Duration: {results.get('total_duration', 0):.2f} seconds</p>
    </div>

    <div class="summary">
        <div class="metric">
            <h3>Overall Status</h3>
            <div class="value {'passed' if results.get('overall_summary', {}).get('overall_status') == 'PASSED' else 'failed'}">
                {results.get('overall_summary', {}).get('overall_status', 'UNKNOWN')}
            </div>
        </div>
        <div class="metric">
            <h3>Total Tests</h3>
            <div class="value">{results.get('overall_summary', {}).get('total_tests', 0)}</div>
        </div>
        <div class="metric">
            <h3>Success Rate</h3>
            <div class="value">{results.get('overall_summary', {}).get('overall_success_rate', 0):.1f}%</div>
        </div>
        <div class="metric">
            <h3>Categories Passed</h3>
            <div class="value">
                {results.get('overall_summary', {}).get('categories_passed', 0)}/{results.get('overall_summary', {}).get('total_categories', 0)}
            </div>
        </div>
    </div>

    <h2>Test Categories</h2>
"""

        # Add category details
        for category, details in results.get('test_categories', {}).items():
            status_class = 'passed' if details.get('status') == 'PASSED' else 'failed'
            html_content += f"""
    <div class="category">
        <h3 class="{status_class}">{category.title()} Tests - {details.get('status', 'UNKNOWN')}</h3>
        <p>Duration: {details.get('duration', 0):.2f}s | Tests: {details.get('tests_run', 0)} |
           Failures: {details.get('failures', 0)} | Errors: {details.get('errors', 0)}</p>

        <div class="details">
"""

            # Add failures
            if details.get('failure_details'):
                html_content += "<h4>Failures:</h4>"
                for failure in details.get('failure_details', []):
                    html_content += f'<div class="failure"><strong>{failure.get("test", "Unknown")}</strong><br><pre>{failure.get("traceback", "")}</pre></div>'

            # Add errors
            if details.get('error_details'):
                html_content += "<h4>Errors:</h4>"
                for error in details.get('error_details', []):
                    html_content += f'<div class="error"><strong>{error.get("test", "Unknown")}</strong><br><pre>{error.get("traceback", "")}</pre></div>'

            html_content += "</div></div>"

        html_content += """
</body>
</html>"""

        with open(html_file, 'w') as f:
            f.write(html_content)

    def _print_console_summary(self, results: Dict[str, Any]):
        """Print console summary of test results."""
        print("\n" + "="*60)
        print("📊 TUTORIAL TEST RESULTS SUMMARY")
        print("="*60)

        overall = results.get('overall_summary', {})
        status = overall.get('overall_status', 'UNKNOWN')
        status_icon = "✅" if status == 'PASSED' else "❌"

        print(f"\n{status_icon} Overall Status: {status}")
        print(f"🔢 Total Tests: {overall.get('total_tests', 0)}")
        print(f"📈 Success Rate: {overall.get('overall_success_rate', 0):.1f}%")
        print(f"⏱️  Total Duration: {results.get('total_duration', 0):.2f} seconds")

        print(f"\n📋 Category Results:")
        for category, details in results.get('test_categories', {}).items():
            status = details.get('status', 'UNKNOWN')
            icon = "✅" if status == 'PASSED' else "❌"
            print(f"  {icon} {category.title()}: {status} ({details.get('tests_run', 0)} tests)")

        # Show critical issues
        failures = overall.get('total_failures', 0)
        errors = overall.get('total_errors', 0)

        if failures > 0 or errors > 0:
            print(f"\n⚠️  Issues Found:")
            if failures > 0:
                print(f"  📛 Failures: {failures}")
            if errors > 0:
                print(f"  🚨 Errors: {errors}")

        print("="*60)


def main():
    """Main function for test runner."""
    parser = argparse.ArgumentParser(description='Run PgForge tutorial tests')
    parser.add_argument('--output-dir', '-o', help='Output directory for test reports')
    parser.add_argument('--verbosity', '-v', type=int, default=2, help='Test verbosity level (0-2)')
    parser.add_argument('--category', '-c', help='Run specific test category only')
    parser.add_argument('--performance-only', action='store_true', help='Run only performance tests')
    parser.add_argument('--quick', action='store_true', help='Run quick validation tests only')

    args = parser.parse_args()

    # Create test runner
    runner = TutorialTestRunner(args.output_dir)

    try:
        if args.quick:
            print("🏃 Running Quick Validation Tests...")
            # Run just basic functionality tests
            from test_config import run_tutorial_validation
            success = run_tutorial_validation()
            print(f"\n{'✅ Quick validation PASSED' if success else '❌ Quick validation FAILED'}")
            return 0 if success else 1

        elif args.performance_only:
            print("⚡ Running Performance Tests Only...")
            results = runner._run_performance_tests(args.verbosity)
            print(f"\n{'✅ Performance tests PASSED' if results.get('status') == 'PASSED' else '❌ Performance tests FAILED'}")
            return 0 if results.get('status') == 'PASSED' else 1

        else:
            # Run comprehensive test suite
            results = runner.run_all_tests(args.verbosity)
            overall_status = results.get('overall_summary', {}).get('overall_status', 'FAILED')
            return 0 if overall_status == 'PASSED' else 1

    except KeyboardInterrupt:
        print("\n🛑 Test execution interrupted by user")
        return 130
    except Exception as e:
        print(f"💥 Critical error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())