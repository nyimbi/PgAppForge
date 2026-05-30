#!/usr/bin/env python3
"""
Test data management infrastructure for Flask-AppBuilder tutorial testing.

This module provides comprehensive test data generation, seeding, and
management capabilities for reliable and reproducible testing.
"""

import json
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Callable
from pathlib import Path
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataSetConfiguration:
    """Configuration for test data generation."""
    task_count: int = 50
    category_count: int = 8
    user_count: int = 10
    seed: Optional[int] = None
    locale: str = 'en_US'
    date_range_days: int = 90
    include_relationships: bool = True
    generate_ai_data: bool = True
    generate_audit_data: bool = True


class TestDataGenerator:
    """Advanced test data generator with realistic patterns."""

    def __init__(self, config: DataSetConfiguration = None):
        self.config = config or DataSetConfiguration()
        if self.config.seed:
            random.seed(self.config.seed)

        # Data templates and patterns
        self.task_templates = self._load_task_templates()
        self.category_data = self._load_category_data()
        self.user_data = self._load_user_data()
        self.ai_responses = self._load_ai_responses()

    def _load_task_templates(self) -> List[Dict[str, Any]]:
        """Load task templates for realistic generation."""
        return [
            {
                'title': 'Implement {feature} for {component}',
                'description': 'Design and implement {feature} functionality for the {component} component. This includes {details} and proper error handling.',
                'tags': ['development', 'implementation', 'feature'],
                'estimated_hours': (4, 16),
                'complexity': 'medium'
            },
            {
                'title': 'Fix {issue} in {component}',
                'description': 'Investigate and resolve {issue} reported in {component}. Impact: {impact}. Priority: {priority_reason}.',
                'tags': ['bugfix', 'maintenance', 'investigation'],
                'estimated_hours': (2, 8),
                'complexity': 'low'
            },
            {
                'title': 'Optimize {component} performance',
                'description': 'Analyze and improve performance of {component}. Focus on {performance_area} and implement {optimization_type}.',
                'tags': ['performance', 'optimization', 'analysis'],
                'estimated_hours': (6, 20),
                'complexity': 'high'
            },
            {
                'title': 'Add {feature} integration',
                'description': 'Integrate {feature} with existing system. Requirements: {requirements}. Expected outcome: {outcome}.',
                'tags': ['integration', 'api', 'feature'],
                'estimated_hours': (8, 24),
                'complexity': 'high'
            },
            {
                'title': 'Update {component} documentation',
                'description': 'Create comprehensive documentation for {component}. Include {doc_sections} and usage examples.',
                'tags': ['documentation', 'maintenance', 'knowledge-sharing'],
                'estimated_hours': (3, 12),
                'complexity': 'low'
            },
            {
                'title': 'Test {feature} functionality',
                'description': 'Develop comprehensive test suite for {feature}. Cover {test_areas} and edge cases.',
                'tags': ['testing', 'quality-assurance', 'automation'],
                'estimated_hours': (4, 16),
                'complexity': 'medium'
            },
            {
                'title': 'Deploy {feature} to {environment}',
                'description': 'Deploy and configure {feature} in {environment} environment. Ensure {deployment_requirements}.',
                'tags': ['deployment', 'devops', 'configuration'],
                'estimated_hours': (2, 10),
                'complexity': 'medium'
            },
            {
                'title': 'Research {technology} implementation',
                'description': 'Research and evaluate {technology} for {use_case}. Provide recommendations and proof of concept.',
                'tags': ['research', 'evaluation', 'planning'],
                'estimated_hours': (8, 32),
                'complexity': 'high'
            }
        ]

    def _load_category_data(self) -> List[Dict[str, Any]]:
        """Load category templates."""
        return [
            {
                'name': 'Backend Development',
                'description': 'Server-side development, APIs, and database work',
                'color': '#007bff',
                'icon': 'server',
                'priority': 'high'
            },
            {
                'name': 'Frontend Development',
                'description': 'User interface and user experience development',
                'color': '#28a745',
                'icon': 'desktop',
                'priority': 'high'
            },
            {
                'name': 'Testing & QA',
                'description': 'Quality assurance, testing, and validation activities',
                'color': '#ffc107',
                'icon': 'check-circle',
                'priority': 'medium'
            },
            {
                'name': 'DevOps & Infrastructure',
                'description': 'Deployment, monitoring, and infrastructure management',
                'color': '#dc3545',
                'icon': 'cloud',
                'priority': 'high'
            },
            {
                'name': 'Documentation',
                'description': 'Technical writing, API docs, and knowledge sharing',
                'color': '#6f42c1',
                'icon': 'book',
                'priority': 'medium'
            },
            {
                'name': 'Research & Planning',
                'description': 'Research, analysis, and project planning activities',
                'color': '#fd7e14',
                'icon': 'search',
                'priority': 'medium'
            },
            {
                'name': 'Security & Compliance',
                'description': 'Security audits, compliance, and vulnerability management',
                'color': '#e83e8c',
                'icon': 'shield',
                'priority': 'high'
            },
            {
                'name': 'Support & Maintenance',
                'description': 'Bug fixes, maintenance, and customer support',
                'color': '#20c997',
                'icon': 'tools',
                'priority': 'medium'
            }
        ]

    def _load_user_data(self) -> List[Dict[str, Any]]:
        """Load user templates for realistic generation."""
        return [
            {'first_name': 'Alice', 'last_name': 'Johnson', 'role': 'Senior Developer', 'department': 'Engineering'},
            {'first_name': 'Bob', 'last_name': 'Smith', 'role': 'Product Manager', 'department': 'Product'},
            {'first_name': 'Carol', 'last_name': 'Davis', 'role': 'QA Engineer', 'department': 'Quality'},
            {'first_name': 'David', 'last_name': 'Wilson', 'role': 'DevOps Engineer', 'department': 'Infrastructure'},
            {'first_name': 'Eva', 'last_name': 'Brown', 'role': 'UX Designer', 'department': 'Design'},
            {'first_name': 'Frank', 'last_name': 'Miller', 'role': 'Backend Developer', 'department': 'Engineering'},
            {'first_name': 'Grace', 'last_name': 'Lee', 'role': 'Frontend Developer', 'department': 'Engineering'},
            {'first_name': 'Henry', 'last_name': 'Taylor', 'role': 'Security Engineer', 'department': 'Security'},
            {'first_name': 'Iris', 'last_name': 'Anderson', 'role': 'Data Analyst', 'department': 'Analytics'},
            {'first_name': 'Jack', 'last_name': 'Thomas', 'role': 'Technical Writer', 'department': 'Documentation'}
        ]

    def _load_ai_responses(self) -> Dict[str, List[str]]:
        """Load AI response templates."""
        return {
            'summaries': [
                'This task involves implementing core functionality with proper error handling and validation.',
                'A comprehensive solution requiring analysis of existing systems and integration patterns.',
                'Strategic implementation that impacts multiple system components and user workflows.',
                'Technical solution focused on performance optimization and scalability improvements.',
                'Cross-functional task requiring collaboration between development and operations teams.'
            ],
            'tags': [
                'development, implementation, core-functionality',
                'analysis, integration, system-design',
                'strategic, multi-component, user-impact',
                'performance, optimization, scalability',
                'cross-functional, collaboration, devops'
            ],
            'insights': [
                'Project progress is on track with 85% completion rate and minimal blockers.',
                'Resource allocation is optimal with balanced workload distribution across teams.',
                'Technical debt levels are manageable and within acceptable thresholds.',
                'Performance metrics indicate strong system stability and user satisfaction.',
                'Current sprint velocity suggests early completion of planned milestones.'
            ]
        }

    def generate_tasks(self) -> List[Dict[str, Any]]:
        """Generate realistic task data."""
        tasks = []
        categories = self.generate_categories()

        for i in range(self.config.task_count):
            template = random.choice(self.task_templates)
            category = random.choice(categories)

            # Generate dynamic content
            features = ['authentication', 'payment', 'notification', 'search', 'reporting', 'dashboard', 'analytics']
            components = ['API', 'frontend', 'database', 'cache', 'queue', 'middleware', 'service']
            issues = ['memory leak', 'performance degradation', 'security vulnerability', 'data inconsistency']

            title = template['title'].format(
                feature=random.choice(features),
                component=random.choice(components),
                issue=random.choice(issues)
            )

            # Generate dates
            created_date = datetime.now() - timedelta(days=random.randint(0, self.config.date_range_days))
            due_date = created_date + timedelta(days=random.randint(1, 30))

            # Generate status and progress
            status = random.choices(
                ['pending', 'in_progress', 'completed', 'cancelled'],
                weights=[30, 40, 25, 5]
            )[0]

            progress = 0
            actual_hours = None

            if status == 'in_progress':
                progress = random.randint(10, 90)
            elif status == 'completed':
                progress = 100
                actual_hours = random.randint(*template['estimated_hours'])
            elif status == 'cancelled':
                progress = random.randint(0, 50)

            # Generate priority based on category and complexity
            if category['priority'] == 'high' or template['complexity'] == 'high':
                priority = random.choices(['medium', 'high', 'urgent'], weights=[20, 60, 20])[0]
            else:
                priority = random.choices(['low', 'medium', 'high'], weights=[40, 50, 10])[0]

            task = {
                'id': i + 1,
                'title': title,
                'description': self._generate_description(template, features, components),
                'category_id': category['id'],
                'category_name': category['name'],
                'priority': priority,
                'status': status,
                'progress': progress,
                'estimated_hours': random.randint(*template['estimated_hours']),
                'actual_hours': actual_hours,
                'created_on': created_date,
                'updated_on': created_date + timedelta(days=random.randint(0, 10)),
                'due_date': due_date,
                'tags': ', '.join(template['tags']),
                'complexity': template['complexity']
            }

            # Add AI-generated content if configured
            if self.config.generate_ai_data:
                task.update({
                    'ai_summary': random.choice(self.ai_responses['summaries']),
                    'ai_tags': random.choice(self.ai_responses['tags']),
                    'ai_generated_on': created_date + timedelta(hours=random.randint(1, 24))
                })

            # Add audit data if configured
            if self.config.generate_audit_data:
                users = self.generate_users()
                creator = random.choice(users)
                task.update({
                    'created_by': creator['username'],
                    'created_by_name': f"{creator['first_name']} {creator['last_name']}",
                    'changed_by': creator['username'],
                    'changed_on': task['updated_on']
                })

            tasks.append(task)

        return tasks

    def generate_categories(self) -> List[Dict[str, Any]]:
        """Generate category data."""
        selected_categories = self.category_data[:self.config.category_count]

        for i, category in enumerate(selected_categories):
            category['id'] = i + 1
            category['created_on'] = datetime.now() - timedelta(days=random.randint(30, 90))
            category['task_count'] = 0  # Will be updated when tasks are generated

        return selected_categories

    def generate_users(self) -> List[Dict[str, Any]]:
        """Generate user data."""
        users = []
        selected_users = self.user_data[:self.config.user_count]

        for i, user_template in enumerate(selected_users):
            username = f"{user_template['first_name'].lower()}.{user_template['last_name'].lower()}"
            email = f"{username}@example.com"

            user = {
                'id': i + 1,
                'username': username,
                'email': email,
                'first_name': user_template['first_name'],
                'last_name': user_template['last_name'],
                'role': user_template['role'],
                'department': user_template['department'],
                'active': random.choice([True] * 9 + [False]),  # 90% active
                'created_on': datetime.now() - timedelta(days=random.randint(60, 180)),
                'last_login': datetime.now() - timedelta(days=random.randint(0, 30)),
                'login_count': random.randint(5, 200)
            }

            users.append(user)

        return users

    def _generate_description(self, template: Dict, features: List[str], components: List[str]) -> str:
        """Generate detailed task descriptions."""
        details_options = [
            'API design and implementation',
            'database schema updates',
            'frontend component development',
            'integration testing',
            'performance optimization',
            'security validation'
        ]

        impacts = ['critical system functionality', 'user experience', 'system performance', 'data integrity']
        requirements = ['proper authentication', 'error handling', 'logging', 'monitoring', 'documentation']

        return template['description'].format(
            feature=random.choice(features),
            component=random.choice(components),
            details=', '.join(random.sample(details_options, 2)),
            impact=random.choice(impacts),
            priority_reason=f"affects {random.choice(impacts)}",
            performance_area=random.choice(['database queries', 'API response time', 'memory usage']),
            optimization_type=random.choice(['caching', 'indexing', 'algorithm improvement']),
            requirements=', '.join(random.sample(requirements, 3)),
            outcome=f"improved {random.choice(['performance', 'reliability', 'user experience'])}",
            doc_sections=', '.join(['API reference', 'usage examples', 'troubleshooting guide']),
            test_areas=', '.join(['unit tests', 'integration tests', 'performance tests']),
            environment=random.choice(['staging', 'production', 'development']),
            deployment_requirements=random.choice(['zero downtime', 'rollback capability', 'monitoring']),
            technology=random.choice(['GraphQL', 'Redis', 'Docker', 'Kubernetes']),
            use_case=random.choice(['real-time features', 'scalability', 'performance optimization'])
        )


class TestDataSeeder:
    """Seed test data into application models."""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.generator = TestDataGenerator()

    def seed_categories(self, categories: List[Dict[str, Any]]) -> Dict[int, Any]:
        """Seed category data into database."""
        category_map = {}

        with self.app.app_context():
            from models import TaskCategory

            for cat_data in categories:
                category = TaskCategory(
                    name=cat_data['name'],
                    description=cat_data['description'],
                    color=cat_data.get('color', '#007bff'),
                    icon=cat_data.get('icon', 'folder')
                )

                self.db.session.add(category)
                self.db.session.flush()  # Get ID without committing
                category_map[cat_data['id']] = category

            self.db.session.commit()
            logger.info(f"Seeded {len(categories)} categories")

        return category_map

    def seed_users(self, users: List[Dict[str, Any]]) -> Dict[int, Any]:
        """Seed user data into database."""
        user_map = {}

        with self.app.app_context():
            # Note: User seeding depends on Flask-AppBuilder's user model
            # This is a simplified version
            for user_data in users:
                # In real implementation, would use appbuilder.sm.add_user()
                user_map[user_data['id']] = user_data

            logger.info(f"Seeded {len(users)} users")

        return user_map

    def seed_tasks(self, tasks: List[Dict[str, Any]], category_map: Dict[int, Any]) -> List[Any]:
        """Seed task data into database."""
        task_objects = []

        with self.app.app_context():
            from models import Task, Priority, Status

            for task_data in tasks:
                category = category_map.get(task_data['category_id'])

                task = Task(
                    title=task_data['title'],
                    description=task_data['description'],
                    category=category,
                    priority=Priority(task_data['priority']),
                    status=Status(task_data['status']),
                    progress=task_data['progress'],
                    estimated_hours=task_data['estimated_hours'],
                    actual_hours=task_data['actual_hours'],
                    due_date=task_data['due_date'],
                    ai_summary=task_data.get('ai_summary'),
                    ai_tags=task_data.get('ai_tags')
                )

                self.db.session.add(task)
                task_objects.append(task)

            self.db.session.commit()
            logger.info(f"Seeded {len(tasks)} tasks")

        return task_objects

    def seed_all(self, config: DataSetConfiguration = None) -> Dict[str, Any]:
        """Seed complete test dataset."""
        if config:
            self.generator.config = config

        # Generate data
        categories = self.generator.generate_categories()
        users = self.generator.generate_users()
        tasks = self.generator.generate_tasks()

        # Seed data
        category_map = self.seed_categories(categories)
        user_map = self.seed_users(users)
        task_objects = self.seed_tasks(tasks, category_map)

        return {
            'categories': len(categories),
            'users': len(users),
            'tasks': len(tasks),
            'category_objects': category_map,
            'user_objects': user_map,
            'task_objects': task_objects
        }


class TestDataManager:
    """Comprehensive test data management."""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path(__file__).parent / 'test_data'
        self.data_dir.mkdir(exist_ok=True)

    def save_dataset(self, name: str, data: Dict[str, Any]):
        """Save generated dataset to file."""
        file_path = self.data_dir / f"{name}.json"

        # Convert datetime objects to strings for JSON serialization
        serializable_data = self._make_serializable(data)

        with open(file_path, 'w') as f:
            json.dump(serializable_data, f, indent=2, default=str)

        logger.info(f"Saved dataset '{name}' to {file_path}")

    def load_dataset(self, name: str) -> Dict[str, Any]:
        """Load dataset from file."""
        file_path = self.data_dir / f"{name}.json"

        if not file_path.exists():
            raise FileNotFoundError(f"Dataset '{name}' not found at {file_path}")

        with open(file_path, 'r') as f:
            data = json.load(f)

        return self._restore_datetime_objects(data)

    def list_datasets(self) -> List[str]:
        """List available datasets."""
        return [f.stem for f in self.data_dir.glob('*.json')]

    def create_standard_datasets(self):
        """Create standard test datasets."""
        generator = TestDataGenerator()

        # Small dataset
        small_config = DataSetConfiguration(
            task_count=10,
            category_count=5,
            user_count=5,
            seed=12345
        )
        generator.config = small_config
        small_data = {
            'categories': generator.generate_categories(),
            'users': generator.generate_users(),
            'tasks': generator.generate_tasks()
        }
        self.save_dataset('small', small_data)

        # Medium dataset
        medium_config = DataSetConfiguration(
            task_count=50,
            category_count=8,
            user_count=10,
            seed=12345
        )
        generator.config = medium_config
        medium_data = {
            'categories': generator.generate_categories(),
            'users': generator.generate_users(),
            'tasks': generator.generate_tasks()
        }
        self.save_dataset('medium', medium_data)

        # Large dataset
        large_config = DataSetConfiguration(
            task_count=200,
            category_count=10,
            user_count=20,
            seed=12345
        )
        generator.config = large_config
        large_data = {
            'categories': generator.generate_categories(),
            'users': generator.generate_users(),
            'tasks': generator.generate_tasks()
        }
        self.save_dataset('large', large_data)

        logger.info("Created standard test datasets: small, medium, large")

    def _make_serializable(self, obj: Any) -> Any:
        """Make object JSON serializable."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        else:
            return obj

    def _restore_datetime_objects(self, obj: Any) -> Any:
        """Restore datetime objects from JSON."""
        if isinstance(obj, str) and self._is_iso_datetime(obj):
            return datetime.fromisoformat(obj)
        elif isinstance(obj, dict):
            return {k: self._restore_datetime_objects(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._restore_datetime_objects(item) for item in obj]
        else:
            return obj

    def _is_iso_datetime(self, value: str) -> bool:
        """Check if string is ISO datetime format."""
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False


# Global data manager instance
data_manager = TestDataManager()


# Export main components
__all__ = [
    'DataSetConfiguration',
    'TestDataGenerator',
    'TestDataSeeder',
    'TestDataManager',
    'data_manager'
]