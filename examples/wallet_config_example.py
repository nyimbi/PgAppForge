"""
Example PgAppForge configuration with Wallet Integration

This example shows how to enable cryptocurrency wallet integration
in your PgAppForge application.
"""

import os
from flask import Flask
from pgappforge import AppBuilder, SQLA

# PgAppForge configuration
APP_NAME = "PgAppForge with Wallet Integration"
APP_ICON = "static/img/logo.jpg"

# Database configuration
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Security configuration
SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here-change-in-production'
AUTH_TYPE = 1  # Database authentication
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'

# Enable wallet integration
ADDON_MANAGERS = [
    'pgappforge.security.wallet.WalletManager'
]

# Wallet-specific configuration (optional)
WALLET_CONFIG = {
    'supported_types': ['metamask', 'coinbase', 'walletconnect', 'trust', 'other'],
    'require_verification': True,
    'auto_verify_signatures': False,  # Set to True for automatic verification (less secure)
    'allowed_networks': ['mainnet', 'rinkeby', 'polygon', 'bsc'],  # Ethereum networks
    'metadata_max_size': 1024,  # Maximum metadata size in bytes
}

# Optional: Custom wallet validation
def validate_wallet_address(address):
    """Custom wallet address validation function"""
    # Add your custom validation logic here
    return True

# Optional: Custom wallet verification 
def verify_wallet_signature(address, message, signature):
    """Custom wallet signature verification"""
    # Add your custom signature verification logic here
    # Return True if verification passes, False otherwise
    return True


# Example application factory
def create_app():
    """Application factory with wallet integration"""
    app = Flask(__name__)
    app.config.from_object(__name__)
    
    # Initialize PgAppForge
    db = SQLA(app)
    appbuilder = AppBuilder(app, db.session)
    
    # The WalletManager is automatically loaded via ADDON_MANAGERS
    # and will register the wallet API endpoints and management views
    
    return app


if __name__ == '__main__':
    app = create_app()
    
    # Run the development server
    app.run(
        host='0.0.0.0',
        port=8080,
        debug=True
    )