# Wallet Integration for PgAppForge

This document describes the cryptocurrency wallet integration feature added to PgAppForge, enabling Web3 functionality and blockchain wallet management.

## Overview

The wallet integration module provides:

- **User Wallet Linking**: Connect cryptocurrency wallets to user accounts
- **Wallet Verification**: Verify wallet ownership through cryptographic signatures  
- **RESTful API**: Complete API for wallet operations
- **Admin Interface**: User-friendly wallet management interface
- **Multi-Provider Support**: Support for MetaMask, Coinbase Wallet, WalletConnect, and more

## Features

### Core Functionality

1. **Wallet Linking**
   - Link Ethereum and other cryptocurrency wallets to user accounts
   - Support for multiple wallet types and providers
   - Unique wallet address constraint (one wallet per account)

2. **Wallet Verification**
   - Cryptographic signature verification for wallet ownership
   - Message signing through web3 providers
   - Verification status tracking with timestamps

3. **Metadata Management**
   - Store custom wallet metadata (chain ID, network name, etc.)
   - JSON-based flexible metadata storage
   - Update metadata through API or UI

4. **Security Features**
   - Wallet address validation
   - Signature verification (extensible for production use)
   - Access control through PgAppForge permissions

### API Endpoints

- `POST /api/v1/wallet/link` - Link a wallet to the current user
- `POST /api/v1/wallet/verify` - Verify wallet ownership
- `GET /api/v1/wallet/info` - Get wallet information
- `POST /api/v1/wallet/unlink` - Remove wallet from account
- `POST /api/v1/wallet/update-metadata` - Update wallet metadata

### User Interface

- Wallet management dashboard at `/wallet/`
- MetaMask integration for easy wallet connection
- Verification workflow with signature prompts
- Metadata editing with JSON validation

## Installation & Configuration

### 1. Enable Wallet Integration

Add the wallet manager to your PgAppForge configuration:

```python
# In your config.py
ADDON_MANAGERS = [
    'pgappforge.security.wallet.WalletManager'
]
```

### 2. Database Migration

The wallet integration adds the following fields to the User model:

```sql
ALTER TABLE ab_user ADD COLUMN wallet_address VARCHAR(128) UNIQUE;
ALTER TABLE ab_user ADD COLUMN wallet_type VARCHAR(50);
ALTER TABLE ab_user ADD COLUMN wallet_provider VARCHAR(100);
ALTER TABLE ab_user ADD COLUMN wallet_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE ab_user ADD COLUMN wallet_verification_date DATETIME;
ALTER TABLE ab_user ADD COLUMN wallet_metadata VARCHAR(1024);

CREATE INDEX idx_wallet_address ON ab_user(wallet_address);
```

### 3. Optional Configuration

Configure wallet settings in your PgAppForge app:

```python
WALLET_CONFIG = {
    'supported_types': ['metamask', 'coinbase', 'walletconnect', 'trust'],
    'require_verification': True,
    'allowed_networks': ['mainnet', 'polygon', 'bsc'],
    'metadata_max_size': 1024
}
```

## Usage Examples

### Link a Wallet (API)

```javascript
const response = await fetch('/api/v1/wallet/link', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
    },
    body: JSON.stringify({
        address: '0x742d35Cc6634C0532925a3b8D65c2Ba7A8d4D8C8',
        type: 'metamask',
        provider: 'MetaMask Browser Extension',
        metadata: {
            chain_id: 1,
            network_name: 'mainnet'
        }
    })
});
```

### Verify Wallet Ownership

```javascript
// Sign message with wallet
const message = `Verify wallet ownership at ${Date.now()}`;
const signature = await window.ethereum.request({
    method: 'personal_sign',
    params: [message, walletAddress]
});

// Submit verification
const response = await fetch('/api/v1/wallet/verify', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
    },
    body: JSON.stringify({
        signature,
        message,
        timestamp: Date.now()
    })
});
```

### Check Wallet Status (Python)

```python
from pgappforge.security import current_user

# Check if user has a wallet
if current_user.has_wallet():
    wallet_info = current_user.get_wallet_info()
    print(f"Wallet: {wallet_info['address']}")
    
    if current_user.is_wallet_verified():
        print("Wallet is verified")
    else:
        print("Wallet needs verification")
```

## Integration with Existing Code

### User Model Extensions

The User model now includes wallet-related methods:

```python
# Check wallet status
user.has_wallet()              # Returns True if wallet linked
user.is_wallet_verified()      # Returns True if verified

# Manage wallet
user.link_wallet(address, type, provider, metadata)
user.verify_wallet()
user.unlink_wallet()

# Get wallet data
user.get_wallet_info()         # Returns complete wallet info
user.get_wallet_metadata()     # Returns metadata as dict
```

### Access Control

Use PgAppForge's built-in permissions system:

```python
from pgappforge.security.decorators import has_access

@has_access
@expose('/wallet-required-page')
def wallet_required_page(self):
    if not current_user.has_wallet():
        flash('This page requires a linked wallet', 'warning')
        return redirect('/wallet/')
    
    # Page content for wallet users
    return self.render_template('wallet_page.html')
```

## Security Considerations

### Production Deployment

1. **Signature Verification**: Replace the demo signature verification with proper cryptographic libraries:
   ```python
   # For Ethereum signatures
   from eth_account.messages import encode_defunct
   from eth_account import Account
   
   def verify_ethereum_signature(address, message, signature):
       message_hash = encode_defunct(text=message)
       recovered_address = Account.recover_message(message_hash, signature=signature)
       return recovered_address.lower() == address.lower()
   ```

2. **Address Validation**: Implement proper address validation for supported blockchain networks

3. **Rate Limiting**: Add rate limiting to wallet API endpoints to prevent abuse

4. **HTTPS Only**: Ensure all wallet operations occur over HTTPS in production

5. **Audit Logging**: Log all wallet operations for security auditing

### Best Practices

- Always require wallet verification for sensitive operations
- Store minimal wallet metadata to reduce privacy risks  
- Implement proper error handling and user feedback
- Use secure random nonces for signature messages
- Regularly audit wallet permissions and access logs

## Troubleshooting

### Common Issues

1. **MetaMask Not Detected**
   - Ensure user has MetaMask extension installed
   - Check for web3 provider availability: `typeof window.ethereum !== 'undefined'`

2. **Signature Verification Fails**
   - Verify message format matches signed content exactly
   - Check wallet address matches the signer address
   - Ensure signature is in correct format (hex string starting with 0x)

3. **Database Migration Errors**
   - Run database migrations after adding wallet integration
   - Check for unique constraint violations on wallet_address field

### Debugging

Enable debug logging for wallet operations:

```python
import logging
logging.getLogger('pgappforge.security.wallet').setLevel(logging.DEBUG)
```

## Extending the Integration

### Custom Wallet Types

Add support for additional wallet types by extending the WalletApi:

```python
class CustomWalletApi(WalletApi):
    def _is_valid_wallet_address(self, address):
        # Add custom validation logic
        if address.startswith('bc1'):  # Bitcoin addresses
            return self._validate_bitcoin_address(address)
        return super()._is_valid_wallet_address(address)
```

### Custom Verification

Implement custom signature verification:

```python
class CustomWalletApi(WalletApi):
    def _verify_signature(self, address, message, signature):
        # Add custom verification logic for different wallet types
        if address.startswith('0x'):
            return self._verify_ethereum_signature(address, message, signature)
        elif address.startswith('bc1'):
            return self._verify_bitcoin_signature(address, message, signature)
        return False
```

## License

This wallet integration is part of PgAppForge and is provided under the same license terms.

## Support

For issues related to wallet integration:

1. Check the troubleshooting section above
2. Review PgAppForge documentation
3. Submit issues to the PgAppForge GitHub repository
4. Contact the development team for enterprise support

---

**Note**: This is a foundational implementation. For production use, ensure proper security reviews, comprehensive testing, and integration with established cryptocurrency libraries.