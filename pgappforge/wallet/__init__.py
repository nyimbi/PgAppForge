"""
User Wallet System for PgForge

This package provides a comprehensive wallet system for tracking user expenditure
and income, with support for multiple currencies, transaction history, budgeting,
financial analytics, and MPESA mobile money integration.

Features:
- Multi-currency wallet support
- Transaction tracking and categorization
- Budget management and alerts
- Financial analytics and reporting
- Payment method integration
- MPESA mobile money integration (STK Push, callbacks, verification)
- Cryptocurrency wallet linking and verification
- Subscription and recurring payment management
- Expense approval workflows
- Financial audit trails
- Real-time balance calculations
- Comprehensive statements and reporting
- Import/export functionality

Components:
- Models: Wallet, Transaction, Budget, PaymentMethod, MPESA models, etc.
- Views: Wallet management, transaction history, budget dashboard, MPESA admin
- Services: Payment processing, MPESA API integration, currency conversion, analytics
- API: RESTful endpoints for wallet operations, MPESA transactions, statements
- Widgets: Financial input widgets, charts, dashboards
"""

from .models import *
from .views import *
from .services import *
from .widgets import *

# MPESA integration (with graceful fallback)
try:
    from .mpesa_models import *
    from .mpesa_service import get_mpesa_service
    from .mpesa_registration import init_mpesa_integration, check_mpesa_integration_status
    MPESA_INTEGRATION_AVAILABLE = True
except ImportError:
    MPESA_INTEGRATION_AVAILABLE = False
    def init_mpesa_integration(appbuilder):
        return {'views_registered': False, 'api_registered': False, 'errors': ['MPESA integration not available']}
    def check_mpesa_integration_status():
        return {'models_available': False, 'service_available': False, 'views_available': False, 'errors': ['MPESA integration not available']}

__version__ = '1.0.0'
__all__ = [
    # Core Models
    'UserWallet',
    'WalletTransaction', 
    'WalletBudget',
    'PaymentMethod',
    'TransactionCategory',
    'RecurringTransaction',
    'WalletAudit',
    
    # MPESA Models (if available)
    'MPESAAccount',
    'MPESATransaction', 
    'MPESAConfiguration',
    'MPESACallback',
    
    # Views
    'WalletDashboardView',
    'TransactionView',
    'BudgetView', 
    'PaymentMethodView',
    'WalletAnalyticsView',
    'WalletReportsView',
    
    # MPESA Views (if available)
    'MPESAAccountModelView',
    'MPESATransactionModelView',
    'MPESAConfigurationModelView',
    'MPESACallbackModelView',
    
    # Services
    'WalletService',
    'TransactionService',
    'BudgetService',
    'CurrencyService',
    'AnalyticsService',
    
    # MPESA Services (if available)
    'get_mpesa_service',
    
    # Widgets
    'CurrencyInputWidget',
    'TransactionFormWidget',
    'BudgetProgressWidget',
    'WalletBalanceWidget',
    'ExpenseChartWidget',
    
    # Integration Functions
    'init_mpesa_integration',
    'check_mpesa_integration_status',
    'MPESA_INTEGRATION_AVAILABLE'
]