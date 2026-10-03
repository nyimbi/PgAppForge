# Flask-AppBuilder Quality Gates Makefile

.PHONY: help quality-check quality-strict syntax lint tests docs security pipeline quick fix clean install-dev ci-simulation pre-commit-install production-check

# Default target
help:
	@echo "Flask-AppBuilder Quality Gates"
	@echo "================================"
	@echo ""
	@echo "Available targets:"
	@echo "  quality-check   Run all quality gates (permissive mode)"
	@echo "  quality-strict  Run all quality gates (strict mode)"
	@echo "  syntax          Check syntax errors only"
	@echo "  lint            compileall + flake8 (same as CI)"
	@echo ""
	@echo "  tests needs PostgreSQL; override the target with PGAF_TEST_DATABASE_URI"
	@echo "  tests          Run test suite only"
	@echo "  docs           Check documentation coverage"
	@echo "  security       Run security scans"
	@echo "  pipeline       Run comprehensive quality pipeline"
	@echo "  install-dev    Install development dependencies"
	@echo "  clean          Clean up generated files"
	@echo ""
	@echo "Environment variables:"
	@echo "  STRICT_MODE=true       Enable strict validation (default: false)"
	@echo "  MIN_COVERAGE=60        Minimum documentation coverage (default: 60)"
	@echo "  GENERATE_REPORT=true   Generate quality reports (default: true)"

# Install development dependencies
install-dev:
	@echo "📦 Installing development dependencies..."
	pip install -e .
	pip install pytest pytest-cov pytest-mock bandit safety pre-commit
	pip install black isort flake8
	@echo "✅ Development dependencies installed"

# Run quality check in permissive mode
quality-check:
	@echo "🚀 Running Flask-AppBuilder Quality Check (Permissive Mode)"
	@STRICT_MODE=false ./scripts/validate-quality.sh

# Run quality check in strict mode
quality-strict:
	@echo "🚀 Running Flask-AppBuilder Quality Check (Strict Mode)"
	@STRICT_MODE=true ./scripts/validate-quality.sh

# Syntax validation only
syntax:
	@echo "🔍 Checking syntax errors..."
	@python -m compileall -q pgappforge
	@echo "✅ Syntax validation complete"

# Lint gate — mirrors .github/workflows/ci.yml lint job
lint:
	@echo "🔍 Running lint..."
	@python -m compileall -q pgappforge
	@python -m flake8 pgappforge tests
	@echo "✅ Lint complete"

# Run test suite only. Needs a reachable PostgreSQL; set PGAF_TEST_DATABASE_URI.
tests:
	@echo "🧪 Running test suite..."
	@python -m pytest tests/ci -q

# Check documentation coverage
docs:
	@echo "📚 Checking documentation coverage..."
	@python -c "\
	import sys; \
	sys.path.append('tests/ci'); \
	from test_documentation_validation import DocumentationValidator; \
	v = DocumentationValidator('pgappforge'); \
	r = v.analyze_directory(['__pycache__', '.git', 'tests', 'examples']); \
	c = r['summary']['documentation_coverage_percentage']; \
	print(f'📊 Documentation Coverage: {c:.1f}%'); \
	print(f'📁 Files analyzed: {r[\"summary\"][\"total_files_analyzed\"]}'); \
	print(f'⚠️ Files with issues: {r[\"summary\"][\"files_with_issues\"]}'); \
	"

# Run security scans
security:
	@echo "🔒 Running security scans..."
	@if command -v bandit >/dev/null 2>&1; then \
		echo "🔍 Running Bandit security scan..."; \
		bandit -r pgappforge -f txt || echo "⚠️ Security issues found"; \
	else \
		echo "⚠️ Bandit not installed - run 'pip install bandit'"; \
	fi
	@if command -v safety >/dev/null 2>&1; then \
		echo "🔍 Running Safety dependency check..."; \
		safety check || echo "⚠️ Vulnerable dependencies found"; \
	else \
		echo "⚠️ Safety not installed - run 'pip install safety'"; \
	fi

# Run comprehensive quality pipeline
pipeline:
	@echo "🔧 Running comprehensive quality pipeline..."
	@python tests/validation/quality_validation_pipeline.py pgappforge

# Run quick validation (essential checks only)
quick:
	@echo "⚡ Running quick validation..."
	@python tests/validation/fix_syntax_errors.py pgappforge --analyze-only
	@python -m pytest tests/ci/test_integration_workflows.py::TestUserRegistrationWorkflow::test_user_creation_workflow -v --tb=short

# Fix common issues automatically
fix:
	@echo "🔧 Fixing common issues..."
	@if command -v black >/dev/null 2>&1; then \
		echo "🎨 Formatting code with Black..."; \
		black pgappforge --line-length=100; \
	fi
	@if command -v isort >/dev/null 2>&1; then \
		echo "📦 Organizing imports with isort..."; \
		isort pgappforge --profile=black; \
	fi
	@echo "✅ Automated fixes complete"

# Clean up generated files
clean:
	@echo "🧹 Cleaning up generated files..."
	@rm -f quality_validation_report_*.json
	@rm -f bandit-report.json safety-report.json
	@rm -f test-results.xml
	@rm -rf .pytest_cache
	@rm -rf __pycache__
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

# Pre-commit setup
pre-commit-install:
	@echo "🪝 Installing pre-commit hooks..."
	@if command -v pre-commit >/dev/null 2>&1; then \
		pre-commit install; \
		echo "✅ Pre-commit hooks installed"; \
	else \
		echo "⚠️ pre-commit not installed - run 'pip install pre-commit'"; \
	fi

# CI/CD simulation
ci-simulation:
	@echo "🤖 Simulating CI/CD pipeline..."
	@echo "Step 1: Syntax validation"
	@make syntax
	@echo ""
	@echo "Step 2: Test execution"
	@make tests
	@echo ""
	@echo "Step 3: Documentation check"
	@make docs
	@echo ""
	@echo "Step 4: Security scan"
	@make security
	@echo ""
	@echo "Step 5: Quality pipeline"
	@make pipeline
	@echo ""
	@echo "✅ CI/CD simulation complete"

# Production readiness check
production-check:
	@echo "🚀 Production Readiness Assessment"
	@echo "=================================="
	@STRICT_MODE=true GENERATE_REPORT=true ./scripts/validate-quality.sh
	@echo ""
	@echo "📋 Production Readiness Checklist:"
	@echo "  ✓ All syntax errors fixed"
	@echo "  ✓ Critical tests passing"
	@echo "  ✓ Documentation coverage ≥60%"
	@echo "  ✓ Security vulnerabilities addressed"
	@echo "  ✓ Quality pipeline passes"
	@echo ""
	@echo "🎉 If all checks pass, Flask-AppBuilder is production ready!"