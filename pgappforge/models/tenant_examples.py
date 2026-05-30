"""
Multi-Tenant Model Examples.

Example models demonstrating how to convert existing PgAppForge
models to support multi-tenant isolation using TenantAwareMixin.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from .tenant_models import TenantAwareMixin

log = logging.getLogger(__name__)


class CustomerMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of a Customer model.
    
    Demonstrates how to add tenant isolation to existing business models.
    Each tenant sees only their own customers.
    """
    
    __tablename__ = 'ab_customers_mt'
    __table_args__ = (
        # Ensure tenant_id is included in key indexes for performance
        Index('ix_customers_mt_tenant_name', 'tenant_id', 'name'),
        Index('ix_customers_mt_tenant_email', 'tenant_id', 'email'),
        Index('ix_customers_mt_tenant_status', 'tenant_id', 'status'),
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=False)
    phone = Column(String(50))
    address = Column(Text)
    
    # Business fields
    status = Column(String(20), default='active')  # active, inactive, suspended
    customer_type = Column(String(20), default='individual')  # individual, business
    registration_date = Column(DateTime, default=datetime.utcnow)
    
    # Credit limit and billing
    credit_limit = Column(Integer, default=1000)
    outstanding_balance = Column(Integer, default=0)
    
    # Relationships (automatically tenant-isolated)
    orders = relationship("OrderMT", back_populates="customer", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<CustomerMT {self.name} (Tenant: {self.tenant_id})>'
    
    @property
    def is_active(self):
        return self.status == 'active'
    
    def get_order_count(self):
        """Get count of orders for this customer (automatically tenant-filtered)"""
        return len(self.orders)
    
    def get_total_order_value(self):
        """Calculate total value of all orders"""
        return sum(order.total_amount or 0 for order in self.orders)


class OrderMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of an Order model.
    
    Demonstrates foreign key relationships in multi-tenant models.
    Both the order and customer must belong to the same tenant.
    """
    
    __tablename__ = 'ab_orders_mt'
    __table_args__ = (
        Index('ix_orders_mt_tenant_customer', 'tenant_id', 'customer_id'),
        Index('ix_orders_mt_tenant_date', 'tenant_id', 'order_date'),
        Index('ix_orders_mt_tenant_status', 'tenant_id', 'status'),
    )
    
    id = Column(Integer, primary_key=True)
    order_number = Column(String(50), nullable=False)
    customer_id = Column(Integer, ForeignKey('ab_customers_mt.id'), nullable=False)
    
    # Order details
    order_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default='pending')  # pending, confirmed, shipped, delivered, cancelled
    
    # Financial
    subtotal = Column(Integer, default=0)  # Store as cents to avoid decimal issues
    tax_amount = Column(Integer, default=0)
    shipping_cost = Column(Integer, default=0)
    discount_amount = Column(Integer, default=0)
    total_amount = Column(Integer, default=0)
    
    # Shipping
    shipping_address = Column(Text)
    tracking_number = Column(String(100))
    estimated_delivery = Column(DateTime)
    
    # Relationships
    customer = relationship("CustomerMT", back_populates="orders")
    items = relationship("OrderItemMT", back_populates="order", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<OrderMT {self.order_number} (Tenant: {self.tenant_id})>'
    
    @property
    def total_amount_dollars(self):
        """Convert cents to dollars for display"""
        return (self.total_amount or 0) / 100
    
    def calculate_total(self):
        """Recalculate order total from components"""
        self.total_amount = (
            (self.subtotal or 0) + 
            (self.tax_amount or 0) + 
            (self.shipping_cost or 0) - 
            (self.discount_amount or 0)
        )
        return self.total_amount
    
    def get_item_count(self):
        """Get total number of items in order"""
        return sum(item.quantity for item in self.items)


class ProductMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of a Product model.
    
    Demonstrates how product catalogs can be tenant-specific,
    allowing each tenant to have their own products and pricing.
    """
    
    __tablename__ = 'ab_products_mt'
    __table_args__ = (
        Index('ix_products_mt_tenant_sku', 'tenant_id', 'sku'),
        Index('ix_products_mt_tenant_category', 'tenant_id', 'category'),
        Index('ix_products_mt_tenant_active', 'tenant_id', 'is_active'),
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    sku = Column(String(50), nullable=False)
    description = Column(Text)
    
    # Product classification
    category = Column(String(50))
    brand = Column(String(100))
    
    # Pricing (stored as cents)
    unit_price = Column(Integer, nullable=False)
    cost_price = Column(Integer)
    
    # Inventory
    stock_quantity = Column(Integer, default=0)
    minimum_stock = Column(Integer, default=0)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    
    # Relationships
    order_items = relationship("OrderItemMT", back_populates="product")
    
    def __repr__(self):
        return f'<ProductMT {self.name} ({self.sku}) (Tenant: {self.tenant_id})>'
    
    @property
    def unit_price_dollars(self):
        """Convert cents to dollars for display"""
        return (self.unit_price or 0) / 100
    
    @property
    def is_in_stock(self):
        """Check if product is in stock"""
        return self.stock_quantity > 0
    
    @property
    def is_low_stock(self):
        """Check if product is below minimum stock level"""
        return self.stock_quantity <= self.minimum_stock
    
    def adjust_stock(self, quantity_change: int, reason: str = None):
        """Adjust stock quantity and log the change"""
        old_quantity = self.stock_quantity
        self.stock_quantity = max(0, self.stock_quantity + quantity_change)
        
        log.info(f"Stock adjusted for {self.sku} (Tenant {self.tenant_id}): "
                f"{old_quantity} -> {self.stock_quantity}. Reason: {reason}")


class OrderItemMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of an OrderItem model.
    
    Demonstrates how junction/association models work in multi-tenant setup.
    The order item must belong to the same tenant as its order and product.
    """
    
    __tablename__ = 'ab_order_items_mt'
    __table_args__ = (
        Index('ix_order_items_mt_tenant_order', 'tenant_id', 'order_id'),
        Index('ix_order_items_mt_tenant_product', 'tenant_id', 'product_id'),
    )
    
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('ab_orders_mt.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('ab_products_mt.id'), nullable=False)
    
    # Item details
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Integer, nullable=False)  # Price at time of order (cents)
    discount_per_item = Column(Integer, default=0)
    
    # Relationships
    order = relationship("OrderMT", back_populates="items")
    product = relationship("ProductMT", back_populates="order_items")
    
    def __repr__(self):
        return f'<OrderItemMT Order:{self.order_id} Product:{self.product_id} (Tenant: {self.tenant_id})>'
    
    @property
    def line_total(self):
        """Calculate total for this line item"""
        return (self.unit_price * self.quantity) - (self.discount_per_item * self.quantity)
    
    @property
    def unit_price_dollars(self):
        """Convert cents to dollars for display"""
        return (self.unit_price or 0) / 100


class ProjectMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of a Project model.
    
    Demonstrates a more complex business model with hierarchical relationships
    and tenant-specific workflows.
    """
    
    __tablename__ = 'ab_projects_mt'
    __table_args__ = (
        Index('ix_projects_mt_tenant_status', 'tenant_id', 'status'),
        Index('ix_projects_mt_tenant_manager', 'tenant_id', 'project_manager_id'),
        Index('ix_projects_mt_tenant_dates', 'tenant_id', 'start_date', 'end_date'),
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    
    # Project timeline
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    estimated_completion = Column(DateTime)
    
    # Project details
    status = Column(String(20), default='planning')  # planning, active, on_hold, completed, cancelled
    priority = Column(String(10), default='medium')  # low, medium, high, critical
    budget = Column(Integer)  # Budget in cents
    
    # Relationships (within tenant)
    project_manager_id = Column(Integer)  # Would FK to tenant user table
    customer_id = Column(Integer, ForeignKey('ab_customers_mt.id'))
    
    # Relationships
    customer = relationship("CustomerMT")
    tasks = relationship("TaskMT", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<ProjectMT {self.name} (Tenant: {self.tenant_id})>'
    
    @property
    def budget_dollars(self):
        """Convert cents to dollars for display"""
        return (self.budget or 0) / 100
    
    @property
    def is_active(self):
        """Check if project is currently active"""
        return self.status == 'active'
    
    @property
    def is_overdue(self):
        """Check if project is past its end date"""
        if not self.end_date:
            return False
        return datetime.now(tz=timezone.utc) > self.end_date and self.status not in ('completed', 'cancelled')
    
    def get_completion_percentage(self):
        """Calculate project completion based on completed tasks"""
        if not self.tasks:
            return 0
        
        completed_tasks = [task for task in self.tasks if task.status == 'completed']
        return int((len(completed_tasks) / len(self.tasks)) * 100)


class TaskMT(TenantAwareMixin, AuditMixin, Model):
    """
    Multi-tenant version of a Task model.
    
    Demonstrates sub-entities that belong to parent entities within the same tenant.
    """
    
    __tablename__ = 'ab_tasks_mt'
    __table_args__ = (
        Index('ix_tasks_mt_tenant_project', 'tenant_id', 'project_id'),
        Index('ix_tasks_mt_tenant_status', 'tenant_id', 'status'),
        Index('ix_tasks_mt_tenant_assignee', 'tenant_id', 'assigned_to_id'),
    )
    
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('ab_projects_mt.id'), nullable=False)
    
    title = Column(String(200), nullable=False)
    description = Column(Text)
    
    # Task details
    status = Column(String(20), default='todo')  # todo, in_progress, review, completed, cancelled
    priority = Column(String(10), default='medium')
    
    # Scheduling
    due_date = Column(DateTime)
    estimated_hours = Column(Integer)
    actual_hours = Column(Integer)
    
    # Assignment (would reference tenant user)
    assigned_to_id = Column(Integer)  # Would FK to tenant user table
    
    # Relationships
    project = relationship("ProjectMT", back_populates="tasks")
    
    def __repr__(self):
        return f'<TaskMT {self.title} (Project: {self.project_id}, Tenant: {self.tenant_id})>'
    
    @property
    def is_completed(self):
        """Check if task is completed"""
        return self.status == 'completed'
    
    @property
    def is_overdue(self):
        """Check if task is past its due date"""
        if not self.due_date:
            return False
        return datetime.now(tz=timezone.utc) > self.due_date and not self.is_completed