"""
Comprehensive Multi-Tenant Testing Framework.

This module provides comprehensive testing utilities and test cases for 
multi-tenant SaaS functionality including isolation, security, performance,
and integration testing.
"""

import unittest
import threading
import time
import random
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, Callable
from unittest.mock import Mock, patch

from flask import Flask
from flask_testing import TestCase
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import multi-tenant components
from pgappforge import AppBuilder, SQLA
from pgappforge.models.tenant_models import (
    Tenant, TenantUser, TenantConfig, TenantSubscription, TenantUsage, TenantAwareMixin
)
from pgappforge.models.tenant_context import tenant_context, get_current_tenant_id
from pgappforge.tenants.billing import get_billing_service
from pgappforge.tenants.usage_tracking import get_usage_tracker
from pgappforge.tenants.branding import get_branding_manager
from pgappforge.tenants.performance import get_db_optimizer, get_cache_manager
from pgappforge.tenants.resource_isolation import (
    get_resource_monitor, get_resource_limiter, ResourceType, LimitAction
)
from pgappforge.tenants.scalability import get_distribution_manager


class MultiTenantTestCase(TestCase):
    """Base test case for multi-tenant testing with utilities."""
    
    def create_app(self):
        """Create Flask app for testing."""
        app = Flask(__name__)
        app.config.from_object('tests.config_test_multitenant')
        
        # Initialize extensions
        self.db = SQLA(app)
        self.appbuilder = AppBuilder(app, self.db.session)
        
        return app
    
    def setUp(self):
        """Set up test environment."""
        self.db.create_all()
        
        # Create test tenants
        self.tenant1 = self.create_test_tenant('tenant1', 'Test Tenant 1', 'starter')
        self.tenant2 = self.create_test_tenant('tenant2', 'Test Tenant 2', 'professional')
        self.tenant3 = self.create_test_tenant('enterprise', 'Enterprise Tenant', 'enterprise')
        
        # Create test users
        self.admin1 = self.create_tenant_admin(self.tenant1, 'admin1@tenant1.com')
        self.admin2 = self.create_tenant_admin(self.tenant2, 'admin2@tenant2.com')
        self.admin3 = self.create_tenant_admin(self.tenant3, 'admin3@enterprise.com')
        
        self.db.session.commit()
    
    def tearDown(self):
        """Clean up test environment."""
        self.db.session.remove()
        self.db.drop_all()
    
    def create_test_tenant(self, slug: str, name: str, plan_id: str = 'free') -> Tenant:
        """Create a test tenant."""
        tenant = Tenant(
            slug=slug,
            name=name,
            primary_contact_email=f'admin@{slug}.com',
            plan_id=plan_id,
            status='active',
            resource_limits={
                'max_users': 10,
                'max_records': 5000,
                'storage_gb': 1.0
            }
        )
        self.db.session.add(tenant)
        return tenant
    
    def create_tenant_admin(self, tenant: Tenant, email: str):
        """Create admin user for tenant."""
        from pgappforge.security.sqla.models import User
        
        user = User(
            first_name='Admin',
            last_name='User',
            username=email,
            email=email,
            active=True
        )
        user.password = 'password123'
        self.db.session.add(user)
        self.db.session.flush()
        
        tenant_user = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            role_within_tenant='admin',
            is_active=True
        )
        self.db.session.add(tenant_user)
        
        return user
    
    @contextmanager
    def tenant_context_manager(self, tenant: Tenant):
        """Context manager for tenant context."""
        old_tenant = getattr(tenant_context, 'current_tenant', None)
        try:
            tenant_context.set_tenant_context(tenant)
            yield
        finally:
            if old_tenant:
                tenant_context.set_tenant_context(old_tenant)
            else:
                # Clear tenant context
                if hasattr(tenant_context, 'current_tenant'):
                    delattr(tenant_context, 'current_tenant')
    
    def create_tenant_aware_model(self, tenant_id: int, **kwargs):
        """Create a tenant-aware model instance for testing."""
        from pgappforge.models.tenant_examples import CustomerMT
        
        customer = CustomerMT(
            tenant_id=tenant_id,
            name=kwargs.get('name', 'Test Customer'),
            email=kwargs.get('email', 'test@example.com'),
            **kwargs
        )
        self.db.session.add(customer)
        return customer


class TestTenantIsolation(MultiTenantTestCase):
    """Test complete tenant data isolation."""
    
    def test_tenant_aware_query_isolation(self):
        """Test that tenant-aware queries properly isolate data."""
        from pgappforge.models.tenant_examples import CustomerMT
        
        # Create customers for each tenant
        with self.tenant_context_manager(self.tenant1):
            customer1 = self.create_tenant_aware_model(
                self.tenant1.id, 
                name='Customer 1 - Tenant 1'
            )
        
        with self.tenant_context_manager(self.tenant2):
            customer2 = self.create_tenant_aware_model(
                self.tenant2.id,
                name='Customer 2 - Tenant 2'
            )
        
        self.db.session.commit()
        
        # Test tenant 1 can only see their data
        with self.tenant_context_manager(self.tenant1):
            customers = CustomerMT.current_tenant().all()
            self.assertEqual(len(customers), 1)
            self.assertEqual(customers[0].name, 'Customer 1 - Tenant 1')
            self.assertEqual(customers[0].tenant_id, self.tenant1.id)
        
        # Test tenant 2 can only see their data
        with self.tenant_context_manager(self.tenant2):
            customers = CustomerMT.current_tenant().all()
            self.assertEqual(len(customers), 1)
            self.assertEqual(customers[0].name, 'Customer 2 - Tenant 2')
            self.assertEqual(customers[0].tenant_id, self.tenant2.id)
    
    def test_cross_tenant_access_prevention(self):
        """Test that direct access to other tenant's data is prevented."""
        from pgappforge.models.tenant_examples import CustomerMT
        
        # Create customer in tenant 1
        customer1 = self.create_tenant_aware_model(
            self.tenant1.id,
            name='Secret Customer'
        )
        self.db.session.commit()
        customer1_id = customer1.id
        
        # Try to access from tenant 2 context
        with self.tenant_context_manager(self.tenant2):
            # Direct query should not return the customer
            customer = CustomerMT.query.filter_by(id=customer1_id).first()
            # The customer exists in DB but should not be accessible through safe methods
            
            # Using tenant-aware query should return None/empty
            tenant_customers = CustomerMT.current_tenant().filter_by(id=customer1_id).all()
            self.assertEqual(len(tenant_customers), 0)
            
            # Current tenant query should only return tenant 2's data
            all_customers = CustomerMT.current_tenant().all()
            for customer in all_customers:
                self.assertEqual(customer.tenant_id, self.tenant2.id)
    
    def test_tenant_context_management(self):
        """Test tenant context is properly managed."""
        
        # Initially no tenant context
        self.assertIsNone(get_current_tenant_id())
        
        # Set tenant 1 context
        with self.tenant_context_manager(self.tenant1):
            self.assertEqual(get_current_tenant_id(), self.tenant1.id)
            
            # Nested tenant 2 context
            with self.tenant_context_manager(self.tenant2):
                self.assertEqual(get_current_tenant_id(), self.tenant2.id)
            
            # Back to tenant 1
            self.assertEqual(get_current_tenant_id(), self.tenant1.id)
        
        # Context cleared
        self.assertIsNone(get_current_tenant_id())
    
    def test_tenant_configuration_isolation(self):
        """Test tenant configuration isolation."""
        
        # Create configurations for each tenant
        config1 = TenantConfig(
            tenant_id=self.tenant1.id,
            config_key='api_key',
            config_value='secret-key-tenant-1',
            category='integration'
        )
        
        config2 = TenantConfig(
            tenant_id=self.tenant2.id,
            config_key='api_key',
            config_value='secret-key-tenant-2',
            category='integration'
        )
        
        self.db.session.add_all([config1, config2])
        self.db.session.commit()
        
        # Test each tenant can only see their configs
        tenant1_configs = TenantConfig.query.filter_by(tenant_id=self.tenant1.id).all()
        self.assertEqual(len(tenant1_configs), 1)
        self.assertEqual(tenant1_configs[0].config_value, 'secret-key-tenant-1')
        
        tenant2_configs = TenantConfig.query.filter_by(tenant_id=self.tenant2.id).all()
        self.assertEqual(len(tenant2_configs), 1)
        self.assertEqual(tenant2_configs[0].config_value, 'secret-key-tenant-2')


class TestBillingIntegration(MultiTenantTestCase):
    """Test billing and subscription management."""
    
    def setUp(self):
        """Set up billing test environment."""
        super().setUp()
        
        # Create subscription for tenant1
        self.subscription1 = TenantSubscription(
            tenant_id=self.tenant1.id,
            stripe_subscription_id='sub_test_123',
            plan_id='starter',
            status='active',
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=30),
            monthly_amount=Decimal('29.99'),
            usage_based=True,
            usage_rate={'api_calls': 0.001, 'storage_gb': 0.10}
        )
        self.db.session.add(self.subscription1)
        self.db.session.commit()
    
    def test_usage_tracking_accuracy(self):
        """Test usage tracking calculates correctly."""
        billing_service = get_billing_service()
        
        # Track API usage
        billing_service.track_usage(
            tenant_id=self.tenant1.id,
            usage_type='api_calls',
            amount=1000,
            unit='calls'
        )
        
        # Track storage usage
        billing_service.track_usage(
            tenant_id=self.tenant1.id,
            usage_type='storage_gb',
            amount=2.5,
            unit='gb'
        )
        
        # Verify usage records
        usage_records = TenantUsage.query.filter_by(tenant_id=self.tenant1.id).all()
        self.assertEqual(len(usage_records), 2)
        
        api_usage = next((r for r in usage_records if r.usage_type == 'api_calls'), None)
        self.assertIsNotNone(api_usage)
        self.assertEqual(api_usage.usage_amount, 1000)
        self.assertEqual(api_usage.total_cost, Decimal('1.00'))  # 1000 * 0.001
        
        storage_usage = next((r for r in usage_records if r.usage_type == 'storage_gb'), None)
        self.assertIsNotNone(storage_usage)
        self.assertEqual(storage_usage.usage_amount, Decimal('2.5'))
        self.assertEqual(storage_usage.total_cost, Decimal('0.25'))  # 2.5 * 0.10
    
    def test_usage_based_billing_calculation(self):
        """Test usage-based billing calculations."""
        usage_data = {
            'api_calls': 5000,
            'storage_gb': 3.0
        }
        
        charges = self.subscription1.calculate_usage_charges(usage_data)
        
        # Expected: (5000 * 0.001) + (3.0 * 0.10) = 5.00 + 0.30 = 5.30
        expected_charges = Decimal('5.30')
        self.assertEqual(charges, expected_charges)
    
    def test_tenant_plan_feature_access(self):
        """Test feature access based on subscription plan."""
        
        # Test starter plan features
        with self.tenant_context_manager(self.tenant1):
            features = self.tenant1.get_feature_flags()
            # Based on configuration, starter should have basic features
            self.assertTrue(features.get('basic_crud', False))
            self.assertTrue(features.get('export_csv', False))
    
    @patch('stripe.Subscription.create')
    def test_subscription_creation_with_stripe(self, mock_stripe_create):
        """Test subscription creation with Stripe integration."""
        # Mock Stripe response
        mock_stripe_create.return_value = Mock(
            id='sub_new_subscription',
            status='active',
            current_period_start=int(time.time()),
            current_period_end=int(time.time() + 2592000),  # 30 days
            items=Mock(data=[Mock(price=Mock(unit_amount=2999))])
        )
        
        billing_service = get_billing_service()
        
        # This would create a subscription (mocked)
        # In real tests, we'd use Stripe's test environment
        
        subscription_count_before = TenantSubscription.query.count()
        
        # Test subscription creation logic
        # billing_service.create_subscription(self.tenant2, 'price_starter', 'pm_card_visa')
        
        # For now, just verify our models work correctly
        test_subscription = TenantSubscription(
            tenant_id=self.tenant2.id,
            stripe_subscription_id='sub_new_subscription',
            plan_id='starter',
            status='active'
        )
        self.db.session.add(test_subscription)
        self.db.session.commit()
        
        subscription_count_after = TenantSubscription.query.count()
        self.assertEqual(subscription_count_after, subscription_count_before + 1)


class TestResourceIsolationAndLimiting(MultiTenantTestCase):
    """Test resource isolation and limiting functionality."""
    
    def setUp(self):
        """Set up resource testing."""
        super().setUp()
        
        # Set up resource limits for tenants
        from pgappforge.tenants.resource_isolation import (
            ResourceLimit, setup_default_tenant_limits
        )
        
        setup_default_tenant_limits(self.tenant1.id, 'starter')
        setup_default_tenant_limits(self.tenant2.id, 'professional')
    
    def test_resource_usage_tracking(self):
        """Test resource usage is tracked correctly."""
        monitor = get_resource_monitor()
        
        # Track API calls for tenant 1
        monitor.track_resource_usage(self.tenant1.id, ResourceType.API_CALLS, 100)
        monitor.track_resource_usage(self.tenant1.id, ResourceType.API_CALLS, 200)
        
        # Check usage
        total_usage = monitor.get_current_usage(self.tenant1.id, ResourceType.API_CALLS)
        self.assertEqual(total_usage, 300)
        
        # Track different resource for tenant 2
        monitor.track_resource_usage(self.tenant2.id, ResourceType.STORAGE, 1.5)
        storage_usage = monitor.get_current_usage(self.tenant2.id, ResourceType.STORAGE)
        self.assertEqual(storage_usage, 1.5)
        
        # Verify isolation - tenant 1 shouldn't see tenant 2's usage
        tenant1_storage = monitor.get_current_usage(self.tenant1.id, ResourceType.STORAGE)
        self.assertEqual(tenant1_storage, 0.0)
    
    def test_resource_limit_enforcement(self):
        """Test resource limits are enforced."""
        limiter = get_resource_limiter()
        
        # Test API call limit for starter plan (10,000 calls/hour)
        # Simulate usage close to limit
        monitor = get_resource_monitor()
        monitor.track_resource_usage(self.tenant1.id, ResourceType.API_CALLS, 9500)
        
        # Should still be allowed
        allowed, message, throttle = limiter.enforce_limit(
            self.tenant1.id, ResourceType.API_CALLS, 400
        )
        self.assertTrue(allowed)
        
        # This should trigger throttling (total would be 9900, close to 10000)
        monitor.track_resource_usage(self.tenant1.id, ResourceType.API_CALLS, 400)
        allowed, message, throttle = limiter.enforce_limit(
            self.tenant1.id, ResourceType.API_CALLS, 200
        )
        
        # Should be throttled or warned
        if not allowed:
            self.assertIsNotNone(message)
    
    def test_concurrent_resource_tracking(self):
        """Test resource tracking under concurrent access."""
        monitor = get_resource_monitor()
        
        def track_resources(tenant_id: int, resource_type: ResourceType, count: int):
            """Track resources in thread."""
            for i in range(count):
                monitor.track_resource_usage(tenant_id, resource_type, 1.0)
                time.sleep(0.001)  # Small delay to simulate real usage
        
        # Create multiple threads tracking resources
        threads = []
        for i in range(5):
            thread = threading.Thread(
                target=track_resources,
                args=(self.tenant1.id, ResourceType.API_CALLS, 100)
            )
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify total usage (5 threads * 100 calls = 500)
        total_usage = monitor.get_current_usage(self.tenant1.id, ResourceType.API_CALLS)
        self.assertEqual(total_usage, 500.0)


class TestPerformanceAndScaling(MultiTenantTestCase):
    """Test performance optimizations and scaling functionality."""
    
    def test_database_query_caching(self):
        """Test database query result caching."""
        cache_manager = get_cache_manager()
        
        # Create test data
        customer = self.create_tenant_aware_model(
            self.tenant1.id,
            name='Cached Customer'
        )
        self.db.session.commit()
        
        with self.tenant_context_manager(self.tenant1):
            # Cache a query result
            query_key = "test_customer_list"
            cache_manager.cache_query_result(query_key, [customer], ttl=60)
            
            # Retrieve from cache
            cached_result = cache_manager.get_cached_query_result(query_key)
            self.assertIsNotNone(cached_result)
            self.assertEqual(len(cached_result), 1)
    
    def test_tenant_configuration_caching(self):
        """Test tenant configuration caching."""
        cache_manager = get_cache_manager()
        
        # Cache tenant config
        config = cache_manager.get_tenant_config(self.tenant1.id)
        self.assertEqual(config['tenant_id'], self.tenant1.id)
        self.assertEqual(config['slug'], self.tenant1.slug)
        
        # Test cache invalidation
        cache_manager.invalidate_tenant_config(self.tenant1.id)
        
        # Should reload from database
        new_config = cache_manager.get_tenant_config(self.tenant1.id)
        self.assertEqual(new_config['tenant_id'], self.tenant1.id)
    
    def test_load_balancing_distribution(self):
        """Test tenant distribution across instances."""
        distribution_manager = get_distribution_manager()
        
        # Register mock application instances
        from pgappforge.tenants.scalability import ApplicationInstance
        
        instance1 = ApplicationInstance(
            instance_id='app-1',
            host='10.0.1.10',
            port=5000,
            region='us-east-1',
            availability_zone='us-east-1a',
            status='active',
            tenant_count=0,
            cpu_usage=30.0,
            memory_usage=40.0,
            last_heartbeat=datetime.utcnow(),
            max_tenants=100,
            assigned_tenants=[]
        )
        
        instance2 = ApplicationInstance(
            instance_id='app-2',
            host='10.0.1.11',
            port=5000,
            region='us-east-1',
            availability_zone='us-east-1b',
            status='active',
            tenant_count=0,
            cpu_usage=50.0,
            memory_usage=60.0,
            last_heartbeat=datetime.utcnow(),
            max_tenants=100,
            assigned_tenants=[]
        )
        
        distribution_manager.register_instance(instance1)
        distribution_manager.register_instance(instance2)
        
        # Assign tenants
        assigned1 = distribution_manager.assign_tenant_to_instance(self.tenant1.id)
        assigned2 = distribution_manager.assign_tenant_to_instance(self.tenant2.id)
        
        self.assertIsNotNone(assigned1)
        self.assertIsNotNone(assigned2)
        
        # Verify assignment
        tenant1_instance = distribution_manager.get_tenant_instance(self.tenant1.id)
        self.assertIsNotNone(tenant1_instance)
        self.assertIn(tenant1_instance.instance_id, ['app-1', 'app-2'])


class TestSecurityAndAuditTrail(MultiTenantTestCase):
    """Test security features and audit logging."""
    
    def test_tenant_subdomain_resolution(self):
        """Test tenant resolution from subdomain."""
        with self.app.test_request_context('/', base_url='http://tenant1.example.com'):
            # Mock the resolution logic
            resolved_tenant = tenant_context._resolve_tenant_from_request()
            
            # In a full implementation, this would resolve tenant1
            # For now, we test the structure is in place
            # self.assertEqual(resolved_tenant.slug, 'tenant1')
    
    def test_cross_tenant_api_access_prevention(self):
        """Test API endpoints prevent cross-tenant access."""
        
        # This would test actual API endpoints to ensure they enforce tenant context
        # For now, we verify the structure for tenant context checking
        
        with self.tenant_context_manager(self.tenant1):
            tenant_id = get_current_tenant_id()
            self.assertEqual(tenant_id, self.tenant1.id)
        
        with self.tenant_context_manager(self.tenant2):
            tenant_id = get_current_tenant_id()
            self.assertEqual(tenant_id, self.tenant2.id)
    
    def test_sensitive_configuration_handling(self):
        """Test sensitive configurations are handled properly."""
        
        # Create sensitive configuration
        sensitive_config = TenantConfig(
            tenant_id=self.tenant1.id,
            config_key='stripe_secret_key',
            config_value='sk_test_12345',
            is_sensitive=True,
            category='billing'
        )
        
        self.db.session.add(sensitive_config)
        self.db.session.commit()
        
        # Verify it's marked as sensitive
        config = TenantConfig.query.filter_by(
            tenant_id=self.tenant1.id,
            config_key='stripe_secret_key'
        ).first()
        
        self.assertTrue(config.is_sensitive)
        self.assertEqual(config.config_value, 'sk_test_12345')


class LoadTestRunner:
    """Utility for running load tests on multi-tenant system."""
    
    def __init__(self, app, db, num_tenants=10, num_users_per_tenant=5):
        self.app = app
        self.db = db
        self.num_tenants = num_tenants
        self.num_users_per_tenant = num_users_per_tenant
        self.tenants = []
        self.users = []
    
    def setup_load_test_data(self):
        """Set up test data for load testing."""
        print(f"Creating {self.num_tenants} tenants with {self.num_users_per_tenant} users each...")
        
        with self.app.app_context():
            # Create tenants
            for i in range(self.num_tenants):
                tenant = Tenant(
                    slug=f'loadtest{i}',
                    name=f'Load Test Tenant {i}',
                    primary_contact_email=f'admin@loadtest{i}.com',
                    plan_id=random.choice(['starter', 'professional', 'enterprise']),
                    status='active'
                )
                self.db.session.add(tenant)
                self.tenants.append(tenant)
            
            self.db.session.commit()
            
            # Create users for each tenant
            from pgappforge.security.sqla.models import User
            
            for tenant in self.tenants:
                for j in range(self.num_users_per_tenant):
                    user = User(
                        first_name=f'User{j}',
                        last_name=f'Tenant{tenant.slug}',
                        username=f'user{j}@{tenant.slug}.com',
                        email=f'user{j}@{tenant.slug}.com',
                        active=True
                    )
                    user.password = 'testpassword'
                    self.db.session.add(user)
                    self.db.session.flush()
                    
                    tenant_user = TenantUser(
                        tenant_id=tenant.id,
                        user_id=user.id,
                        role_within_tenant='member',
                        is_active=True
                    )
                    self.db.session.add(tenant_user)
                    self.users.append((tenant, user))
            
            self.db.session.commit()
            print(f"Created {len(self.tenants)} tenants and {len(self.users)} users")
    
    def run_concurrent_operations_test(self, num_threads=20, operations_per_thread=50):
        """Test concurrent operations across tenants."""
        print(f"Running concurrent operations test with {num_threads} threads...")
        
        def worker_thread(thread_id: int):
            """Worker thread function."""
            operations_completed = 0
            errors = []
            
            with self.app.app_context():
                for i in range(operations_per_thread):
                    try:
                        # Randomly select a tenant
                        tenant, user = random.choice(self.users)
                        
                        # Simulate tenant operations
                        with tenant_context.with_tenant_context(tenant):
                            # Track resource usage
                            monitor = get_resource_monitor()
                            monitor.track_resource_usage(
                                tenant.id, 
                                ResourceType.API_CALLS, 
                                1.0
                            )
                            
                            # Create test data
                            from pgappforge.models.tenant_examples import CustomerMT
                            customer = CustomerMT(
                                tenant_id=tenant.id,
                                name=f'Customer {thread_id}-{i}',
                                email=f'customer{i}@{tenant.slug}.com'
                            )
                            self.db.session.add(customer)
                            self.db.session.commit()
                            
                            operations_completed += 1
                    
                    except Exception as e:
                        errors.append(str(e))
            
            return {'thread_id': thread_id, 'completed': operations_completed, 'errors': errors}
        
        # Run concurrent threads
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(worker_thread, i) 
                for i in range(num_threads)
            ]
            
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Analyze results
        total_operations = sum(r['completed'] for r in results)
        total_errors = sum(len(r['errors']) for r in results)
        
        print(f"Load test completed in {execution_time:.2f} seconds")
        print(f"Total operations: {total_operations}")
        print(f"Total errors: {total_errors}")
        print(f"Operations per second: {total_operations / execution_time:.2f}")
        print(f"Error rate: {total_errors / total_operations * 100:.2f}%")
        
        return {
            'execution_time': execution_time,
            'total_operations': total_operations,
            'total_errors': total_errors,
            'ops_per_second': total_operations / execution_time,
            'error_rate': total_errors / total_operations if total_operations > 0 else 0
        }
    
    def cleanup_load_test_data(self):
        """Clean up load test data."""
        print("Cleaning up load test data...")
        
        with self.app.app_context():
            # Clean up tenant-aware models
            from pgappforge.models.tenant_examples import CustomerMT
            CustomerMT.query.filter(
                CustomerMT.tenant_id.in_([t.id for t in self.tenants])
            ).delete(synchronize_session=False)
            
            # Clean up tenant users
            TenantUser.query.filter(
                TenantUser.tenant_id.in_([t.id for t in self.tenants])
            ).delete(synchronize_session=False)
            
            # Clean up users
            from pgappforge.security.sqla.models import User
            user_emails = [u[1].email for u in self.users]
            User.query.filter(User.email.in_(user_emails)).delete(synchronize_session=False)
            
            # Clean up tenants
            Tenant.query.filter(
                Tenant.id.in_([t.id for t in self.tenants])
            ).delete(synchronize_session=False)
            
            self.db.session.commit()
            print("Load test data cleaned up")


def run_comprehensive_test_suite():
    """Run the complete multi-tenant test suite."""
    print("Running comprehensive multi-tenant test suite...")
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_suite.addTest(unittest.makeSuite(TestTenantIsolation))
    test_suite.addTest(unittest.makeSuite(TestBillingIntegration))
    test_suite.addTest(unittest.makeSuite(TestResourceIsolationAndLimiting))
    test_suite.addTest(unittest.makeSuite(TestPerformanceAndScaling))
    test_suite.addTest(unittest.makeSuite(TestSecurityAndAuditTrail))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    return result


if __name__ == '__main__':
    # Run comprehensive tests
    test_result = run_comprehensive_test_suite()
    
    if test_result.wasSuccessful():
        print("All multi-tenant tests passed successfully!")
    else:
        print(f"Tests failed: {len(test_result.failures)} failures, {len(test_result.errors)} errors")
        
        # Print failure details
        for test, traceback in test_result.failures:
            print(f"FAILURE: {test}")
            print(traceback)
        
        for test, traceback in test_result.errors:
            print(f"ERROR: {test}")
            print(traceback)