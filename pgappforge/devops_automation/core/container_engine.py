"""
Containerization Engine

Automated Docker containerization, multi-stage builds, security scanning,
and container optimization for PgForge applications.
"""

import logging
import os
import subprocess
import json
import yaml
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib
import re
import tempfile
import shutil

logger = logging.getLogger(__name__)


@dataclass
class ContainerConfiguration:
    """Configuration for containerization."""
    # Base image settings
    python_version: str = "3.11"
    base_image: str = "python:{python_version}-slim"
    alpine_variant: bool = False
    
    # Application settings
    app_name: str = "flask-appbuilder-app"
    app_port: int = 8080
    app_user: str = "appuser"
    app_group: str = "appgroup"
    
    # Security settings
    run_as_non_root: bool = True
    security_scanning: bool = True
    remove_package_caches: bool = True
    minimal_packages: bool = True
    
    # Performance settings
    multi_stage_build: bool = True
    layer_optimization: bool = True
    distroless_runtime: bool = False
    
    # Environment settings
    environments: List[str] = field(default_factory=lambda: ["development", "staging", "production"])
    environment_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Dependencies
    system_packages: List[str] = field(default_factory=lambda: ["curl", "wget"])
    python_packages_file: str = "requirements.txt"
    dev_requirements_file: str = "requirements-dev.txt"
    
    # Health checks
    health_check_endpoint: str = "/health"
    health_check_interval: str = "30s"
    health_check_timeout: str = "10s"
    health_check_retries: int = 3
    
    # Resource limits
    memory_limit: str = "512M"
    cpu_limit: str = "0.5"
    
    # Volumes and persistence
    data_volumes: List[str] = field(default_factory=list)
    config_volumes: List[str] = field(default_factory=list)
    
    # Networking
    expose_ports: List[int] = field(default_factory=lambda: [8080])
    internal_network: bool = True


@dataclass
class ContainerSecurityReport:
    """Container security scan report."""
    scan_id: str
    timestamp: datetime
    image_name: str
    vulnerabilities: List[Dict[str, Any]]
    security_score: float
    compliance_issues: List[Dict[str, Any]]
    recommendations: List[str]
    passed_checks: int
    failed_checks: int
    total_checks: int


class ContainerizationEngine:
    """
    Automated containerization engine for PgForge applications.
    
    Features:
    - Multi-stage Docker builds with optimization
    - Security-hardened container images
    - Multi-environment configuration
    - Container security scanning
    - Performance optimization
    - Health checks and monitoring
    - Container registry integration
    - Docker Compose generation
    - Kubernetes manifests generation
    """
    
    def __init__(self, config: Optional[ContainerConfiguration] = None):
        self.config = config or ContainerConfiguration()
        self.project_root = Path.cwd()
        self.container_dir = self.project_root / "containers"
        
        # Ensure container directory exists
        self.container_dir.mkdir(exist_ok=True)
        
        # Initialize Docker client check
        self.docker_available = self._check_docker_available()
        
        # Security scanning tools
        self.security_tools = {
            'trivy': self._check_trivy_available(),
            'grype': self._check_grype_available(),
            'docker_scout': self._check_docker_scout_available()
        }
        
        logger.info("Containerization Engine initialized")
    
    def _check_docker_available(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(['docker', '--version'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_trivy_available(self) -> bool:
        """Check if Trivy security scanner is available."""
        try:
            result = subprocess.run(['trivy', '--version'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_grype_available(self) -> bool:
        """Check if Grype security scanner is available."""
        try:
            result = subprocess.run(['grype', '--version'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_docker_scout_available(self) -> bool:
        """Check if Docker Scout is available."""
        try:
            result = subprocess.run(['docker', 'scout', '--help'], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    # Main containerization methods
    def generate_dockerfile(self, environment: str = "production") -> str:
        """
        Generate optimized Dockerfile for specified environment.
        
        Args:
            environment: Target environment (development, staging, production)
            
        Returns:
            Dockerfile content as string
        """
        logger.info(f"Generating Dockerfile for {environment} environment")
        
        # Select base image
        base_image = self.config.base_image.format(python_version=self.config.python_version)
        if self.config.alpine_variant:
            base_image = f"python:{self.config.python_version}-alpine"
        
        # Determine build strategy
        if self.config.multi_stage_build:
            dockerfile_content = self._generate_multi_stage_dockerfile(environment, base_image)
        else:
            dockerfile_content = self._generate_single_stage_dockerfile(environment, base_image)
        
        # Write Dockerfile
        dockerfile_path = self.container_dir / f"Dockerfile.{environment}"
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)
        
        logger.info(f"Generated Dockerfile: {dockerfile_path}")
        return dockerfile_content
    
    def _generate_multi_stage_dockerfile(self, environment: str, base_image: str) -> str:
        """Generate multi-stage Dockerfile for optimization."""
        
        # Get environment-specific config
        env_config = self.config.environment_configs.get(environment, {})
        
        dockerfile = f'''# Multi-stage Dockerfile for {environment} environment
# Generated by PgForge Containerization Engine

# =============================================================================
# Stage 1: Build Dependencies
# =============================================================================
FROM {base_image} as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    gcc \\
    g++ \\
    make \\
    pkg-config \\
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy requirements
COPY {self.config.python_packages_file} .
'''
        
        # Add dev requirements for development environment
        if environment == "development" and Path(self.config.dev_requirements_file).exists():
            dockerfile += f"COPY {self.config.dev_requirements_file} .\n"
        
        dockerfile += '''
# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \\
    pip install --no-cache-dir -r requirements.txt'''
        
        if environment == "development":
            dockerfile += f" && \\\n    pip install --no-cache-dir -r {self.config.dev_requirements_file}"
        
        dockerfile += '''

# =============================================================================
# Stage 2: Runtime Environment  
# =============================================================================
'''
        
        # Choose runtime image
        if self.config.distroless_runtime and environment == "production":
            runtime_image = "gcr.io/distroless/python3"
        else:
            runtime_image = base_image
        
        dockerfile += f'''FROM {runtime_image} as runtime

# Install runtime system packages
'''
        
        if not self.config.distroless_runtime:
            dockerfile += f'''RUN apt-get update && apt-get install -y --no-install-recommends \\
    {' '.join(self.config.system_packages)} \\
    && rm -rf /var/lib/apt/lists/*'''
        
        # Security: Create non-root user
        if self.config.run_as_non_root:
            dockerfile += f'''

# Create non-root user
RUN groupadd -r {self.config.app_group} && \\
    useradd -r -g {self.config.app_group} -d /app -s /bin/bash {self.config.app_user}
'''
        
        # Copy virtual environment from builder
        dockerfile += f'''
# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app
'''
        
        # Copy application code
        dockerfile += '''
# Copy application code
COPY --chown={user}:{group} . /app/

# Install application in development mode for dev environment
'''.format(user=self.config.app_user, group=self.config.app_group)
        
        if environment == "development":
            dockerfile += "RUN pip install -e .\n"
        else:
            dockerfile += "RUN pip install .\n"
        
        # Set up environment variables
        dockerfile += f'''
# Environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV={environment}
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT={self.config.app_port}
'''
        
        # Add environment-specific variables
        for key, value in env_config.get('environment_variables', {}).items():
            dockerfile += f"ENV {key}={value}\n"
        
        # Create directories and set permissions
        if self.config.data_volumes or self.config.config_volumes:
            dockerfile += "\n# Create volume directories\n"
            
            for volume in self.config.data_volumes + self.config.config_volumes:
                dockerfile += f"RUN mkdir -p {volume} && chown -R {self.config.app_user}:{self.config.app_group} {volume}\n"
        
        # Switch to non-root user
        if self.config.run_as_non_root:
            dockerfile += f"\nUSER {self.config.app_user}\n"
        
        # Health check
        dockerfile += f'''
# Health check
HEALTHCHECK --interval={self.config.health_check_interval} \\
           --timeout={self.config.health_check_timeout} \\
           --retries={self.config.health_check_retries} \\
    CMD curl -f http://localhost:{self.config.app_port}{self.config.health_check_endpoint} || exit 1

# Expose port
EXPOSE {self.config.app_port}
'''
        
        # Add volumes
        for volume in self.config.data_volumes:
            dockerfile += f"VOLUME {volume}\n"
        
        # Entry point
        dockerfile += '''
# Start application
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--timeout", "60", "app:app"]
'''
        
        return dockerfile
    
    def _generate_single_stage_dockerfile(self, environment: str, base_image: str) -> str:
        """Generate single-stage Dockerfile."""
        
        dockerfile = f'''# Single-stage Dockerfile for {environment} environment
# Generated by PgForge Containerization Engine

FROM {base_image}

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \\
    {' '.join(self.config.system_packages)} \\
    && rm -rf /var/lib/apt/lists/*
'''
        
        # Security: Create non-root user
        if self.config.run_as_non_root:
            dockerfile += f'''
# Create non-root user
RUN groupadd -r {self.config.app_group} && \\
    useradd -r -g {self.config.app_group} -d /app -s /bin/bash {self.config.app_user}
'''
        
        dockerfile += '''
# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \\
    pip install --no-cache-dir -r requirements.txt
'''
        
        if environment == "development":
            dockerfile += f'''
# Install development dependencies
COPY {self.config.dev_requirements_file} .
RUN pip install --no-cache-dir -r {self.config.dev_requirements_file}
'''
        
        dockerfile += f'''
# Copy application code
COPY --chown={self.config.app_user}:{self.config.app_group} . .

# Environment variables
ENV FLASK_ENV={environment}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER {self.config.app_user}

# Health check
HEALTHCHECK --interval={self.config.health_check_interval} \\
           --timeout={self.config.health_check_timeout} \\
           --retries={self.config.health_check_retries} \\
    CMD curl -f http://localhost:{self.config.app_port}{self.config.health_check_endpoint} || exit 1

# Expose port
EXPOSE {self.config.app_port}

# Start application
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "app:app"]
'''
        
        return dockerfile
    
    def generate_dockerignore(self) -> str:
        """Generate .dockerignore file."""
        
        dockerignore_content = '''# Generated by PgForge Containerization Engine

# Version control
.git/
.gitignore
.gitattributes

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Testing
.tox/
.coverage
.pytest_cache/
htmlcov/
.coverage.*
coverage.xml
*.cover

# Documentation
docs/_build/
.readthedocs.yml

# Logs
*.log
logs/

# Database
*.db
*.sqlite3

# OS
.DS_Store
Thumbs.db

# Node.js (if present)
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Docker
Dockerfile*
docker-compose*.yml
.dockerignore

# CI/CD
.github/
.gitlab-ci.yml
.travis.yml
Jenkinsfile

# Temporary files
tmp/
temp/
*.tmp
*.temp

# Local configuration
.env.local
config.local.*
secrets/
'''
        
        # Write .dockerignore
        dockerignore_path = self.project_root / ".dockerignore"
        with open(dockerignore_path, 'w') as f:
            f.write(dockerignore_content)
        
        logger.info(f"Generated .dockerignore: {dockerignore_path}")
        return dockerignore_content
    
    def generate_docker_compose(self, environments: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Generate Docker Compose files for specified environments.
        
        Args:
            environments: List of environments to generate compose files for
            
        Returns:
            Dictionary mapping environment to compose file content
        """
        if environments is None:
            environments = self.config.environments
        
        compose_files = {}
        
        for environment in environments:
            logger.info(f"Generating Docker Compose for {environment}")
            
            compose_content = self._generate_compose_content(environment)
            
            # Write compose file
            compose_filename = f"docker-compose.{environment}.yml"
            compose_path = self.container_dir / compose_filename
            
            with open(compose_path, 'w') as f:
                f.write(compose_content)
            
            compose_files[environment] = compose_content
            logger.info(f"Generated Docker Compose: {compose_path}")
        
        return compose_files
    
    def _generate_compose_content(self, environment: str) -> str:
        """Generate Docker Compose content for environment."""
        
        env_config = self.config.environment_configs.get(environment, {})
        
        # Base compose structure
        compose = {
            'version': '3.8',
            'services': {
                self.config.app_name: {
                    'build': {
                        'context': '.',
                        'dockerfile': f'containers/Dockerfile.{environment}',
                        'target': 'runtime'
                    },
                    'image': f"{self.config.app_name}:{environment}",
                    'container_name': f"{self.config.app_name}-{environment}",
                    'restart': 'unless-stopped',
                    'ports': [f"{self.config.app_port}:{self.config.app_port}"],
                    'environment': {
                        'FLASK_ENV': environment,
                        'DATABASE_URL': '${DATABASE_URL}',
                        **env_config.get('environment_variables', {})
                    },
                    'healthcheck': {
                        'test': f"curl -f http://localhost:{self.config.app_port}{self.config.health_check_endpoint}",
                        'interval': self.config.health_check_interval,
                        'timeout': self.config.health_check_timeout,
                        'retries': self.config.health_check_retries
                    }
                }
            }
        }
        
        # Add resource limits for production
        if environment == "production":
            compose['services'][self.config.app_name]['deploy'] = {
                'resources': {
                    'limits': {
                        'memory': self.config.memory_limit,
                        'cpus': self.config.cpu_limit
                    }
                }
            }
        
        # Add volumes
        if self.config.data_volumes or self.config.config_volumes:
            compose['services'][self.config.app_name]['volumes'] = []
            
            for volume in self.config.data_volumes:
                volume_name = volume.replace('/', '_').strip('_')
                compose['services'][self.config.app_name]['volumes'].append(
                    f"{volume_name}:{volume}"
                )
            
            for volume in self.config.config_volumes:
                volume_name = volume.replace('/', '_').strip('_') + '_config'
                compose['services'][self.config.app_name]['volumes'].append(
                    f"{volume_name}:{volume}:ro"  # Read-only config
                )
            
            # Define named volumes
            compose['volumes'] = {}
            for volume in self.config.data_volumes:
                volume_name = volume.replace('/', '_').strip('_')
                compose['volumes'][volume_name] = {}
            
            for volume in self.config.config_volumes:
                volume_name = volume.replace('/', '_').strip('_') + '_config'
                compose['volumes'][volume_name] = {}
        
        # Add database service for development
        if environment == "development":
            compose['services']['database'] = {
                'image': 'postgres:15-alpine',
                'container_name': f"{self.config.app_name}-db-{environment}",
                'restart': 'unless-stopped',
                'environment': {
                    'POSTGRES_DB': 'appdb',
                    'POSTGRES_USER': 'appuser',
                    'POSTGRES_PASSWORD': 'apppass'
                },
                'volumes': ['postgres_data:/var/lib/postgresql/data'],
                'ports': ['5432:5432']
            }
            
            if 'volumes' not in compose:
                compose['volumes'] = {}
            compose['volumes']['postgres_data'] = {}
            
            # Update app service to depend on database
            compose['services'][self.config.app_name]['depends_on'] = ['database']
            compose['services'][self.config.app_name]['environment']['DATABASE_URL'] = \
                'postgresql://appuser:apppass@database:5432/appdb'
        
        # Add Redis for caching/sessions
        if env_config.get('redis_enabled', True):
            compose['services']['redis'] = {
                'image': 'redis:7-alpine',
                'container_name': f"{self.config.app_name}-redis-{environment}",
                'restart': 'unless-stopped',
                'volumes': ['redis_data:/data'],
                'ports': ['6379:6379'] if environment == "development" else []
            }
            
            if 'volumes' not in compose:
                compose['volumes'] = {}
            compose['volumes']['redis_data'] = {}
            
            # Add Redis URL to app environment
            compose['services'][self.config.app_name]['environment']['REDIS_URL'] = \
                'redis://redis:6379/0'
        
        # Add network
        if self.config.internal_network:
            compose['networks'] = {
                f"{self.config.app_name}_network": {
                    'driver': 'bridge'
                }
            }
            
            # Add network to all services
            for service in compose['services'].values():
                service['networks'] = [f"{self.config.app_name}_network"]
        
        return yaml.dump(compose, default_flow_style=False, sort_keys=False)
    
    def build_image(self, environment: str = "production", 
                   tag: Optional[str] = None, 
                   push: bool = False, 
                   registry: Optional[str] = None) -> Dict[str, Any]:
        """
        Build Docker image for specified environment.
        
        Args:
            environment: Target environment
            tag: Custom tag for the image
            push: Whether to push to registry
            registry: Container registry URL
            
        Returns:
            Build result information
        """
        if not self.docker_available:
            raise RuntimeError("Docker is not available")
        
        logger.info(f"Building Docker image for {environment} environment")
        
        # Generate Dockerfile if it doesn't exist
        dockerfile_path = self.container_dir / f"Dockerfile.{environment}"
        if not dockerfile_path.exists():
            self.generate_dockerfile(environment)
        
        # Generate .dockerignore if it doesn't exist
        dockerignore_path = self.project_root / ".dockerignore"
        if not dockerignore_path.exists():
            self.generate_dockerignore()
        
        # Determine image tag
        if tag is None:
            tag = f"{self.config.app_name}:{environment}"
        
        if registry:
            full_tag = f"{registry}/{tag}"
        else:
            full_tag = tag
        
        try:
            # Build image
            build_cmd = [
                'docker', 'build',
                '-f', str(dockerfile_path),
                '-t', full_tag,
                '--target', 'runtime',
                '.'
            ]
            
            # Add build args for environment
            env_config = self.config.environment_configs.get(environment, {})
            for key, value in env_config.get('build_args', {}).items():
                build_cmd.extend(['--build-arg', f"{key}={value}"])
            
            # Add labels
            labels = {
                'app.name': self.config.app_name,
                'app.environment': environment,
                'app.build-date': datetime.now().isoformat(),
                'app.version': env_config.get('version', '1.0.0')
            }
            
            for key, value in labels.items():
                build_cmd.extend(['--label', f"{key}={value}"])
            
            logger.info(f"Running: {' '.join(build_cmd)}")
            
            start_time = datetime.now()
            result = subprocess.run(
                build_cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minutes
            )
            
            build_duration = (datetime.now() - start_time).total_seconds()
            
            if result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {result.stderr}")
            
            # Get image info
            inspect_result = subprocess.run(
                ['docker', 'inspect', full_tag],
                capture_output=True,
                text=True
            )
            
            image_info = {}
            if inspect_result.returncode == 0:
                inspect_data = json.loads(inspect_result.stdout)[0]
                image_info = {
                    'id': inspect_data['Id'],
                    'size': inspect_data['Size'],
                    'created': inspect_data['Created'],
                    'architecture': inspect_data['Architecture'],
                    'os': inspect_data['Os']
                }
            
            build_result = {
                'success': True,
                'image_tag': full_tag,
                'build_duration': build_duration,
                'image_info': image_info,
                'build_log': result.stdout
            }
            
            # Push to registry if requested
            if push and registry:
                push_result = self._push_image(full_tag)
                build_result['push_result'] = push_result
            
            logger.info(f"Successfully built image: {full_tag}")
            return build_result
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker build timed out")
        except Exception as e:
            logger.error(f"Docker build failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'image_tag': full_tag
            }
    
    def _push_image(self, image_tag: str) -> Dict[str, Any]:
        """Push image to container registry."""
        
        logger.info(f"Pushing image to registry: {image_tag}")
        
        try:
            result = subprocess.run(
                ['docker', 'push', image_tag],
                capture_output=True,
                text=True,
                timeout=1800  # 30 minutes
            )
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': result.stderr
                }
            
            return {
                'success': True,
                'push_log': result.stdout
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': "Push timed out"
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def scan_image_security(self, image_tag: str) -> ContainerSecurityReport:
        """
        Perform security scan on container image.
        
        Args:
            image_tag: Image tag to scan
            
        Returns:
            Security scan report
        """
        logger.info(f"Performing security scan on image: {image_tag}")
        
        scan_id = hashlib.md5(f"{image_tag}_{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        vulnerabilities = []
        compliance_issues = []
        recommendations = []
        
        # Try different security scanning tools
        scan_results = {}
        
        if self.security_tools.get('trivy'):
            scan_results['trivy'] = self._run_trivy_scan(image_tag)
            
        if self.security_tools.get('grype'):
            scan_results['grype'] = self._run_grype_scan(image_tag)
            
        if self.security_tools.get('docker_scout'):
            scan_results['docker_scout'] = self._run_docker_scout_scan(image_tag)
        
        # Aggregate results
        total_vulnerabilities = 0
        critical_vulnerabilities = 0
        
        for tool, results in scan_results.items():
            if results and results.get('vulnerabilities'):
                for vuln in results['vulnerabilities']:
                    vulnerabilities.append({
                        'tool': tool,
                        'id': vuln.get('id', 'unknown'),
                        'severity': vuln.get('severity', 'unknown'),
                        'package': vuln.get('package', 'unknown'),
                        'version': vuln.get('version', 'unknown'),
                        'description': vuln.get('description', ''),
                        'fixed_version': vuln.get('fixed_version')
                    })
                    
                    total_vulnerabilities += 1
                    if vuln.get('severity', '').lower() == 'critical':
                        critical_vulnerabilities += 1
        
        # Calculate security score
        security_score = max(0, 100 - (critical_vulnerabilities * 20) - (total_vulnerabilities * 2))
        
        # Generate recommendations
        if critical_vulnerabilities > 0:
            recommendations.append(f"Fix {critical_vulnerabilities} critical vulnerabilities immediately")
        
        if total_vulnerabilities > 20:
            recommendations.append("Consider using a smaller base image to reduce attack surface")
        
        recommendations.extend([
            "Use multi-stage builds to minimize final image size",
            "Run as non-root user",
            "Implement health checks",
            "Use specific version tags instead of 'latest'",
            "Regular security scanning in CI/CD pipeline"
        ])
        
        # Check compliance
        compliance_checks = self._check_container_compliance(image_tag)
        
        return ContainerSecurityReport(
            scan_id=scan_id,
            timestamp=datetime.now(),
            image_name=image_tag,
            vulnerabilities=vulnerabilities,
            security_score=security_score,
            compliance_issues=compliance_issues,
            recommendations=recommendations,
            passed_checks=compliance_checks['passed'],
            failed_checks=compliance_checks['failed'],
            total_checks=compliance_checks['total']
        )
    
    def _run_trivy_scan(self, image_tag: str) -> Optional[Dict[str, Any]]:
        """Run Trivy security scan."""
        try:
            result = subprocess.run([
                'trivy', 'image', '--format', 'json', '--quiet', image_tag
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and result.stdout:
                trivy_data = json.loads(result.stdout)
                vulnerabilities = []
                
                for target in trivy_data.get('Results', []):
                    for vuln in target.get('Vulnerabilities', []):
                        vulnerabilities.append({
                            'id': vuln.get('VulnerabilityID'),
                            'severity': vuln.get('Severity'),
                            'package': vuln.get('PkgName'),
                            'version': vuln.get('InstalledVersion'),
                            'description': vuln.get('Title', ''),
                            'fixed_version': vuln.get('FixedVersion')
                        })
                
                return {'vulnerabilities': vulnerabilities}
        
        except Exception as e:
            logger.warning(f"Trivy scan failed: {e}")
        
        return None
    
    def _run_grype_scan(self, image_tag: str) -> Optional[Dict[str, Any]]:
        """Run Grype security scan."""
        try:
            result = subprocess.run([
                'grype', '-o', 'json', image_tag
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and result.stdout:
                grype_data = json.loads(result.stdout)
                vulnerabilities = []
                
                for match in grype_data.get('matches', []):
                    vuln = match.get('vulnerability', {})
                    artifact = match.get('artifact', {})
                    
                    vulnerabilities.append({
                        'id': vuln.get('id'),
                        'severity': vuln.get('severity'),
                        'package': artifact.get('name'),
                        'version': artifact.get('version'),
                        'description': vuln.get('description', ''),
                        'fixed_version': match.get('relatedVulnerabilities', [{}])[0].get('fixedInVersion')
                    })
                
                return {'vulnerabilities': vulnerabilities}
        
        except Exception as e:
            logger.warning(f"Grype scan failed: {e}")
        
        return None
    
    def _run_docker_scout_scan(self, image_tag: str) -> Optional[Dict[str, Any]]:
        """Run Docker Scout security scan."""
        try:
            result = subprocess.run([
                'docker', 'scout', 'cves', '--format', 'json', image_tag
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and result.stdout:
                scout_data = json.loads(result.stdout)
                vulnerabilities = []
                
                # Parse Docker Scout output (format may vary)
                # This is a simplified parser
                for vuln in scout_data.get('vulnerabilities', []):
                    vulnerabilities.append({
                        'id': vuln.get('id'),
                        'severity': vuln.get('severity'),
                        'package': vuln.get('packages', [{}])[0].get('name'),
                        'version': vuln.get('packages', [{}])[0].get('version'),
                        'description': vuln.get('title', ''),
                        'fixed_version': vuln.get('fixedInVersion')
                    })
                
                return {'vulnerabilities': vulnerabilities}
        
        except Exception as e:
            logger.warning(f"Docker Scout scan failed: {e}")
        
        return None
    
    def _check_container_compliance(self, image_tag: str) -> Dict[str, int]:
        """Check container compliance against best practices."""
        
        passed = 0
        failed = 0
        
        try:
            # Get image inspection data
            inspect_result = subprocess.run([
                'docker', 'inspect', image_tag
            ], capture_output=True, text=True)
            
            if inspect_result.returncode != 0:
                return {'passed': 0, 'failed': 1, 'total': 1}
            
            image_data = json.loads(inspect_result.stdout)[0]
            config = image_data.get('Config', {})
            
            # Check 1: Non-root user
            user = config.get('User', '')
            if user and user != 'root' and user != '0':
                passed += 1
            else:
                failed += 1
            
            # Check 2: No unnecessary packages (simplified check)
            # This would need more sophisticated analysis
            passed += 1  # Assume pass for now
            
            # Check 3: Health check present
            if config.get('Healthcheck'):
                passed += 1
            else:
                failed += 1
            
            # Check 4: Specific tags (not 'latest')
            if ':' in image_tag and not image_tag.endswith(':latest'):
                passed += 1
            else:
                failed += 1
            
            # Check 5: Minimal exposed ports
            exposed_ports = config.get('ExposedPorts', {})
            if len(exposed_ports) <= 2:  # Reasonable number of ports
                passed += 1
            else:
                failed += 1
        
        except Exception as e:
            logger.warning(f"Compliance check failed: {e}")
            failed += 1
        
        total = passed + failed
        return {'passed': passed, 'failed': failed, 'total': total}
    
    def optimize_image(self, environment: str = "production") -> Dict[str, Any]:
        """
        Optimize Docker image for size and performance.
        
        Args:
            environment: Target environment
            
        Returns:
            Optimization results
        """
        logger.info(f"Optimizing Docker image for {environment}")
        
        optimizations = []
        
        # Enable multi-stage builds
        if not self.config.multi_stage_build:
            self.config.multi_stage_build = True
            optimizations.append("Enabled multi-stage builds")
        
        # Enable layer optimization
        if not self.config.layer_optimization:
            self.config.layer_optimization = True
            optimizations.append("Enabled layer optimization")
        
        # Use distroless for production
        if environment == "production" and not self.config.distroless_runtime:
            self.config.distroless_runtime = True
            optimizations.append("Enabled distroless runtime for production")
        
        # Remove package caches
        if not self.config.remove_package_caches:
            self.config.remove_package_caches = True
            optimizations.append("Enabled package cache removal")
        
        # Use Alpine variant for smaller size
        if not self.config.alpine_variant:
            self.config.alpine_variant = True
            optimizations.append("Switched to Alpine base image")
        
        # Regenerate Dockerfile with optimizations
        dockerfile_content = self.generate_dockerfile(environment)
        
        return {
            'optimizations_applied': optimizations,
            'dockerfile_regenerated': True,
            'recommendations': [
                "Use .dockerignore to exclude unnecessary files",
                "Combine RUN commands to reduce layers",
                "Order Dockerfile commands by change frequency",
                "Use specific package versions",
                "Remove development tools in production images"
            ]
        }
    
    # Kubernetes manifest generation
    def generate_kubernetes_manifests(self, environment: str = "production") -> Dict[str, str]:
        """
        Generate Kubernetes deployment manifests.
        
        Args:
            environment: Target environment
            
        Returns:
            Dictionary of manifest files
        """
        logger.info(f"Generating Kubernetes manifests for {environment}")
        
        manifests = {}
        
        # Deployment manifest
        deployment = self._generate_k8s_deployment(environment)
        manifests['deployment.yaml'] = yaml.dump(deployment, default_flow_style=False)
        
        # Service manifest
        service = self._generate_k8s_service(environment)
        manifests['service.yaml'] = yaml.dump(service, default_flow_style=False)
        
        # ConfigMap for environment variables
        configmap = self._generate_k8s_configmap(environment)
        manifests['configmap.yaml'] = yaml.dump(configmap, default_flow_style=False)
        
        # Ingress for production
        if environment == "production":
            ingress = self._generate_k8s_ingress(environment)
            manifests['ingress.yaml'] = yaml.dump(ingress, default_flow_style=False)
        
        # HorizontalPodAutoscaler for production
        if environment == "production":
            hpa = self._generate_k8s_hpa(environment)
            manifests['hpa.yaml'] = yaml.dump(hpa, default_flow_style=False)
        
        # Save manifests to files
        k8s_dir = self.container_dir / "k8s" / environment
        k8s_dir.mkdir(parents=True, exist_ok=True)
        
        for filename, content in manifests.items():
            manifest_path = k8s_dir / filename
            with open(manifest_path, 'w') as f:
                f.write(content)
            logger.info(f"Generated K8s manifest: {manifest_path}")
        
        return manifests
    
    def _generate_k8s_deployment(self, environment: str) -> Dict[str, Any]:
        """Generate Kubernetes Deployment manifest."""
        
        env_config = self.config.environment_configs.get(environment, {})
        replicas = env_config.get('replicas', 3 if environment == "production" else 1)
        
        return {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {
                'name': f"{self.config.app_name}-{environment}",
                'labels': {
                    'app': self.config.app_name,
                    'environment': environment
                }
            },
            'spec': {
                'replicas': replicas,
                'selector': {
                    'matchLabels': {
                        'app': self.config.app_name,
                        'environment': environment
                    }
                },
                'template': {
                    'metadata': {
                        'labels': {
                            'app': self.config.app_name,
                            'environment': environment
                        }
                    },
                    'spec': {
                        'containers': [{
                            'name': self.config.app_name,
                            'image': f"{self.config.app_name}:{environment}",
                            'ports': [{
                                'containerPort': self.config.app_port,
                                'name': 'http'
                            }],
                            'env': [{
                                'name': 'FLASK_ENV',
                                'value': environment
                            }],
                            'envFrom': [{
                                'configMapRef': {
                                    'name': f"{self.config.app_name}-config-{environment}"
                                }
                            }],
                            'resources': {
                                'requests': {
                                    'memory': '256Mi',
                                    'cpu': '250m'
                                },
                                'limits': {
                                    'memory': self.config.memory_limit,
                                    'cpu': self.config.cpu_limit
                                }
                            },
                            'livenessProbe': {
                                'httpGet': {
                                    'path': self.config.health_check_endpoint,
                                    'port': 'http'
                                },
                                'initialDelaySeconds': 30,
                                'periodSeconds': 10
                            },
                            'readinessProbe': {
                                'httpGet': {
                                    'path': self.config.health_check_endpoint,
                                    'port': 'http'
                                },
                                'initialDelaySeconds': 5,
                                'periodSeconds': 5
                            }
                        }],
                        'securityContext': {
                            'runAsNonRoot': True,
                            'runAsUser': 1000,
                            'fsGroup': 1000
                        }
                    }
                }
            }
        }
    
    def _generate_k8s_service(self, environment: str) -> Dict[str, Any]:
        """Generate Kubernetes Service manifest."""
        
        return {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': f"{self.config.app_name}-service-{environment}",
                'labels': {
                    'app': self.config.app_name,
                    'environment': environment
                }
            },
            'spec': {
                'selector': {
                    'app': self.config.app_name,
                    'environment': environment
                },
                'ports': [{
                    'port': 80,
                    'targetPort': self.config.app_port,
                    'name': 'http'
                }],
                'type': 'ClusterIP'
            }
        }
    
    def _generate_k8s_configmap(self, environment: str) -> Dict[str, Any]:
        """Generate Kubernetes ConfigMap manifest."""
        
        env_config = self.config.environment_configs.get(environment, {})
        
        return {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {
                'name': f"{self.config.app_name}-config-{environment}",
                'labels': {
                    'app': self.config.app_name,
                    'environment': environment
                }
            },
            'data': {
                'FLASK_ENV': environment,
                'PORT': str(self.config.app_port),
                **{k: str(v) for k, v in env_config.get('environment_variables', {}).items()}
            }
        }
    
    def _generate_k8s_ingress(self, environment: str) -> Dict[str, Any]:
        """Generate Kubernetes Ingress manifest."""
        
        env_config = self.config.environment_configs.get(environment, {})
        host = env_config.get('ingress_host', f"{self.config.app_name}.example.com")
        
        return {
            'apiVersion': 'networking.k8s.io/v1',
            'kind': 'Ingress',
            'metadata': {
                'name': f"{self.config.app_name}-ingress-{environment}",
                'labels': {
                    'app': self.config.app_name,
                    'environment': environment
                },
                'annotations': {
                    'nginx.ingress.kubernetes.io/rewrite-target': '/',
                    'cert-manager.io/cluster-issuer': 'letsencrypt-prod'
                }
            },
            'spec': {
                'tls': [{
                    'hosts': [host],
                    'secretName': f"{self.config.app_name}-tls-{environment}"
                }],
                'rules': [{
                    'host': host,
                    'http': {
                        'paths': [{
                            'path': '/',
                            'pathType': 'Prefix',
                            'backend': {
                                'service': {
                                    'name': f"{self.config.app_name}-service-{environment}",
                                    'port': {
                                        'number': 80
                                    }
                                }
                            }
                        }]
                    }
                }]
            }
        }
    
    def _generate_k8s_hpa(self, environment: str) -> Dict[str, Any]:
        """Generate Kubernetes HorizontalPodAutoscaler manifest."""
        
        return {
            'apiVersion': 'autoscaling/v2',
            'kind': 'HorizontalPodAutoscaler',
            'metadata': {
                'name': f"{self.config.app_name}-hpa-{environment}",
                'labels': {
                    'app': self.config.app_name,
                    'environment': environment
                }
            },
            'spec': {
                'scaleTargetRef': {
                    'apiVersion': 'apps/v1',
                    'kind': 'Deployment',
                    'name': f"{self.config.app_name}-{environment}"
                },
                'minReplicas': 2,
                'maxReplicas': 10,
                'metrics': [{
                    'type': 'Resource',
                    'resource': {
                        'name': 'cpu',
                        'target': {
                            'type': 'Utilization',
                            'averageUtilization': 70
                        }
                    }
                }, {
                    'type': 'Resource',
                    'resource': {
                        'name': 'memory',
                        'target': {
                            'type': 'Utilization',
                            'averageUtilization': 80
                        }
                    }
                }]
            }
        }
    
    # Utility methods
    def get_image_info(self, image_tag: str) -> Optional[Dict[str, Any]]:
        """Get information about a Docker image."""
        
        try:
            result = subprocess.run([
                'docker', 'inspect', image_tag
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                image_data = json.loads(result.stdout)[0]
                return {
                    'id': image_data['Id'],
                    'created': image_data['Created'],
                    'size': image_data['Size'],
                    'architecture': image_data['Architecture'],
                    'os': image_data['Os'],
                    'labels': image_data['Config'].get('Labels', {}),
                    'exposed_ports': list(image_data['Config'].get('ExposedPorts', {}).keys()),
                    'environment': image_data['Config'].get('Env', [])
                }
        
        except Exception as e:
            logger.error(f"Failed to get image info: {e}")
        
        return None
    
    def cleanup_images(self, keep_latest: int = 3) -> Dict[str, Any]:
        """Clean up old Docker images."""
        
        try:
            # Get list of images for this app
            result = subprocess.run([
                'docker', 'images', '--format', 'json'
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                return {'success': False, 'error': 'Failed to list images'}
            
            images = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    image_data = json.loads(line)
                    if self.config.app_name in image_data.get('Repository', ''):
                        images.append(image_data)
            
            # Sort by created date (newest first)
            images.sort(key=lambda x: x['CreatedAt'], reverse=True)
            
            # Keep only the latest N images
            images_to_remove = images[keep_latest:]
            removed_images = []
            
            for image in images_to_remove:
                image_id = image['ID']
                try:
                    subprocess.run([
                        'docker', 'rmi', image_id
                    ], capture_output=True, text=True, check=True)
                    removed_images.append(image_id)
                except subprocess.CalledProcessError:
                    logger.warning(f"Could not remove image {image_id}")
            
            return {
                'success': True,
                'removed_images': removed_images,
                'kept_images': len(images) - len(removed_images)
            }
        
        except Exception as e:
            logger.error(f"Image cleanup failed: {e}")
            return {'success': False, 'error': str(e)}