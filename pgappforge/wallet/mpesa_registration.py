"""
MPESA View Registration for PgForge

This module handles the registration of MPESA views with PgForge.
It provides utilities to register MPESA admin views and API endpoints.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def register_mpesa_views(appbuilder) -> bool:
    """
    Register MPESA views with PgForge.
    
    Args:
        appbuilder: PgForge instance
        
    Returns:
        bool: True if registration successful, False otherwise
    """
    try:
        # Import MPESA views with graceful fallback
        try:
            from .mpesa_views import (
                MPESAAccountModelView,
                MPESATransactionModelView,
                MPESAConfigurationModelView,
                MPESACallbackModelView
            )
        except ImportError as e:
            log.warning(f"MPESA views not available for registration: {e}")
            return False
        
        # Register MPESA Account management view
        try:
            appbuilder.add_view(
                MPESAAccountModelView,
                "MPESA Accounts",
                icon="fa-mobile-phone",
                category="Wallet",
                category_icon="fa-wallet"
            )
            log.info("Registered MPESA Accounts view")
        except Exception as e:
            log.error(f"Failed to register MPESA Accounts view: {e}")
        
        # Register MPESA Transaction view
        try:
            appbuilder.add_view(
                MPESATransactionModelView,
                "MPESA Transactions",
                icon="fa-exchange-alt",
                category="Wallet"
            )
            log.info("Registered MPESA Transactions view")
        except Exception as e:
            log.error(f"Failed to register MPESA Transactions view: {e}")
        
        # Register MPESA Configuration view
        try:
            appbuilder.add_view(
                MPESAConfigurationModelView,
                "MPESA Configuration",
                icon="fa-cog",
                category="Administration",
                category_icon="fa-cogs"
            )
            log.info("Registered MPESA Configuration view")
        except Exception as e:
            log.error(f"Failed to register MPESA Configuration view: {e}")
        
        # Register MPESA Callback logs view
        try:
            appbuilder.add_view(
                MPESACallbackModelView,
                "MPESA Callbacks",
                icon="fa-phone",
                category="Administration"
            )
            log.info("Registered MPESA Callbacks view")
        except Exception as e:
            log.error(f"Failed to register MPESA Callbacks view: {e}")
        
        return True
        
    except Exception as e:
        log.error(f"Failed to register MPESA views: {e}")
        return False


def register_mpesa_api(appbuilder) -> bool:
    """
    Register MPESA API endpoints with PgForge.
    
    Args:
        appbuilder: PgForge instance
        
    Returns:
        bool: True if registration successful, False otherwise
    """
    try:
        # Import MPESA API with graceful fallback
        try:
            from ..security.wallet.wallet_api import WalletApi
        except ImportError as e:
            log.warning(f"MPESA API not available for registration: {e}")
            return False
        
        # Register MPESA API endpoints (if not already registered)
        try:
            # Check if wallet API is already registered
            existing_apis = [view.__name__ for view in appbuilder.sm.get_all_views()]
            
            if 'WalletApi' not in existing_apis:
                appbuilder.add_api(WalletApi)
                log.info("Registered Wallet/MPESA API endpoints")
            else:
                log.info("Wallet/MPESA API endpoints already registered")
            
        except Exception as e:
            log.error(f"Failed to register MPESA API: {e}")
            return False
        
        return True
        
    except Exception as e:
        log.error(f"Failed to register MPESA API: {e}")
        return False


def init_mpesa_integration(appbuilder) -> dict:
    """
    Initialize complete MPESA integration with PgForge.
    
    This function should be called during app initialization to set up
    all MPESA-related views, APIs, and configurations.
    
    Args:
        appbuilder: PgForge instance
        
    Returns:
        dict: Status of registration attempts
    """
    results = {
        'views_registered': False,
        'api_registered': False,
        'errors': []
    }
    
    try:
        log.info("Initializing MPESA integration with PgForge")
        
        # Register MPESA admin views
        try:
            results['views_registered'] = register_mpesa_views(appbuilder)
            if results['views_registered']:
                log.info("MPESA admin views registered successfully")
            else:
                results['errors'].append("Failed to register MPESA admin views")
                
        except Exception as e:
            error_msg = f"Error registering MPESA views: {e}"
            log.error(error_msg)
            results['errors'].append(error_msg)
        
        # Register MPESA API endpoints
        try:
            results['api_registered'] = register_mpesa_api(appbuilder)
            if results['api_registered']:
                log.info("MPESA API endpoints registered successfully")
            else:
                results['errors'].append("Failed to register MPESA API endpoints")
                
        except Exception as e:
            error_msg = f"Error registering MPESA API: {e}"
            log.error(error_msg)
            results['errors'].append(error_msg)
        
        # Log final status
        if results['views_registered'] and results['api_registered']:
            log.info("MPESA integration initialized successfully")
        elif results['views_registered'] or results['api_registered']:
            log.warning("MPESA integration partially initialized")
        else:
            log.error("MPESA integration failed to initialize")
        
        return results
        
    except Exception as e:
        error_msg = f"Critical error during MPESA integration initialization: {e}"
        log.error(error_msg)
        results['errors'].append(error_msg)
        return results


def check_mpesa_integration_status() -> dict:
    """
    Check the current status of MPESA integration.
    
    Returns:
        dict: Status information about MPESA integration
    """
    status = {
        'models_available': False,
        'service_available': False,
        'views_available': False,
        'dependencies_installed': False,
        'errors': []
    }
    
    # Check if MPESA models are available
    try:
        from .mpesa_models import MPESAAccount, MPESATransaction, MPESAConfiguration
        status['models_available'] = True
    except ImportError as e:
        status['errors'].append(f"MPESA models not available: {e}")
    
    # Check if MPESA service is available
    try:
        from .mpesa_service import get_mpesa_service
        service = get_mpesa_service()
        status['service_available'] = True
    except Exception as e:
        status['errors'].append(f"MPESA service not available: {e}")
    
    # Check if MPESA views are available
    try:
        from .mpesa_views import MPESAAccountModelView
        status['views_available'] = True
    except ImportError as e:
        status['errors'].append(f"MPESA views not available: {e}")
    
    # Check if required dependencies are installed
    try:
        import requests
        from decimal import Decimal
        import base64
        import json
        # Try to import optional MPESA dependencies
        try:
            import eth_account
            import web3
            status['dependencies_installed'] = True
        except ImportError:
            status['errors'].append("Optional crypto dependencies not installed (eth_account, web3)")
            status['dependencies_installed'] = True  # Basic deps are OK
    except ImportError as e:
        status['errors'].append(f"Required dependencies not available: {e}")
    
    return status