#!/usr/bin/env python3
"""
Health Check Script
PgForge Apache AGE Graph Analytics Platform

Comprehensive system health monitoring and validation script.
"""

import os
import sys
import json
import time
import logging
import requests
import psycopg2
import redis
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SystemHealthChecker:
    """Comprehensive system health checker"""
    
    def __init__(self):
        self.checks = []
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'overall_status': 'unknown',
            'checks': {},
            'summary': {
                'total_checks': 0,
                'passed': 0,
                'failed': 0,
                'warnings': 0
            }
        }
    
    def add_check(self, name: str, status: str, details: Dict[str, Any], duration: float = 0.0):
        """Add a health check result"""
        self.results['checks'][name] = {
            'status': status,
            'details': details,
            'duration_ms': round(duration * 1000, 2),
            'timestamp': datetime.now().isoformat()
        }
        
        # Update summary
        self.results['summary']['total_checks'] += 1
        if status == 'pass':
            self.results['summary']['passed'] += 1
        elif status == 'fail':
            self.results['summary']['failed'] += 1
        elif status == 'warning':
            self.results['summary']['warnings'] += 1
    
    def check_database_connection(self) -> bool:
        """Check PostgreSQL database connectivity"""
        logger.info("🔍 Checking database connection...")
        start_time = time.time()
        
        try:
            database_uri = os.environ.get(
                'DATABASE_URI',
                'postgresql://graph_admin:password@postgres-age:5432/graph_analytics_db'
            )
            
            # Parse database URI
            from urllib.parse import urlparse
            parsed = urlparse(database_uri)
            
            # Test connection
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path[1:],
                user=parsed.username,
                password=parsed.password,
                connect_timeout=5
            )
            
            cursor = conn.cursor()
            
            # Test basic query
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            
            # Check database size
            cursor.execute("""
                SELECT pg_size_pretty(pg_database_size(current_database())) as size,
                       current_database() as database_name
            """)
            db_info = cursor.fetchone()
            
            # Check connection count
            cursor.execute("""
                SELECT count(*) as active_connections
                FROM pg_stat_activity 
                WHERE state = 'active'
            """)
            active_connections = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            duration = time.time() - start_time
            self.add_check('database_connection', 'pass', {
                'version': version,
                'database_name': db_info[1],
                'database_size': db_info[0],
                'active_connections': active_connections,
                'connection_time_ms': round(duration * 1000, 2)
            }, duration)
            
            return True
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('database_connection', 'fail', {
                'error': str(e),
                'connection_time_ms': round(duration * 1000, 2)
            }, duration)
            return False
    
    def check_apache_age_extension(self) -> bool:
        """Check Apache AGE extension status"""
        logger.info("🔧 Checking Apache AGE extension...")
        start_time = time.time()
        
        try:
            database_uri = os.environ.get(
                'DATABASE_URI',
                'postgresql://graph_admin:password@postgres-age:5432/graph_analytics_db'
            )
            
            from urllib.parse import urlparse
            parsed = urlparse(database_uri)
            
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path[1:],
                user=parsed.username,
                password=parsed.password,
                connect_timeout=5
            )
            
            cursor = conn.cursor()
            
            # Check AGE extension
            cursor.execute("SELECT * FROM pg_extension WHERE extname = 'age';")
            age_ext = cursor.fetchone()
            
            if not age_ext:
                raise Exception("Apache AGE extension not found")
            
            # Check available graphs
            cursor.execute("SELECT graph_name FROM ag_catalog.ag_graph;")
            graphs = [row[0] for row in cursor.fetchall()]
            
            # Test graph query
            cursor.execute("SET search_path = ag_catalog, public;")
            cursor.execute("SELECT * FROM cypher('analytics_graph', $$ MATCH (n) RETURN count(n) $$) as (count agtype);")
            node_count = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            duration = time.time() - start_time
            self.add_check('apache_age_extension', 'pass', {
                'extension_version': age_ext[1] if age_ext else None,
                'available_graphs': graphs,
                'total_graphs': len(graphs),
                'node_count_test': str(node_count)
            }, duration)
            
            return True
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('apache_age_extension', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def check_redis_connection(self) -> bool:
        """Check Redis connectivity"""
        logger.info("📦 Checking Redis connection...")
        start_time = time.time()
        
        try:
            redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
            
            # Parse Redis URL
            r = redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
            
            # Test basic operations
            r.ping()
            
            # Get Redis info
            info = r.info()
            memory_info = r.info('memory')
            
            # Test set/get
            test_key = 'health_check_test'
            r.set(test_key, 'test_value', ex=10)  # Expire in 10 seconds
            test_result = r.get(test_key).decode('utf-8')
            r.delete(test_key)
            
            duration = time.time() - start_time
            self.add_check('redis_connection', 'pass', {
                'redis_version': info.get('redis_version'),
                'used_memory_human': memory_info.get('used_memory_human'),
                'connected_clients': info.get('connected_clients'),
                'uptime_in_seconds': info.get('uptime_in_seconds'),
                'test_operation': 'success' if test_result == 'test_value' else 'failed'
            }, duration)
            
            return True
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('redis_connection', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def check_web_application(self) -> bool:
        """Check web application accessibility"""
        logger.info("🌐 Checking web application...")
        start_time = time.time()
        
        try:
            base_url = os.environ.get('BASE_URL', 'http://webapp:8080')
            
            # Test health endpoint
            health_response = requests.get(
                f"{base_url}/health",
                timeout=10
            )
            
            if health_response.status_code != 200:
                raise Exception(f"Health endpoint returned {health_response.status_code}")
            
            # Test main page
            main_response = requests.get(
                f"{base_url}/",
                timeout=10,
                allow_redirects=True
            )
            
            # Test API endpoint
            api_response = requests.get(
                f"{base_url}/api/graph/list",
                timeout=10
            )
            
            duration = time.time() - start_time
            self.add_check('web_application', 'pass', {
                'health_status': health_response.status_code,
                'main_page_status': main_response.status_code,
                'api_status': api_response.status_code,
                'response_time_ms': round(duration * 1000, 2)
            }, duration)
            
            return True
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('web_application', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def check_file_systems(self) -> bool:
        """Check file system accessibility"""
        logger.info("📁 Checking file systems...")
        start_time = time.time()
        
        try:
            import shutil
            
            # Check required directories
            required_dirs = ['/app/logs', '/app/uploads', '/app/cache']
            dir_status = {}
            
            for dir_path in required_dirs:
                path = Path(dir_path)
                if path.exists():
                    # Check if writable
                    try:
                        test_file = path / 'health_check_test.txt'
                        test_file.write_text('test')
                        test_file.unlink()  # Remove test file
                        dir_status[dir_path] = 'writable'
                    except:
                        dir_status[dir_path] = 'read_only'
                else:
                    # Try to create directory
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        dir_status[dir_path] = 'created'
                    except:
                        dir_status[dir_path] = 'missing'
            
            # Check disk space
            disk_usage = shutil.disk_usage('/')
            free_space_gb = disk_usage.free // (1024**3)
            total_space_gb = disk_usage.total // (1024**3)
            used_space_gb = (disk_usage.total - disk_usage.free) // (1024**3)
            
            duration = time.time() - start_time
            status = 'warning' if free_space_gb < 5 else 'pass'  # Warning if less than 5GB free
            
            self.add_check('file_systems', status, {
                'directories': dir_status,
                'disk_usage': {
                    'total_gb': total_space_gb,
                    'used_gb': used_space_gb,
                    'free_gb': free_space_gb,
                    'usage_percent': round((used_space_gb / total_space_gb) * 100, 1)
                }
            }, duration)
            
            return status != 'fail'
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('file_systems', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def check_system_resources(self) -> bool:
        """Check system resource usage"""
        logger.info("💻 Checking system resources...")
        start_time = time.time()
        
        try:
            import psutil
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # Memory usage
            memory = psutil.virtual_memory()
            
            # Process information
            process = psutil.Process()
            process_memory = process.memory_info()
            
            duration = time.time() - start_time
            
            # Determine status based on resource usage
            status = 'pass'
            if cpu_percent > 80 or memory.percent > 85:
                status = 'warning'
            if cpu_percent > 95 or memory.percent > 95:
                status = 'fail'
            
            self.add_check('system_resources', status, {
                'cpu': {
                    'usage_percent': cpu_percent,
                    'cpu_count': cpu_count
                },
                'memory': {
                    'total_gb': round(memory.total / (1024**3), 2),
                    'available_gb': round(memory.available / (1024**3), 2),
                    'used_gb': round(memory.used / (1024**3), 2),
                    'percent': memory.percent
                },
                'process': {
                    'rss_mb': round(process_memory.rss / (1024**2), 2),
                    'vms_mb': round(process_memory.vms / (1024**2), 2)
                }
            }, duration)
            
            return status != 'fail'
            
        except ImportError:
            # psutil not available
            duration = time.time() - start_time
            self.add_check('system_resources', 'warning', {
                'error': 'psutil not available, cannot check system resources'
            }, duration)
            return True
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('system_resources', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def check_environment_configuration(self) -> bool:
        """Check environment configuration"""
        logger.info("⚙️ Checking environment configuration...")
        start_time = time.time()
        
        try:
            # Required environment variables
            required_vars = [
                'DATABASE_URI',
                'SECRET_KEY',
                'SECURITY_PASSWORD_SALT'
            ]
            
            # Optional but recommended variables
            recommended_vars = [
                'REDIS_URL',
                'OPENAI_API_KEY',
                'ADMIN_PASSWORD'
            ]
            
            env_status = {}
            
            # Check required variables
            for var in required_vars:
                value = os.environ.get(var)
                if value:
                    env_status[var] = 'set' if var != 'SECRET_KEY' else 'set (hidden)'
                else:
                    env_status[var] = 'missing'
            
            # Check recommended variables
            for var in recommended_vars:
                value = os.environ.get(var)
                env_status[var] = 'set' if value else 'not_set'
            
            # Check feature flags
            feature_flags = {}
            for var in os.environ:
                if var.startswith('ENABLE_'):
                    feature_flags[var] = os.environ[var].lower() == 'true'
            
            duration = time.time() - start_time
            
            # Determine status
            missing_required = [var for var in required_vars if env_status[var] == 'missing']
            status = 'fail' if missing_required else 'pass'
            
            self.add_check('environment_configuration', status, {
                'environment_variables': env_status,
                'feature_flags': feature_flags,
                'missing_required': missing_required
            }, duration)
            
            return status != 'fail'
            
        except Exception as e:
            duration = time.time() - start_time
            self.add_check('environment_configuration', 'fail', {
                'error': str(e)
            }, duration)
            return False
    
    def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks"""
        logger.info("🏥 Starting comprehensive health check...")
        
        checks = [
            ('Environment Configuration', self.check_environment_configuration),
            ('File Systems', self.check_file_systems),
            ('Database Connection', self.check_database_connection),
            ('Apache AGE Extension', self.check_apache_age_extension),
            ('Redis Connection', self.check_redis_connection),
            ('System Resources', self.check_system_resources),
            ('Web Application', self.check_web_application),
        ]
        
        all_passed = True
        
        for check_name, check_func in checks:
            logger.info(f"➡️  Running: {check_name}")
            try:
                success = check_func()
                if not success:
                    all_passed = False
                logger.info(f"✅ {check_name}: {'PASS' if success else 'FAIL'}")
            except Exception as e:
                logger.error(f"❌ {check_name}: ERROR - {e}")
                all_passed = False
        
        # Determine overall status
        failed_checks = self.results['summary']['failed']
        warning_checks = self.results['summary']['warnings']
        
        if failed_checks > 0:
            self.results['overall_status'] = 'unhealthy'
        elif warning_checks > 0:
            self.results['overall_status'] = 'degraded'
        else:
            self.results['overall_status'] = 'healthy'
        
        # Add execution summary
        self.results['execution_summary'] = {
            'total_duration_seconds': sum(
                check['duration_ms'] / 1000 
                for check in self.results['checks'].values()
            ),
            'overall_status': self.results['overall_status'],
            'recommendation': self._get_health_recommendation()
        }
        
        return self.results
    
    def _get_health_recommendation(self) -> str:
        """Get health recommendation based on results"""
        if self.results['overall_status'] == 'healthy':
            return "System is operating normally. All checks passed."
        elif self.results['overall_status'] == 'degraded':
            return "System is operational but has some issues that should be addressed."
        else:
            return "System has critical issues that require immediate attention."
    
    def print_summary(self):
        """Print a human-readable summary"""
        print("\n" + "="*80)
        print("🏥 SYSTEM HEALTH CHECK SUMMARY")
        print("="*80)
        
        # Overall status
        status_icon = {
            'healthy': '✅',
            'degraded': '⚠️ ',
            'unhealthy': '❌'
        }.get(self.results['overall_status'], '❓')
        
        print(f"\n{status_icon} Overall Status: {self.results['overall_status'].upper()}")
        print(f"📊 Total Checks: {self.results['summary']['total_checks']}")
        print(f"✅ Passed: {self.results['summary']['passed']}")
        print(f"⚠️  Warnings: {self.results['summary']['warnings']}")
        print(f"❌ Failed: {self.results['summary']['failed']}")
        
        # Individual check results
        print(f"\n📋 Check Results:")
        for check_name, check_result in self.results['checks'].items():
            status_icon = {
                'pass': '✅',
                'warning': '⚠️ ',
                'fail': '❌'
            }.get(check_result['status'], '❓')
            
            duration = check_result['duration_ms']
            print(f"  {status_icon} {check_name.replace('_', ' ').title()}: {check_result['status'].upper()} ({duration}ms)")
            
            # Show error details for failed checks
            if check_result['status'] == 'fail' and 'error' in check_result['details']:
                print(f"     Error: {check_result['details']['error']}")
        
        print(f"\n💡 Recommendation: {self.results['execution_summary']['recommendation']}")
        print(f"⏱️  Total execution time: {self.results['execution_summary']['total_duration_seconds']:.2f}s")
        print(f"🕐 Check completed at: {self.results['timestamp']}")
        
        print("\n" + "="*80)


def main():
    """Main health check function"""
    checker = SystemHealthChecker()
    results = checker.run_all_checks()
    
    # Print summary
    checker.print_summary()
    
    # Save detailed results to file
    results_file = Path('/app/logs/health_check.json')
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"📄 Detailed results saved to: {results_file}")
    
    # Return appropriate exit code
    if results['overall_status'] == 'healthy':
        return 0
    elif results['overall_status'] == 'degraded':
        return 1
    else:
        return 2


if __name__ == '__main__':
    sys.exit(main())