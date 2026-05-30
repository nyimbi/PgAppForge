#!/usr/bin/env python3
"""
Comprehensive Test Runner for PgAppForge Mixins

Runs all mixin tests with detailed reporting, coverage analysis,
and performance benchmarking.

Usage:
    python tests/run_mixin_tests.py [options]
    
Options:
    --fast           Skip slow tests
    --security-only  Run only security tests
    --performance    Run performance benchmarks
    --coverage       Generate coverage report
    --verbose        Verbose output
"""

import sys
import os
import argparse
import subprocess
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class MixinTestRunner:
    """Comprehensive test runner for mixin tests."""
    
    def __init__(self):
        self.test_dir = Path(__file__).parent / "test_mixins"
        self.results = {}
        
    def run_security_tests(self, verbose=False):
        """Run security-focused tests."""
        print("🔐 Running Security Tests...")
        
        security_tests = [
            "test_security_framework.py",
            "test_integration_and_performance.py::TestSecurityIntegrationScenarios"
        ]
        
        cmd = ["python", "-m", "pytest"] + [str(self.test_dir / test) for test in security_tests]
        if verbose:
            cmd.extend(["-v", "-s"])
        cmd.extend(["-m", "security", "--tb=short"])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.results['security'] = result.returncode == 0
        
        print(f"Security Tests: {'✅ PASSED' if result.returncode == 0 else '❌ FAILED'}")
        if result.returncode != 0 and verbose:
            print(result.stdout)
            print(result.stderr)
        
        return result.returncode == 0
    
    def run_performance_tests(self, verbose=False):
        """Run performance tests."""
        print("⚡ Running Performance Tests...")
        
        performance_tests = [
            "test_integration_and_performance.py::TestPerformanceCharacteristics"
        ]
        
        cmd = ["python", "-m", "pytest"] + [str(self.test_dir / test) for test in performance_tests]
        if verbose:
            cmd.extend(["-v", "-s"])
        cmd.extend(["-m", "performance", "--tb=short"])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.results['performance'] = result.returncode == 0
        
        print(f"Performance Tests: {'✅ PASSED' if result.returncode == 0 else '❌ FAILED'}")
        if result.returncode != 0 and verbose:
            print(result.stdout)
            print(result.stderr)
        
        return result.returncode == 0
    
    def run_unit_tests(self, verbose=False, fast=False):
        """Run unit tests for all mixins."""
        print("🧪 Running Unit Tests...")
        
        unit_tests = [
            "test_enhanced_mixins.py",
            "test_specialized_mixins.py", 
            "test_security_framework.py"
        ]
        
        cmd = ["python", "-m", "pytest"] + [str(self.test_dir / test) for test in unit_tests]
        if verbose:
            cmd.extend(["-v", "-s"])
        if fast:
            cmd.extend(["-m", "not slow"])
        cmd.extend(["--tb=short"])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.results['unit'] = result.returncode == 0
        
        print(f"Unit Tests: {'✅ PASSED' if result.returncode == 0 else '❌ FAILED'}")
        if result.returncode != 0 and verbose:
            print(result.stdout)
            print(result.stderr)
        
        return result.returncode == 0
    
    def run_integration_tests(self, verbose=False):
        """Run integration tests."""
        print("🔗 Running Integration Tests...")
        
        integration_tests = [
            "test_integration_and_performance.py::TestMixinIntegration"
        ]
        
        cmd = ["python", "-m", "pytest"] + [str(self.test_dir / test) for test in integration_tests]
        if verbose:
            cmd.extend(["-v", "-s"])
        cmd.extend(["-m", "integration", "--tb=short"])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.results['integration'] = result.returncode == 0
        
        print(f"Integration Tests: {'✅ PASSED' if result.returncode == 0 else '❌ FAILED'}")
        if result.returncode != 0 and verbose:
            print(result.stdout)
            print(result.stderr)
        
        return result.returncode == 0
    
    def run_coverage_analysis(self, verbose=False):
        """Run tests with coverage analysis."""
        print("📊 Running Coverage Analysis...")
        
        try:
            # Install coverage if not available
            subprocess.run([sys.executable, "-m", "pip", "install", "coverage", "pytest-cov"], 
                         check=False, capture_output=True)
            
            # Run tests with coverage
            cmd = [
                "python", "-m", "pytest",
                str(self.test_dir),
                f"--cov={project_root}/pgappforge/mixins",
                "--cov-report=html",
                "--cov-report=term",
                "--cov-fail-under=80"
            ]
            
            if verbose:
                cmd.extend(["-v"])
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.results['coverage'] = result.returncode == 0
            
            print(f"Coverage Analysis: {'✅ PASSED' if result.returncode == 0 else '❌ FAILED'}")
            if verbose:
                print(result.stdout)
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"Coverage analysis failed: {e}")
            return False
    
    def run_all_tests(self, fast=False, verbose=False, coverage=False):
        """Run all test suites."""
        print("🚀 Running Comprehensive Mixin Test Suite")
        print("=" * 50)
        
        start_time = time.time()
        all_passed = True
        
        # Run test suites
        test_suites = [
            ("Unit Tests", lambda: self.run_unit_tests(verbose, fast)),
            ("Integration Tests", lambda: self.run_integration_tests(verbose)),
            ("Security Tests", lambda: self.run_security_tests(verbose)),
            ("Performance Tests", lambda: self.run_performance_tests(verbose))
        ]
        
        for suite_name, test_func in test_suites:
            try:
                suite_passed = test_func()
                all_passed = all_passed and suite_passed
            except Exception as e:
                print(f"❌ {suite_name} failed with error: {e}")
                all_passed = False
        
        # Run coverage if requested
        if coverage:
            try:
                self.run_coverage_analysis(verbose)
            except Exception as e:
                print(f"Coverage analysis error: {e}")
        
        # Summary
        end_time = time.time()
        duration = end_time - start_time
        
        print("\n" + "=" * 50)
        print("📋 TEST SUMMARY")
        print("=" * 50)
        
        for test_type, passed in self.results.items():
            status = "✅ PASSED" if passed else "❌ FAILED"
            print(f"{test_type.capitalize():15} : {status}")
        
        print(f"\nTotal Duration: {duration:.2f} seconds")
        print(f"Overall Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
        
        return all_passed
    
    def validate_test_environment(self):
        """Validate test environment setup."""
        print("🔍 Validating Test Environment...")
        
        required_modules = [
            'pytest',
            'flask',
            'pgappforge',
            'sqlalchemy',
            'cryptography',
            'requests'
        ]
        
        missing_modules = []
        for module in required_modules:
            try:
                __import__(module.replace('-', '_'))
            except ImportError:
                missing_modules.append(module)
        
        if missing_modules:
            print(f"❌ Missing required modules: {', '.join(missing_modules)}")
            print("Install with: pip install " + " ".join(missing_modules))
            return False
        
        # Check test files exist
        test_files = [
            "test_security_framework.py",
            "test_enhanced_mixins.py", 
            "test_specialized_mixins.py",
            "test_integration_and_performance.py",
            "conftest.py"
        ]
        
        missing_files = []
        for test_file in test_files:
            if not (self.test_dir / test_file).exists():
                missing_files.append(test_file)
        
        if missing_files:
            print(f"❌ Missing test files: {', '.join(missing_files)}")
            return False
        
        print("✅ Test environment validated")
        return True


def main():
    """Main test runner entry point."""
    parser = argparse.ArgumentParser(description="Run PgAppForge Mixin Tests")
    parser.add_argument("--fast", action="store_true", help="Skip slow tests")
    parser.add_argument("--security-only", action="store_true", help="Run only security tests")
    parser.add_argument("--performance", action="store_true", help="Run performance benchmarks")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--validate", action="store_true", help="Only validate test environment")
    
    args = parser.parse_args()
    
    runner = MixinTestRunner()
    
    # Validate environment
    if not runner.validate_test_environment():
        sys.exit(1)
    
    if args.validate:
        print("✅ Test environment validation complete")
        sys.exit(0)
    
    # Run specific test suites
    success = True
    
    if args.security_only:
        success = runner.run_security_tests(args.verbose)
    elif args.performance:
        success = runner.run_performance_tests(args.verbose)
    else:
        # Run all tests
        success = runner.run_all_tests(
            fast=args.fast,
            verbose=args.verbose, 
            coverage=args.coverage
        )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()