"""
Wallet Integration Module for PgAppForge

This module provides cryptocurrency wallet integration capabilities
for PgAppForge applications, including:

- User wallet linking and management
- Wallet verification through signature validation
- RESTful API endpoints for wallet operations
- Admin interface for wallet management

Usage:
    Add to your PgAppForge configuration:
    
    from pgappforge.security.wallet import WalletManager
    
    # In your app factory or configuration
    ADDON_MANAGERS = ['pgappforge.security.wallet.WalletManager']
"""

from pgappforge.base import BaseManager
from .wallet_api import WalletApi, WalletView
import logging

log = logging.getLogger(__name__)


class WalletManager(BaseManager):
    """
    Wallet Integration Manager for PgAppForge.
    
    Registers wallet API endpoints and management views.
    """
    
    def register_views(self):
        """Register wallet management views and API endpoints"""
        try:
            # Register API endpoints
            self.appbuilder.add_api(WalletApi)
            log.info("Registered Wallet API endpoints")
            
            # Register management view
            self.appbuilder.add_view(
                WalletView, 
                "Wallet Management", 
                category="Security",
                icon="fa-wallet"
            )
            log.info("Registered Wallet Management view")
            
        except Exception as e:
            log.error(f"Failed to register wallet views: {str(e)}")
            raise


# Convenience imports
__all__ = ['WalletManager', 'WalletApi', 'WalletView']