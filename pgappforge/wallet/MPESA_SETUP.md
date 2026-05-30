# MPESA Integration Setup Guide

This guide explains how to set up and configure MPESA integration with Flask-AppBuilder.

## Quick Setup

### 1. Initialize MPESA Integration

In your Flask-AppBuilder app initialization:

```python
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA
from flask_appbuilder.wallet import init_mpesa_integration, check_mpesa_integration_status

app = Flask(__name__)
app.config.from_object("config")
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Initialize MPESA integration
mpesa_status = init_mpesa_integration(appbuilder)

if mpesa_status['views_registered'] and mpesa_status['api_registered']:
    print("✅ MPESA integration initialized successfully")
else:
    print("⚠️ MPESA integration partially initialized")
    for error in mpesa_status['errors']:
        print(f"❌ {error}")
```

### 2. Check Integration Status

```python
from flask_appbuilder.wallet import check_mpesa_integration_status

# Check current status
status = check_mpesa_integration_status()
print(f"Models available: {status['models_available']}")
print(f"Service available: {status['service_available']}")
print(f"Views available: {status['views_available']}")
print(f"Dependencies installed: {status['dependencies_installed']}")

if status['errors']:
    print("Errors:")
    for error in status['errors']:
        print(f"  - {error}")
```

## Manual View Registration

If you need more control over view registration:

```python
from flask_appbuilder.wallet.mpesa_registration import register_mpesa_views, register_mpesa_api

# Register just the admin views
views_ok = register_mpesa_views(appbuilder)

# Register just the API endpoints  
api_ok = register_mpesa_api(appbuilder)
```

## Configuration

### MPESA API Configuration

Configure your MPESA settings in your Flask app config:

```python
# config.py
class Config:
    # ... other config settings ...
    
    # MPESA Configuration (for production)
    MPESA_ENVIRONMENT = 'production'  # or 'sandbox'
    MPESA_CONSUMER_KEY = 'your_consumer_key'
    MPESA_CONSUMER_SECRET = 'your_consumer_secret'
    MPESA_BUSINESS_SHORTCODE = '123456'
    MPESA_LIPA_NA_MPESA_SHORTCODE = '654321'
    MPESA_PASSKEY = 'your_passkey'
    MPESA_CALLBACK_URL = 'https://yourapp.com/api/v1/wallet/mpesa/callback'
```

### Database Setup

Create MPESA tables by running migrations:

```python
# In your app initialization
from flask_migrate import Migrate

migrate = Migrate(app, db)

# Then run:
# flask db init
# flask db migrate -m "Add MPESA tables"
# flask db upgrade
```

## Available Admin Views

After successful registration, these views will be available in your admin interface:

1. **MPESA Accounts** (`/mpesa_accounts/`) - Manage user MPESA account links
2. **MPESA Transactions** (`/mpesa_transactions/`) - View transaction history
3. **MPESA Configuration** (`/mpesa_configurations/`) - API configuration management
4. **MPESA Callbacks** (`/mpesa_callbacks/`) - Debug callback logs

## Available API Endpoints

The following REST endpoints will be registered:

### MPESA Operations
- `POST /api/v1/wallet/mpesa/link` - Link MPESA account
- `POST /api/v1/wallet/mpesa/verify` - Verify MPESA account
- `POST /api/v1/wallet/mpesa/pay` - Initiate STK Push payment
- `GET /api/v1/wallet/mpesa/status/<id>` - Get payment status
- `GET /api/v1/wallet/mpesa/accounts` - Get user's MPESA accounts
- `GET /api/v1/wallet/mpesa/transactions` - Get transaction history
- `POST /api/v1/wallet/mpesa/callback` - MPESA callback handler (public)

### Wallet Operations
- `POST /api/v1/wallet/cashout` - Cash out to external system
- `POST /api/v1/wallet/withdraw` - Withdraw funds
- `POST /api/v1/wallet/transfer` - Transfer between wallets
- `GET /api/v1/wallet/statement/<wallet_id>` - Get detailed statement
- `GET /api/v1/wallet/monthly-summary/<wallet_id>` - Get monthly summary

## Dependencies

Required dependencies are automatically installed when you install Flask-AppBuilder with wallet support:

```bash
pip install "flask-appbuilder[wallet]"
```

Or install manually:

```bash
pip install eth-account web3 bitcoinlib eth-hash eth-keys python-mpesa
```

## Troubleshooting

### Common Issues

1. **Views not appearing in menu**
   - Check that `init_mpesa_integration(appbuilder)` is called after AppBuilder initialization
   - Verify that the user has appropriate permissions

2. **API endpoints returning 503**
   - Ensure MPESA dependencies are installed
   - Check that MPESA configuration is properly set

3. **Import errors**
   - Verify that all required dependencies are installed
   - Check that Python path includes Flask-AppBuilder wallet module

### Debug Mode

Enable debug logging to see registration details:

```python
import logging
logging.getLogger('flask_appbuilder.wallet').setLevel(logging.DEBUG)
```

### Status Check

Use the status check function to diagnose issues:

```python
from flask_appbuilder.wallet import check_mpesa_integration_status
status = check_mpesa_integration_status()
print(status)  # Shows detailed status and errors
```

## Security Notes

- Always use HTTPS for production MPESA endpoints
- Store API credentials securely (use environment variables)
- Regularly rotate API credentials
- Monitor callback logs for suspicious activity
- Implement rate limiting on API endpoints
- Use proper authentication for admin views

## Production Checklist

- [ ] HTTPS enabled for all endpoints
- [ ] API credentials configured and secured
- [ ] Database migrations applied
- [ ] Callback URL publicly accessible
- [ ] Rate limiting configured
- [ ] Monitoring and logging set up
- [ ] Backup strategy implemented
- [ ] User permissions configured
- [ ] Testing completed in sandbox environment