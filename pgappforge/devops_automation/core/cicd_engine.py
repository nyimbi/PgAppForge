"""
CI/CD Pipeline Engine

Automated CI/CD pipeline generation and management for PgAppForge applications.
Supports GitHub Actions, GitLab CI, Jenkins, Azure DevOps, and CircleCI.
"""

import os
import json
import yaml
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class PipelineProvider(Enum):
    """Supported CI/CD providers"""
    GITHUB_ACTIONS = "github_actions"
    GITLAB_CI = "gitlab_ci"
    JENKINS = "jenkins"
    AZURE_DEVOPS = "azure_devops"
    CIRCLECI = "circleci"

class DeploymentStage(Enum):
    """Deployment stages"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

@dataclass
class PipelineConfig:
    """CI/CD Pipeline configuration"""
    provider: PipelineProvider
    app_name: str
    python_version: str = "3.11"
    node_version: Optional[str] = "18"
    enable_testing: bool = True
    enable_security_scan: bool = True
    enable_code_quality: bool = True
    enable_container_scan: bool = True
    enable_dependency_scan: bool = True
    deployment_stages: List[DeploymentStage] = field(default_factory=lambda: [
        DeploymentStage.DEVELOPMENT,
        DeploymentStage.STAGING,
        DeploymentStage.PRODUCTION
    ])
    container_registry: Optional[str] = None
    kubernetes_cluster: Optional[str] = None
    notification_channels: List[str] = field(default_factory=list)
    environment_variables: Dict[str, str] = field(default_factory=dict)
    secrets: List[str] = field(default_factory=list)
    artifact_retention: int = 30  # days
    
@dataclass
class TestConfig:
    """Test configuration for pipeline"""
    unit_tests: bool = True
    integration_tests: bool = True
    e2e_tests: bool = False
    coverage_threshold: float = 80.0
    test_command: str = "nose2 -c setup.cfg -F -v --with-coverage"
    test_results_path: str = "test-results"
    coverage_report_path: str = "coverage-reports"

@dataclass
class SecurityConfig:
    """Security scanning configuration"""
    sast_tools: List[str] = field(default_factory=lambda: ["bandit", "semgrep"])
    dependency_tools: List[str] = field(default_factory=lambda: ["safety", "pip-audit"])
    container_tools: List[str] = field(default_factory=lambda: ["trivy", "grype"])
    license_scan: bool = True
    vulnerability_threshold: str = "high"  # low, medium, high, critical

class CICDPipelineEngine:
    """
    CI/CD Pipeline Engine for automated pipeline generation and management.
    
    Generates optimized CI/CD pipelines for multiple providers with:
    - Multi-stage builds and deployments
    - Comprehensive testing and security scanning
    - Container registry integration
    - Kubernetes deployment automation
    - Notification and monitoring integration
    """
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.test_config = TestConfig()
        self.security_config = SecurityConfig()
        self.templates_path = Path(__file__).parent.parent / "templates" / "cicd"
        
    def generate_pipeline(self, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate CI/CD pipeline configuration files.
        
        Args:
            output_dir: Directory to save pipeline files (optional)
            
        Returns:
            Dictionary with pipeline files and their content
        """
        logger.info(f"Generating {self.config.provider.value} pipeline for {self.config.app_name}")
        
        if self.config.provider == PipelineProvider.GITHUB_ACTIONS:
            pipeline_content = self._generate_github_actions()
            filename = ".github/workflows/main.yml"
        elif self.config.provider == PipelineProvider.GITLAB_CI:
            pipeline_content = self._generate_gitlab_ci()
            filename = ".gitlab-ci.yml"
        elif self.config.provider == PipelineProvider.JENKINS:
            pipeline_content = self._generate_jenkins()
            filename = "Jenkinsfile"
        elif self.config.provider == PipelineProvider.AZURE_DEVOPS:
            pipeline_content = self._generate_azure_devops()
            filename = "azure-pipelines.yml"
        elif self.config.provider == PipelineProvider.CIRCLECI:
            pipeline_content = self._generate_circleci()
            filename = ".circleci/config.yml"
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")
        
        result = {
            "provider": self.config.provider.value,
            "filename": filename,
            "content": pipeline_content,
            "additional_files": self._generate_additional_files()
        }
        
        if output_dir:
            self._save_pipeline_files(result, output_dir)
            
        return result
    
    def _generate_github_actions(self) -> str:
        """Generate GitHub Actions workflow"""
        workflow = {
            "name": f"CI/CD Pipeline - {self.config.app_name}",
            "on": {
                "push": {
                    "branches": ["main", "develop", "feature/*"]
                },
                "pull_request": {
                    "branches": ["main", "develop"]
                }
            },
            "env": self.config.environment_variables,
            "jobs": {}
        }
        
        # Build and Test Job
        test_job = {
            "runs-on": "ubuntu-latest",
            "strategy": {
                "matrix": {
                    "python-version": [self.config.python_version]
                }
            },
            "steps": [
                {
                    "name": "Checkout code",
                    "uses": "actions/checkout@v4"
                },
                {
                    "name": "Set up Python",
                    "uses": "actions/setup-python@v4",
                    "with": {
                        "python-version": "${{ matrix.python-version }}"
                    }
                },
                {
                    "name": "Cache dependencies",
                    "uses": "actions/cache@v3",
                    "with": {
                        "path": "~/.cache/pip",
                        "key": "${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt') }}",
                        "restore-keys": "${{ runner.os }}-pip-"
                    }
                },
                {
                    "name": "Install dependencies",
                    "run": "pip install -r requirements/testing.txt"
                }
            ]
        }
        
        if self.config.enable_testing:
            test_job["steps"].extend([
                {
                    "name": "Run tests",
                    "run": self.test_config.test_command
                },
                {
                    "name": "Upload test results",
                    "uses": "actions/upload-artifact@v3",
                    "if": "always()",
                    "with": {
                        "name": "test-results",
                        "path": self.test_config.test_results_path
                    }
                },
                {
                    "name": "Upload coverage reports",
                    "uses": "codecov/codecov-action@v3",
                    "with": {
                        "file": f"{self.test_config.coverage_report_path}/coverage.xml"
                    }
                }
            ])
        
        if self.config.enable_code_quality:
            test_job["steps"].extend([
                {
                    "name": "Run flake8",
                    "run": "flake8 pgappforge"
                },
                {
                    "name": "Run black check",
                    "run": "black --check pgappforge"
                },
                {
                    "name": "Run mypy",
                    "run": "mypy pgappforge"
                }
            ])
        
        workflow["jobs"]["test"] = test_job
        
        # Security Scan Job
        if self.config.enable_security_scan:
            security_job = {
                "runs-on": "ubuntu-latest",
                "needs": ["test"],
                "steps": [
                    {
                        "name": "Checkout code",
                        "uses": "actions/checkout@v4"
                    }
                ]
            }
            
            for tool in self.security_config.sast_tools:
                if tool == "bandit":
                    security_job["steps"].append({
                        "name": "Run Bandit security scan",
                        "run": "bandit -r pgappforge -f json -o bandit-report.json"
                    })
                elif tool == "semgrep":
                    security_job["steps"].append({
                        "name": "Run Semgrep security scan",
                        "uses": "returntocorp/semgrep-action@v1",
                        "with": {
                            "config": "auto"
                        }
                    })
            
            for tool in self.security_config.dependency_tools:
                if tool == "safety":
                    security_job["steps"].append({
                        "name": "Run Safety check",
                        "run": "safety check --json --output safety-report.json"
                    })
            
            workflow["jobs"]["security"] = security_job
        
        # Build and Push Container Job
        if self.config.container_registry:
            build_job = {
                "runs-on": "ubuntu-latest",
                "needs": ["test"],
                "if": "github.event_name == 'push'",
                "steps": [
                    {
                        "name": "Checkout code",
                        "uses": "actions/checkout@v4"
                    },
                    {
                        "name": "Set up Docker Buildx",
                        "uses": "docker/setup-buildx-action@v3"
                    },
                    {
                        "name": "Login to Container Registry",
                        "uses": "docker/login-action@v3",
                        "with": {
                            "registry": self.config.container_registry,
                            "username": "${{ secrets.REGISTRY_USERNAME }}",
                            "password": "${{ secrets.REGISTRY_PASSWORD }}"
                        }
                    },
                    {
                        "name": "Build and push",
                        "uses": "docker/build-push-action@v5",
                        "with": {
                            "context": ".",
                            "push": True,
                            "tags": f"{self.config.container_registry}/{self.config.app_name}:${{{{ github.sha }}}}"
                        }
                    }
                ]
            }
            
            if self.config.enable_container_scan:
                build_job["steps"].append({
                    "name": "Run Trivy vulnerability scanner",
                    "uses": "aquasecurity/trivy-action@master",
                    "with": {
                        "image-ref": f"{self.config.container_registry}/{self.config.app_name}:${{{{ github.sha }}}}",
                        "format": "sarif",
                        "output": "trivy-results.sarif"
                    }
                })
            
            workflow["jobs"]["build"] = build_job
        
        # Deployment Jobs
        for stage in self.config.deployment_stages:
            deploy_job = {
                "runs-on": "ubuntu-latest",
                "needs": ["build"] if self.config.container_registry else ["test"],
                "environment": stage.value,
                "if": self._get_deployment_condition(stage),
                "steps": [
                    {
                        "name": "Checkout code",
                        "uses": "actions/checkout@v4"
                    }
                ]
            }
            
            if self.config.kubernetes_cluster:
                deploy_job["steps"].extend([
                    {
                        "name": "Set up kubectl",
                        "uses": "azure/setup-kubectl@v3"
                    },
                    {
                        "name": "Deploy to Kubernetes",
                        "run": f"kubectl apply -f k8s/{stage.value}/"
                    }
                ])
            
            workflow["jobs"][f"deploy-{stage.value}"] = deploy_job
        
        return yaml.dump(workflow, default_flow_style=False, sort_keys=False)
    
    def _generate_gitlab_ci(self) -> str:
        """Generate GitLab CI configuration"""
        config = {
            "stages": ["test", "security", "build", "deploy"],
            "variables": self.config.environment_variables,
            "image": f"python:{self.config.python_version}"
        }
        
        # Test stage
        config["test"] = {
            "stage": "test",
            "before_script": [
                "pip install -r requirements/testing.txt"
            ],
            "script": [
                self.test_config.test_command
            ],
            "artifacts": {
                "reports": {
                    "junit": "test-results.xml",
                    "coverage_report": {
                        "coverage_format": "cobertura",
                        "path": "coverage.xml"
                    }
                },
                "expire_in": f"{self.config.artifact_retention} days"
            }
        }
        
        if self.config.enable_code_quality:
            config["code_quality"] = {
                "stage": "test",
                "script": [
                    "flake8 pgappforge",
                    "black --check pgappforge",
                    "mypy pgappforge"
                ]
            }
        
        # Security stage
        if self.config.enable_security_scan:
            config["security_scan"] = {
                "stage": "security",
                "script": [
                    "bandit -r pgappforge -f json -o bandit-report.json",
                    "safety check --json --output safety-report.json"
                ],
                "artifacts": {
                    "reports": {
                        "sast": "bandit-report.json"
                    }
                }
            }
        
        # Build stage
        if self.config.container_registry:
            config["build_image"] = {
                "stage": "build",
                "image": "docker:latest",
                "services": ["docker:dind"],
                "before_script": [
                    f"docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD {self.config.container_registry}"
                ],
                "script": [
                    f"docker build -t {self.config.container_registry}/{self.config.app_name}:$CI_COMMIT_SHA .",
                    f"docker push {self.config.container_registry}/{self.config.app_name}:$CI_COMMIT_SHA"
                ],
                "only": ["main", "develop"]
            }
        
        # Deploy stages
        for stage in self.config.deployment_stages:
            config[f"deploy_{stage.value}"] = {
                "stage": "deploy",
                "environment": {
                    "name": stage.value
                },
                "script": [
                    f"kubectl apply -f k8s/{stage.value}/"
                ],
                "only": [self._get_gitlab_branch_for_stage(stage)]
            }
        
        return yaml.dump(config, default_flow_style=False)
    
    def _generate_jenkins(self) -> str:
        """Generate Jenkins pipeline (Groovy script)"""
        pipeline = f"""
pipeline {{
    agent any
    
    environment {{
        PYTHON_VERSION = '{self.config.python_version}'
        APP_NAME = '{self.config.app_name}'
"""
        
        for key, value in self.config.environment_variables.items():
            pipeline += f"        {key} = '{value}'\n"
        
        if self.config.container_registry:
            pipeline += f"        REGISTRY = '{self.config.container_registry}'\n"
        
        pipeline += """    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        
        stage('Setup') {
            steps {
                sh '''
                    python3 -m venv venv
                    . venv/bin/activate
                    pip install -r requirements/testing.txt
                '''
            }
        }
"""
        
        if self.config.enable_testing:
            pipeline += f"""        
        stage('Test') {{
            steps {{
                sh '''
                    . venv/bin/activate
                    {self.test_config.test_command}
                '''
            }}
            post {{
                always {{
                    publishTestResults testResultsPattern: '{self.test_config.test_results_path}/**/*.xml'
                    publishCoverage adapters: [
                        coberturaAdapter('{self.test_config.coverage_report_path}/coverage.xml')
                    ]
                }}
            }}
        }}
"""
        
        if self.config.enable_code_quality:
            pipeline += """
        stage('Code Quality') {
            parallel {
                stage('Lint') {
                    steps {
                        sh '''
                            . venv/bin/activate
                            flake8 pgappforge
                        '''
                    }
                }
                stage('Format Check') {
                    steps {
                        sh '''
                            . venv/bin/activate
                            black --check pgappforge
                        '''
                    }
                }
                stage('Type Check') {
                    steps {
                        sh '''
                            . venv/bin/activate
                            mypy pgappforge
                        '''
                    }
                }
            }
        }
"""
        
        if self.config.enable_security_scan:
            pipeline += """
        stage('Security Scan') {
            parallel {
                stage('SAST') {
                    steps {
                        sh '''
                            . venv/bin/activate
                            bandit -r pgappforge -f json -o bandit-report.json
                        '''
                    }
                }
                stage('Dependency Check') {
                    steps {
                        sh '''
                            . venv/bin/activate
                            safety check --json --output safety-report.json
                        '''
                    }
                }
            }
        }
"""
        
        if self.config.container_registry:
            pipeline += """
        stage('Build Image') {
            when {
                anyOf {
                    branch 'main'
                    branch 'develop'
                }
            }
            steps {
                script {
                    def image = docker.build("${REGISTRY}/${APP_NAME}:${BUILD_NUMBER}")
"""
            
            if self.config.enable_container_scan:
                pipeline += """
                    sh "trivy image --exit-code 0 --severity HIGH,CRITICAL ${REGISTRY}/${APP_NAME}:${BUILD_NUMBER}"
"""
            
            pipeline += """
                    docker.withRegistry("https://${REGISTRY}", 'registry-credentials') {
                        image.push()
                        image.push("latest")
                    }
                }
            }
        }
"""
        
        # Deploy stages
        for stage in self.config.deployment_stages:
            branch_condition = self._get_jenkins_branch_for_stage(stage)
            pipeline += f"""
        stage('Deploy {stage.value.title()}') {{
            when {{
                branch '{branch_condition}'
            }}
            environment {{
                KUBECONFIG = credentials('kubeconfig-{stage.value}')
            }}
            steps {{
                sh '''
                    kubectl apply -f k8s/{stage.value}/
                    kubectl rollout status deployment/{self.config.app_name} -n {stage.value}
                '''
            }}
        }}
"""
        
        pipeline += """
    }
    
    post {
        always {
            cleanWs()
        }
        success {"""
        
        for channel in self.config.notification_channels:
            if channel.startswith("slack:"):
                channel_name = channel.split(":")[1]
                pipeline += f"""
            slackSend channel: '#{channel_name}', 
                      color: 'good', 
                      message: "✅ Pipeline succeeded for ${{env.JOB_NAME}} - ${{env.BUILD_NUMBER}}"
"""
        
        pipeline += """
        }
        failure {"""
        
        for channel in self.config.notification_channels:
            if channel.startswith("slack:"):
                channel_name = channel.split(":")[1]
                pipeline += f"""
            slackSend channel: '#{channel_name}', 
                      color: 'danger', 
                      message: "❌ Pipeline failed for ${{env.JOB_NAME}} - ${{env.BUILD_NUMBER}}"
"""
        
        pipeline += """
        }
    }
}"""
        
        return pipeline
    
    def _generate_azure_devops(self) -> str:
        """Generate Azure DevOps pipeline"""
        pipeline = {
            "trigger": {
                "branches": {
                    "include": ["main", "develop", "feature/*"]
                }
            },
            "pr": {
                "branches": {
                    "include": ["main", "develop"]
                }
            },
            "variables": self.config.environment_variables,
            "stages": []
        }
        
        # Build and test stage
        test_stage = {
            "stage": "BuildAndTest",
            "displayName": "Build and Test",
            "jobs": [{
                "job": "Test",
                "displayName": "Run Tests",
                "pool": {
                    "vmImage": "ubuntu-latest"
                },
                "steps": [
                    {
                        "task": "UsePythonVersion@0",
                        "inputs": {
                            "versionSpec": self.config.python_version,
                            "addToPath": True
                        }
                    },
                    {
                        "script": "pip install -r requirements/testing.txt",
                        "displayName": "Install dependencies"
                    }
                ]
            }]
        }
        
        if self.config.enable_testing:
            test_stage["jobs"][0]["steps"].extend([
                {
                    "script": self.test_config.test_command,
                    "displayName": "Run tests"
                },
                {
                    "task": "PublishTestResults@2",
                    "inputs": {
                        "testResultsFiles": f"{self.test_config.test_results_path}/**/*.xml",
                        "testRunTitle": "Python Tests"
                    }
                },
                {
                    "task": "PublishCodeCoverageResults@1",
                    "inputs": {
                        "codeCoverageTool": "Cobertura",
                        "summaryFileLocation": f"{self.test_config.coverage_report_path}/coverage.xml"
                    }
                }
            ])
        
        pipeline["stages"].append(test_stage)
        
        # Security stage
        if self.config.enable_security_scan:
            security_stage = {
                "stage": "SecurityScan",
                "displayName": "Security Scan",
                "dependsOn": ["BuildAndTest"],
                "jobs": [{
                    "job": "Security",
                    "displayName": "Security Analysis",
                    "pool": {
                        "vmImage": "ubuntu-latest"
                    },
                    "steps": [
                        {
                            "script": "bandit -r pgappforge -f json -o bandit-report.json",
                            "displayName": "Run Bandit SAST"
                        },
                        {
                            "script": "safety check --json --output safety-report.json",
                            "displayName": "Run Safety check"
                        }
                    ]
                }]
            }
            pipeline["stages"].append(security_stage)
        
        return yaml.dump(pipeline, default_flow_style=False)
    
    def _generate_circleci(self) -> str:
        """Generate CircleCI configuration"""
        config = {
            "version": 2.1,
            "orbs": {
                "python": "circleci/python@2.1.1"
            },
            "workflows": {
                "test-and-deploy": {
                    "jobs": []
                }
            },
            "jobs": {}
        }
        
        # Test job
        test_job = {
            "docker": [
                {"image": f"cimg/python:{self.config.python_version}"}
            ],
            "steps": [
                "checkout",
                {
                    "python/install-packages": {
                        "pip-dependency-file": "requirements/testing.txt"
                    }
                }
            ]
        }
        
        if self.config.enable_testing:
            test_job["steps"].extend([
                {
                    "run": {
                        "name": "Run tests",
                        "command": self.test_config.test_command
                    }
                },
                {
                    "store_test_results": {
                        "path": self.test_config.test_results_path
                    }
                }
            ])
        
        config["jobs"]["test"] = test_job
        config["workflows"]["test-and-deploy"]["jobs"].append("test")
        
        # Build job
        if self.config.container_registry:
            build_job = {
                "docker": [
                    {"image": "cimg/base:current"}
                ],
                "steps": [
                    "checkout",
                    "setup_remote_docker",
                    {
                        "run": {
                            "name": "Build and push image",
                            "command": f"""
                                docker build -t {self.config.container_registry}/{self.config.app_name}:$CIRCLE_SHA1 .
                                echo $REGISTRY_PASSWORD | docker login -u $REGISTRY_USERNAME --password-stdin {self.config.container_registry}
                                docker push {self.config.container_registry}/{self.config.app_name}:$CIRCLE_SHA1
                            """
                        }
                    }
                ]
            }
            
            config["jobs"]["build"] = build_job
            config["workflows"]["test-and-deploy"]["jobs"].append({
                "build": {
                    "requires": ["test"],
                    "filters": {
                        "branches": {
                            "only": ["main", "develop"]
                        }
                    }
                }
            })
        
        return yaml.dump(config, default_flow_style=False)
    
    def _generate_additional_files(self) -> Dict[str, str]:
        """Generate additional configuration files"""
        files = {}
        
        # Docker compose for local development
        if self.config.container_registry:
            docker_compose = {
                "version": "3.8",
                "services": {
                    "app": {
                        "build": ".",
                        "ports": ["8080:8080"],
                        "environment": self.config.environment_variables,
                        "depends_on": ["db", "redis"]
                    },
                    "db": {
                        "image": "postgres:15",
                        "environment": {
                            "POSTGRES_DB": f"{self.config.app_name}_dev",
                            "POSTGRES_USER": "postgres",
                            "POSTGRES_PASSWORD": "postgres"
                        },
                        "volumes": ["postgres_data:/var/lib/postgresql/data"],
                        "ports": ["5432:5432"]
                    },
                    "redis": {
                        "image": "redis:7-alpine",
                        "ports": ["6379:6379"]
                    }
                },
                "volumes": {
                    "postgres_data": {}
                }
            }
            files["docker-compose.dev.yml"] = yaml.dump(docker_compose, default_flow_style=False)
        
        # Pre-commit configuration
        if self.config.enable_code_quality:
            precommit_config = {
                "repos": [
                    {
                        "repo": "https://github.com/pre-commit/pre-commit-hooks",
                        "rev": "v4.4.0",
                        "hooks": [
                            {"id": "trailing-whitespace"},
                            {"id": "end-of-file-fixer"},
                            {"id": "check-yaml"},
                            {"id": "check-added-large-files"}
                        ]
                    },
                    {
                        "repo": "https://github.com/psf/black",
                        "rev": "23.3.0",
                        "hooks": [{"id": "black"}]
                    },
                    {
                        "repo": "https://github.com/pycqa/flake8",
                        "rev": "6.0.0",
                        "hooks": [{"id": "flake8"}]
                    }
                ]
            }
            files[".pre-commit-config.yaml"] = yaml.dump(precommit_config, default_flow_style=False)
        
        # Dependabot configuration for GitHub
        if self.config.provider == PipelineProvider.GITHUB_ACTIONS:
            dependabot_config = {
                "version": 2,
                "updates": [
                    {
                        "package-ecosystem": "pip",
                        "directory": "/",
                        "schedule": {"interval": "weekly"},
                        "open-pull-requests-limit": 10
                    },
                    {
                        "package-ecosystem": "docker",
                        "directory": "/",
                        "schedule": {"interval": "weekly"}
                    },
                    {
                        "package-ecosystem": "github-actions",
                        "directory": "/",
                        "schedule": {"interval": "weekly"}
                    }
                ]
            }
            files[".github/dependabot.yml"] = yaml.dump(dependabot_config, default_flow_style=False)
        
        return files
    
    def _get_deployment_condition(self, stage: DeploymentStage) -> str:
        """Get deployment condition for GitHub Actions"""
        if stage == DeploymentStage.DEVELOPMENT:
            return "github.ref == 'refs/heads/develop'"
        elif stage == DeploymentStage.STAGING:
            return "github.ref == 'refs/heads/main'"
        elif stage == DeploymentStage.PRODUCTION:
            return "github.ref == 'refs/heads/main' && github.event_name == 'release'"
        return "false"
    
    def _get_gitlab_branch_for_stage(self, stage: DeploymentStage) -> str:
        """Get branch name for GitLab CI deployment stage"""
        if stage == DeploymentStage.DEVELOPMENT:
            return "develop"
        elif stage == DeploymentStage.STAGING:
            return "main"
        elif stage == DeploymentStage.PRODUCTION:
            return "main"
        return "main"
    
    def _get_jenkins_branch_for_stage(self, stage: DeploymentStage) -> str:
        """Get branch name for Jenkins deployment stage"""
        return self._get_gitlab_branch_for_stage(stage)
    
    def _save_pipeline_files(self, pipeline_result: Dict[str, Any], output_dir: str) -> None:
        """Save pipeline files to output directory"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save main pipeline file
        main_file_path = output_path / pipeline_result["filename"]
        main_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(main_file_path, 'w') as f:
            f.write(pipeline_result["content"])
        
        # Save additional files
        for filename, content in pipeline_result["additional_files"].items():
            file_path = output_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w') as f:
                f.write(content)
        
        logger.info(f"Pipeline files saved to {output_dir}")
    
    def validate_pipeline(self, pipeline_content: str) -> Dict[str, Any]:
        """
        Validate pipeline configuration.
        
        Args:
            pipeline_content: Pipeline configuration content
            
        Returns:
            Validation result with issues and recommendations
        """
        issues = []
        recommendations = []
        
        try:
            if self.config.provider in [PipelineProvider.GITHUB_ACTIONS, 
                                      PipelineProvider.GITLAB_CI,
                                      PipelineProvider.AZURE_DEVOPS,
                                      PipelineProvider.CIRCLECI]:
                config = yaml.safe_load(pipeline_content)
                
                # Check for required sections
                if self.config.provider == PipelineProvider.GITHUB_ACTIONS:
                    if "jobs" not in config:
                        issues.append("Missing 'jobs' section")
                    if "on" not in config:
                        issues.append("Missing 'on' (triggers) section")
                
                # Check for security best practices
                if "env" in config or "environment" in config:
                    env_vars = config.get("env", {}) or config.get("environment", {})
                    for key, value in env_vars.items():
                        if any(secret_keyword in key.lower() for secret_keyword in 
                              ["password", "token", "key", "secret"]):
                            if not str(value).startswith("${{"):
                                issues.append(f"Environment variable '{key}' appears to contain secrets")
                
                # Performance recommendations
                if self.config.provider == PipelineProvider.GITHUB_ACTIONS:
                    if "cache" not in str(config):
                        recommendations.append("Consider adding dependency caching for faster builds")
                    
                    # Check for parallel jobs
                    jobs = config.get("jobs", {})
                    if len(jobs) > 1 and not any("needs" in job for job in jobs.values()):
                        recommendations.append("Consider parallelizing independent jobs")
                
        except yaml.YAMLError as e:
            issues.append(f"YAML syntax error: {e}")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations,
            "security_score": self._calculate_security_score(pipeline_content),
            "performance_score": self._calculate_performance_score(pipeline_content)
        }
    
    def _calculate_security_score(self, pipeline_content: str) -> float:
        """Calculate security score (0-100) for pipeline"""
        score = 100.0
        
        # Check for hardcoded secrets
        if any(keyword in pipeline_content.lower() for keyword in 
               ["password:", "token:", "api_key:", "secret:"]):
            score -= 30
        
        # Check for security scanning
        if not self.config.enable_security_scan:
            score -= 20
        
        # Check for dependency scanning
        if not self.config.enable_dependency_scan:
            score -= 15
        
        # Check for container scanning
        if self.config.container_registry and not self.config.enable_container_scan:
            score -= 15
        
        # Check for branch protection
        if "pull_request" not in pipeline_content and "merge_request" not in pipeline_content:
            score -= 10
        
        # Check for approval requirements
        if "environment" not in pipeline_content:
            score -= 10
        
        return max(0, score)
    
    def _calculate_performance_score(self, pipeline_content: str) -> float:
        """Calculate performance score (0-100) for pipeline"""
        score = 100.0
        
        # Check for caching
        if "cache" not in pipeline_content.lower():
            score -= 20
        
        # Check for parallelization
        if "parallel" not in pipeline_content.lower() and "needs" not in pipeline_content.lower():
            score -= 15
        
        # Check for artifact management
        if "artifact" not in pipeline_content.lower():
            score -= 10
        
        # Check for optimized images
        if "alpine" not in pipeline_content.lower() and "slim" not in pipeline_content.lower():
            score -= 5
        
        return max(0, score)
    
    def generate_pipeline_documentation(self) -> str:
        """Generate documentation for the CI/CD pipeline"""
        doc = f"""
# CI/CD Pipeline Documentation

## Overview
This document describes the CI/CD pipeline configuration for **{self.config.app_name}**.

**Provider:** {self.config.provider.value}  
**Python Version:** {self.config.python_version}  

## Pipeline Stages

### 1. Build & Test
- Code checkout and dependency installation
- Unit and integration tests
- Code coverage reporting
- Code quality checks (linting, formatting, type checking)

### 2. Security Analysis
- Static Application Security Testing (SAST)
- Dependency vulnerability scanning
- License compliance checking

### 3. Container Build
- Multi-stage Docker image building
- Container vulnerability scanning
- Image optimization and cleanup

### 4. Deployment
"""
        
        for stage in self.config.deployment_stages:
            doc += f"- **{stage.value.title()}**: Automated deployment to {stage.value} environment\n"
        
        doc += f"""

## Configuration

### Environment Variables
"""
        
        for key, value in self.config.environment_variables.items():
            doc += f"- `{key}`: {value}\n"
        
        doc += f"""

### Secrets Required
"""
        
        for secret in self.config.secrets:
            doc += f"- `{secret}`\n"
        
        if self.config.container_registry:
            doc += f"""

### Container Registry
- **Registry:** {self.config.container_registry}
- **Image:** {self.config.container_registry}/{self.config.app_name}
"""
        
        doc += f"""

## Security Features
- SAST scanning with {', '.join(self.security_config.sast_tools)}
- Dependency scanning with {', '.join(self.security_config.dependency_tools)}
- Container scanning with {', '.join(self.security_config.container_tools)}
- Vulnerability threshold: {self.security_config.vulnerability_threshold}

## Notifications
"""
        
        for channel in self.config.notification_channels:
            doc += f"- {channel}\n"
        
        doc += f"""

## Artifact Retention
- Test results: {self.config.artifact_retention} days
- Coverage reports: {self.config.artifact_retention} days
- Security scan results: {self.config.artifact_retention} days

## Maintenance
- Dependencies are automatically updated via dependency management tools
- Pipeline runs on every push to main branches and pull requests
- Failed builds trigger notifications to configured channels
"""
        
        return doc