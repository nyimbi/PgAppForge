# CI/CD Setup and Best Practices

This guide covers setting up continuous integration and deployment pipelines for PgAppForge applications with comprehensive testing, security scanning, and automated deployment.

## Overview

A robust CI/CD pipeline for PgAppForge should include:
- Automated testing across multiple Python versions and databases
- Code quality checks and security scanning
- Documentation generation and deployment
- Automated deployment to staging and production environments
- Performance testing and monitoring

## GitHub Actions

### Basic CI Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

env:
  PYTHON_VERSION: '3.11'

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']
        database: ['sqlite', 'postgresql', 'mysql']
        exclude:
          - python-version: '3.9'
            database: 'mysql'  # Skip specific combinations if needed

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: test_db
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: root
          MYSQL_DATABASE: test_db
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=3
        ports:
          - 3306:3306

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Cache pip dependencies
      uses: actions/cache@v3
      with:
        path: ~/.cache/pip
        key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt') }}
        restore-keys: |
          ${{ runner.os }}-pip-

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y libpq-dev libmysqlclient-dev

    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e ".[mfa,export,analytics]"

    - name: Set up database environment
      run: |
        case "${{ matrix.database }}" in
          sqlite)
            echo "DATABASE_URL=sqlite:///test.db" >> $GITHUB_ENV
            ;;
          postgresql)
            echo "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test_db" >> $GITHUB_ENV
            ;;
          mysql)
            echo "DATABASE_URL=mysql://root:root@localhost:3306/test_db" >> $GITHUB_ENV
            ;;
        esac
        echo "REDIS_URL=redis://localhost:6379/0" >> $GITHUB_ENV

    - name: Run code quality checks
      run: |
        black --check pgappforge tests examples
        flake8 pgappforge tests examples
        mypy pgappforge

    - name: Run security checks
      run: |
        bandit -r pgappforge -f json -o bandit-report.json
        safety check --json --output safety-report.json

    - name: Run tests
      run: |
        pytest tests/ \
          --cov=pgappforge \
          --cov-report=xml \
          --cov-report=html \
          --junitxml=junit.xml \
          -v

    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        files: ./coverage.xml
        flags: unittests
        name: codecov-umbrella

    - name: Upload test results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: test-results-${{ matrix.python-version }}-${{ matrix.database }}
        path: |
          junit.xml
          htmlcov/
          bandit-report.json
          safety-report.json

  integration-tests:
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ env.PYTHON_VERSION }}

    - name: Install dependencies
      run: |
        pip install -e ".[mfa,export,analytics]"

    - name: Run integration tests
      run: |
        pytest tests/integration/ -v --slow

    - name: Run performance tests
      run: |
        pytest tests/performance/ -v --benchmark-only

  ai-service-tests:
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push'

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ env.PYTHON_VERSION }}

    - name: Install dependencies
      run: |
        pip install -e ".[mfa,export,analytics]"

    - name: Test AI services (mocked)
      env:
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY_TEST }}
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY_TEST }}
      run: |
        pytest tests/ai/ -v -m "not requires_api_key"

    - name: Test AI services (with API keys)
      if: github.ref == 'refs/heads/main'
      env:
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      run: |
        pytest tests/ai/ -v -m "requires_api_key" --api-test
```

### Advanced CI Features

```yaml
# .github/workflows/advanced-ci.yml
name: Advanced CI

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:  # Manual trigger

jobs:
  dependency-check:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Check for dependency updates
      run: |
        pip install pip-audit
        pip-audit --desc --format=json --output=audit-report.json

    - name: Check for outdated packages
      run: |
        pip list --outdated --format=json > outdated-packages.json

    - name: Upload dependency reports
      uses: actions/upload-artifact@v3
      with:
        name: dependency-reports
        path: |
          audit-report.json
          outdated-packages.json

  documentation:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        pip install -e ".[mfa,export,analytics]"
        pip install sphinx sphinx-rtd-theme

    - name: Build documentation
      run: |
        cd docs
        make html

    - name: Deploy documentation
      if: github.ref == 'refs/heads/main'
      uses: peaceiris/actions-gh-pages@v3
      with:
        github_token: ${{ secrets.GITHUB_TOKEN }}
        publish_dir: ./docs/_build/html

  docker-build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v2

    - name: Log in to Container Registry
      uses: docker/login-action@v2
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - name: Build and push Docker image
      uses: docker/build-push-action@v4
      with:
        context: .
        push: ${{ github.event_name != 'pull_request' }}
        tags: |
          ghcr.io/${{ github.repository }}:latest
          ghcr.io/${{ github.repository }}:${{ github.sha }}
        cache-from: type=gha
        cache-to: type=gha,mode=max
```

## GitLab CI

### Complete GitLab Pipeline

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - security
  - build
  - deploy

variables:
  PYTHON_VERSION: "3.11"
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
  paths:
    - .cache/pip
    - venv/

before_script:
  - python -V
  - pip install virtualenv
  - virtualenv venv
  - source venv/bin/activate
  - pip install --upgrade pip

# Linting and Code Quality
lint:
  stage: lint
  image: python:$PYTHON_VERSION
  script:
    - pip install black flake8 mypy
    - black --check pgappforge tests examples
    - flake8 pgappforge tests examples
    - mypy pgappforge
  only:
    - merge_requests
    - main
    - develop

# Testing
.test_template: &test_template
  stage: test
  image: python:$PYTHON_VERSION
  services:
    - name: postgres:15
      alias: postgres
      variables:
        POSTGRES_DB: test_db
        POSTGRES_USER: test
        POSTGRES_PASSWORD: test
    - name: redis:7-alpine
      alias: redis
  variables:
    DATABASE_URL: "postgresql://test:test@postgres:5432/test_db"
    REDIS_URL: "redis://redis:6379/0"
  before_script:
    - apt-get update -qq && apt-get install -y -qq libpq-dev
    - python -V
    - pip install --upgrade pip
    - pip install -e ".[mfa,export,analytics]"
  script:
    - pytest tests/ --cov=pgappforge --cov-report=xml --junitxml=junit.xml -v
  coverage: '/TOTAL.+?(\d+\%)$/'
  artifacts:
    reports:
      junit: junit.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - htmlcov/
    expire_in: 1 week

test:python39:
  <<: *test_template
  image: python:3.9

test:python310:
  <<: *test_template
  image: python:3.10

test:python311:
  <<: *test_template
  image: python:3.11

# Security Testing
security:
  stage: security
  image: python:$PYTHON_VERSION
  script:
    - pip install bandit safety
    - bandit -r pgappforge -f json -o bandit-report.json
    - safety check --json --output safety-report.json
  artifacts:
    reports:
      security:
        - bandit-report.json
    paths:
      - safety-report.json
    expire_in: 1 week
  only:
    - main
    - develop

# Container Security Scanning
container_scanning:
  stage: security
  image: docker:stable
  services:
    - docker:dind
  script:
    - docker build -t $CI_PROJECT_NAME .
    - docker run --rm -v /var/run/docker.sock:/var/run/docker.sock
      -v $PWD:/tmp/.cache/ aquasec/trivy image --exit-code 0 --no-progress
      --format table $CI_PROJECT_NAME
  only:
    - main

# Build
build:
  stage: build
  image: docker:stable
  services:
    - docker:dind
  variables:
    DOCKER_DRIVER: overlay2
    DOCKER_TLS_CERTDIR: "/certs"
  script:
    - docker login -u gitlab-ci-token -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - |
      if [ "$CI_COMMIT_BRANCH" == "main" ]; then
        docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:latest
        docker push $CI_REGISTRY_IMAGE:latest
      fi
  only:
    - main
    - develop

# Deployment
.deploy_template: &deploy_template
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache curl
  script:
    - echo "Deploying to $ENVIRONMENT"
    - curl -X POST "$DEPLOYMENT_WEBHOOK" -d "environment=$ENVIRONMENT&version=$CI_COMMIT_SHA"

deploy:staging:
  <<: *deploy_template
  variables:
    ENVIRONMENT: staging
  environment:
    name: staging
    url: https://staging.yourdomain.com
  only:
    - develop

deploy:production:
  <<: *deploy_template
  variables:
    ENVIRONMENT: production
  environment:
    name: production
    url: https://yourdomain.com
  when: manual
  only:
    - main
```

## Jenkins Pipeline

### Jenkinsfile

```groovy
// Jenkinsfile
pipeline {
    agent any

    environment {
        PYTHON_VERSION = '3.11'
        VENV_NAME = "venv-${BUILD_NUMBER}"
        DATABASE_URL = 'postgresql://test:test@localhost:5432/test_db'
        REDIS_URL = 'redis://localhost:6379/0'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Setup Environment') {
            steps {
                sh '''
                    python${PYTHON_VERSION} -m venv ${VENV_NAME}
                    . ${VENV_NAME}/bin/activate
                    pip install --upgrade pip
                    pip install -e ".[mfa,export,analytics]"
                '''
            }
        }

        stage('Code Quality') {
            parallel {
                stage('Linting') {
                    steps {
                        sh '''
                            . ${VENV_NAME}/bin/activate
                            black --check pgappforge tests examples
                            flake8 pgappforge tests examples
                        '''
                    }
                }
                stage('Type Checking') {
                    steps {
                        sh '''
                            . ${VENV_NAME}/bin/activate
                            mypy pgappforge
                        '''
                    }
                }
                stage('Security Scan') {
                    steps {
                        sh '''
                            . ${VENV_NAME}/bin/activate
                            bandit -r pgappforge -f json -o bandit-report.json
                            safety check --json --output safety-report.json
                        '''
                        archiveArtifacts artifacts: '*-report.json', fingerprint: true
                    }
                }
            }
        }

        stage('Testing') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        sh '''
                            . ${VENV_NAME}/bin/activate
                            pytest tests/unit/ --cov=pgappforge --cov-report=xml --junitxml=junit.xml -v
                        '''
                        publishTestResults testResultsPattern: 'junit.xml'
                        publishCoverage adapters: [coberturaAdapter('coverage.xml')], sourceFileResolver: sourceFiles('STORE_LAST_BUILD')
                    }
                }
                stage('Integration Tests') {
                    steps {
                        sh '''
                            . ${VENV_NAME}/bin/activate
                            pytest tests/integration/ -v
                        '''
                    }
                }
                stage('AI Service Tests') {
                    when {
                        anyOf {
                            branch 'main'
                            branch 'develop'
                        }
                    }
                    steps {
                        withCredentials([
                            string(credentialsId: 'openai-api-key', variable: 'OPENAI_API_KEY'),
                            string(credentialsId: 'anthropic-api-key', variable: 'ANTHROPIC_API_KEY')
                        ]) {
                            sh '''
                                . ${VENV_NAME}/bin/activate
                                pytest tests/ai/ -v -m "not requires_api_key"
                            '''
                        }
                    }
                }
            }
        }

        stage('Build Docker Image') {
            when {
                anyOf {
                    branch 'main'
                    branch 'develop'
                }
            }
            steps {
                script {
                    def image = docker.build("flask-appbuilder:${BUILD_NUMBER}")
                    docker.withRegistry('https://registry.yourdomain.com', 'docker-registry-credentials') {
                        image.push()
                        if (env.BRANCH_NAME == 'main') {
                            image.push('latest')
                        }
                    }
                }
            }
        }

        stage('Deploy to Staging') {
            when { branch 'develop' }
            steps {
                script {
                    build job: 'deploy-to-staging', parameters: [
                        string(name: 'IMAGE_TAG', value: "${BUILD_NUMBER}")
                    ]
                }
            }
        }

        stage('Deploy to Production') {
            when { branch 'main' }
            steps {
                input message: 'Deploy to Production?', ok: 'Deploy'
                script {
                    build job: 'deploy-to-production', parameters: [
                        string(name: 'IMAGE_TAG', value: "${BUILD_NUMBER}")
                    ]
                }
            }
        }
    }

    post {
        always {
            sh '''
                if [ -d "${VENV_NAME}" ]; then
                    rm -rf ${VENV_NAME}
                fi
            '''
            archiveArtifacts artifacts: 'htmlcov/**', allowEmptyArchive: true
            cleanWs()
        }
        failure {
            emailext (
                subject: "Build Failed: ${env.JOB_NAME} - ${env.BUILD_NUMBER}",
                body: "Build failed. Check console output at ${env.BUILD_URL}",
                to: "${env.CHANGE_AUTHOR_EMAIL}"
            )
        }
        success {
            script {
                if (env.BRANCH_NAME == 'main') {
                    slackSend (
                        color: 'good',
                        message: "✅ PgAppForge ${env.BUILD_NUMBER} deployed to production"
                    )
                }
            }
        }
    }
}
```

## Testing Strategies

### Test Configuration

```python
# tests/conftest.py
import pytest
import os
import tempfile
from flask import Flask
from pgappforge import AppBuilder, SQLA

@pytest.fixture(scope='session')
def test_config():
    """Test configuration."""
    return {
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'CACHE_TYPE': 'SimpleCache',
        'REDIS_URL': 'redis://localhost:6379/1',  # Different DB for tests
    }

@pytest.fixture(scope='session')
def app(test_config):
    """Create test application."""
    app = Flask(__name__)
    app.config.update(test_config)

    # Use separate test database
    if 'DATABASE_URL' in os.environ:
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    else:
        # Create temporary SQLite database
        db_fd, db_path = tempfile.mkstemp()
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)

    with app.app_context():
        db.create_all()
        # Create test data
        yield app
        db.drop_all()

    if 'db_fd' in locals():
        os.close(db_fd)
        os.unlink(db_path)

@pytest.fixture
def client(app):
    """Test client."""
    return app.test_client()

@pytest.fixture
def auth_client(client, app):
    """Authenticated test client."""
    with app.app_context():
        # Login as admin user
        response = client.post('/login/', data={
            'username': 'admin',
            'password': 'admin'
        })
        yield client
```

### Performance Testing

```python
# tests/performance/test_performance.py
import pytest
from time import time
from concurrent.futures import ThreadPoolExecutor, as_completed

class TestPerformance:
    """Performance tests for critical operations."""

    @pytest.mark.benchmark
    def test_database_query_performance(self, app):
        """Test database query performance."""
        with app.app_context():
            from pgappforge import appbuilder
            User = appbuilder.sm.user_model

            # Measure query time
            start_time = time()
            users = User.query.limit(100).all()
            query_time = time() - start_time

            assert query_time < 0.1  # Should complete within 100ms
            assert len(users) <= 100

    @pytest.mark.benchmark
    def test_ai_response_time(self, app):
        """Test AI service response time."""
        with app.app_context():
            from pgappforge.collaborative.ai.ai_models import AIModelManager

            manager = AIModelManager()
            start_time = time()

            try:
                response = manager.generate_text(
                    prompt="Hello",
                    max_tokens=10,
                    timeout=5
                )
                response_time = time() - start_time
                assert response_time < 5.0  # Should respond within 5 seconds
            except Exception:
                pytest.skip("AI service not available")

    @pytest.mark.benchmark
    def test_concurrent_requests(self, client):
        """Test concurrent request handling."""
        def make_request():
            response = client.get('/health')
            return response.status_code

        # Test with 10 concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [future.result() for future in as_completed(futures)]

        # All requests should succeed
        assert all(status == 200 for status in results)
```

### Integration Testing

```python
# tests/integration/test_ai_integration.py
import pytest
from unittest.mock import patch, MagicMock

class TestAIIntegration:
    """Integration tests for AI features."""

    @pytest.mark.integration
    def test_ai_content_generation_flow(self, auth_client, app):
        """Test complete AI content generation flow."""
        with app.app_context():
            # Test AI content generation endpoint
            response = auth_client.post('/ai/generate', json={
                'prompt': 'Generate a test content',
                'content_type': 'text',
                'max_tokens': 100
            })

            assert response.status_code == 200
            data = response.get_json()
            assert 'content' in data
            assert len(data['content']) > 0

    @pytest.mark.integration
    @pytest.mark.requires_api_key
    def test_real_ai_service_integration(self, app):
        """Test integration with real AI services."""
        with app.app_context():
            from pgappforge.collaborative.ai.ai_models import AIModelManager

            manager = AIModelManager()

            # Test with minimal prompt to avoid costs
            response = manager.generate_text(
                prompt="Hi",
                max_tokens=5,
                temperature=0.1
            )

            assert isinstance(response, str)
            assert len(response) > 0

    @pytest.mark.integration
    def test_collaborative_features(self, auth_client, app):
        """Test collaborative features integration."""
        with app.app_context():
            # Test WebSocket connection
            response = auth_client.get('/collaborate/connect')
            assert response.status_code == 200

            # Test real-time updates
            response = auth_client.post('/collaborate/update', json={
                'document_id': 'test-doc',
                'operation': 'insert',
                'data': 'test content'
            })
            assert response.status_code == 200
```

## Deployment Automation

### Ansible Playbook

```yaml
# deploy.yml
---
- name: Deploy PgAppForge Application
  hosts: webservers
  become: yes
  vars:
    app_name: flask-appbuilder
    app_user: "{{ app_name }}"
    app_dir: "/opt/{{ app_name }}"
    venv_dir: "{{ app_dir }}/venv"
    repo_url: "https://github.com/dpgaspar/PgAppForge.git"
    branch: "{{ deploy_branch | default('main') }}"

  tasks:
    - name: Create application user
      user:
        name: "{{ app_user }}"
        system: yes
        shell: /bin/bash
        home: "{{ app_dir }}"

    - name: Create application directory
      file:
        path: "{{ app_dir }}"
        state: directory
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0755'

    - name: Clone/update repository
      git:
        repo: "{{ repo_url }}"
        dest: "{{ app_dir }}/src"
        version: "{{ branch }}"
        force: yes
      become_user: "{{ app_user }}"
      notify: restart application

    - name: Create virtual environment
      python_virtualenv:
        virtualenv: "{{ venv_dir }}"
        virtualenv_python: python3.11
      become_user: "{{ app_user }}"

    - name: Install Python dependencies
      pip:
        requirements: "{{ app_dir }}/src/requirements/production.txt"
        virtualenv: "{{ venv_dir }}"
      become_user: "{{ app_user }}"
      notify: restart application

    - name: Install application
      pip:
        name: "{{ app_dir }}/src"
        virtualenv: "{{ venv_dir }}"
        editable: no
      become_user: "{{ app_user }}"
      notify: restart application

    - name: Copy configuration file
      template:
        src: config.py.j2
        dest: "{{ app_dir }}/config.py"
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0640'
      notify: restart application

    - name: Copy environment file
      template:
        src: .env.j2
        dest: "{{ app_dir }}/.env"
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0600'
      notify: restart application

    - name: Run database migrations
      shell: |
        source {{ venv_dir }}/bin/activate
        cd {{ app_dir }}/src
        flask db upgrade
      become_user: "{{ app_user }}"
      environment:
        FLASK_APP: app
        CONFIG_FILE: "{{ app_dir }}/config.py"

    - name: Copy systemd service file
      template:
        src: flask-appbuilder.service.j2
        dest: /etc/systemd/system/{{ app_name }}.service
      notify:
        - reload systemd
        - restart application

    - name: Enable and start application service
      systemd:
        name: "{{ app_name }}"
        enabled: yes
        state: started

  handlers:
    - name: reload systemd
      systemd:
        daemon_reload: yes

    - name: restart application
      systemd:
        name: "{{ app_name }}"
        state: restarted
```

### Terraform Infrastructure

```hcl
# infrastructure/main.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# VPC and Networking
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.project_name}-vpc"
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 1}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.project_name}-public-${count.index + 1}"
    Environment = var.environment
  }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name        = "${var.project_name}-private-${count.index + 1}"
    Environment = var.environment
  }
}

# Application Load Balancer
resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = var.environment == "production"

  tags = {
    Environment = var.environment
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Environment = var.environment
  }
}

# RDS Database
resource "aws_db_instance" "main" {
  identifier                = "${var.project_name}-db"
  engine                    = "postgres"
  engine_version            = "15.4"
  instance_class            = var.db_instance_class
  allocated_storage         = var.db_allocated_storage
  storage_encrypted         = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name

  backup_retention_period = var.environment == "production" ? 7 : 1
  backup_window          = "03:00-04:00"
  maintenance_window     = "sun:04:00-sun:05:00"

  skip_final_snapshot = var.environment != "production"
  deletion_protection = var.environment == "production"

  tags = {
    Environment = var.environment
  }
}

# ElastiCache Redis
resource "aws_elasticache_cluster" "main" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [aws_security_group.redis.id]

  tags = {
    Environment = var.environment
  }
}
```

## Monitoring and Alerting

### Prometheus Configuration

```yaml
# monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "pgappforge_rules.yml"

scrape_configs:
  - job_name: 'flask-appbuilder'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 10s

  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['localhost:9121']

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

### Alert Rules

```yaml
# monitoring/pgappforge_rules.yml
groups:
  - name: pgappforge
    rules:
      - alert: HighErrorRate
        expr: rate(flask_http_request_exceptions_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors per second"

      - alert: HighResponseTime
        expr: histogram_quantile(0.95, rate(flask_http_request_duration_seconds_bucket[5m])) > 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High response time detected"
          description: "95th percentile response time is {{ $value }} seconds"

      - alert: DatabaseConnectionFailed
        expr: up{job="postgres"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Database connection failed"
          description: "PostgreSQL database is down"

      - alert: RedisConnectionFailed
        expr: up{job="redis"} == 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Redis connection failed"
          description: "Redis cache is down"

      - alert: AIServiceTimeout
        expr: rate(ai_request_timeout_total[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "AI service timeout rate high"
          description: "AI service timeout rate is {{ $value }} per second"
```

This comprehensive CI/CD setup guide provides automated testing, security scanning, deployment pipelines, and monitoring for PgAppForge applications with enhanced AI and collaborative features.