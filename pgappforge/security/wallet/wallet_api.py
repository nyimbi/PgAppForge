"""
Wallet Integration API for PgAppForge

Provides REST endpoints for wallet management including linking, verification,
and metadata handling for user cryptocurrency wallets.
"""

import json
import logging
import time
from flask import request, jsonify, g
from pgappforge import expose
from pgappforge.api import BaseApi, safe
from pgappforge.security.decorators import has_access_api
from ...baseviews import BaseView
from .. import current_user

# MPESA integration imports (with graceful fallback)
try:
    from ...wallet.mpesa_service import get_mpesa_service
    from ...wallet.mpesa_models import MPESATransaction, MPESAAccount
    MPESA_AVAILABLE = True
except ImportError:
    def get_mpesa_service():
        raise NotImplementedError("MPESA integration not available. Install required dependencies.")
    
    class MPESATransaction:
        pass
    
    class MPESAAccount:
        pass
    
    MPESA_AVAILABLE = False

# Wallet model imports (with graceful fallback)
try:
    from ...wallet.models import UserWallet
    WALLET_MODELS_AVAILABLE = True
except ImportError:
    class UserWallet:
        pass
    
    WALLET_MODELS_AVAILABLE = False

log = logging.getLogger(__name__)


class WalletApi(BaseApi):
    """
    RESTful API for wallet management operations.
    
    Provides endpoints for:
    - Linking wallets to user accounts
    - Verifying wallet ownership
    - Managing wallet metadata
    - Retrieving wallet information
    """
    
    resource_name = 'wallet'
    
    @expose('/link', methods=['POST'])
    @has_access_api
    @safe
    def link_wallet(self):
        """
        Link a cryptocurrency wallet to the current user's account.
        
        Expected JSON payload:
        {
            "address": "0x1234...",
            "type": "metamask",
            "provider": "MetaMask",
            "metadata": {
                "chain_id": 1,
                "network_name": "mainnet"
            }
        }
        
        Returns:
            JSON response with success status and wallet info
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
                
            # Comprehensive input validation
            wallet_address = data.get('address', '').strip()
            wallet_type = data.get('type', '').strip().lower()
            wallet_provider = data.get('provider', '').strip()
            metadata = data.get('metadata', {})
            
            # Required field validation
            if not wallet_address:
                return jsonify({'error': 'Wallet address is required'}), 400
                
            if not wallet_type:
                return jsonify({'error': 'Wallet type is required'}), 400
            
            # Validate wallet address length
            if len(wallet_address) < 10:
                return jsonify({'error': 'Wallet address too short'}), 400
            
            if len(wallet_address) > 128:
                return jsonify({'error': 'Wallet address too long'}), 400
            
            # Validate wallet type
            valid_wallet_types = ['metamask', 'coinbase', 'walletconnect', 'trust', 'other']
            if wallet_type not in valid_wallet_types:
                return jsonify({'error': f'Invalid wallet type. Must be one of: {", ".join(valid_wallet_types)}'}), 400
            
            # Validate provider field
            if wallet_provider and len(wallet_provider) > 100:
                return jsonify({'error': 'Wallet provider name too long (max 100 characters)'}), 400
            
            # Validate metadata
            if metadata:
                if not isinstance(metadata, dict):
                    return jsonify({'error': 'Metadata must be a JSON object'}), 400
                
                # Check metadata size (serialize to JSON and check length)
                try:
                    import json
                    metadata_json = json.dumps(metadata)
                    if len(metadata_json) > 1024:
                        return jsonify({'error': 'Metadata too large (max 1024 characters when serialized)'}), 400
                except (TypeError, ValueError):
                    return jsonify({'error': 'Metadata contains invalid values'}), 400
            
            # Validate wallet address format (basic validation)
            if not self._is_valid_wallet_address(wallet_address):
                return jsonify({'error': 'Invalid wallet address format'}), 400
            
            # Check if wallet is already linked to another user
            from pgappforge import db
            from .sqla.models import User
            
            existing_user = db.session.query(User).filter_by(wallet_address=wallet_address).first()
            if existing_user and existing_user.id != current_user.id:
                return jsonify({'error': 'Wallet already linked to another account'}), 409
            
            # Link wallet to current user
            current_user.link_wallet(
                address=wallet_address,
                wallet_type=wallet_type,
                provider=data.get('provider'),
                metadata=data.get('metadata', {})
            )
            
            db.session.commit()
            
            log.info(f"Wallet linked for user {current_user.id}: {wallet_address[:10]}...")
            
            return jsonify({
                'message': 'Wallet linked successfully',
                'wallet_info': current_user.get_wallet_info(),
                'verification_required': True
            }), 200
            
        except Exception as e:
            log.error(f"Error linking wallet: {str(e)}")
            return jsonify({'error': 'Failed to link wallet'}), 500
    
    @expose('/verify', methods=['POST'])
    @has_access_api
    @safe
    def verify_wallet(self):
        """
        Verify wallet ownership through signature verification.
        
        Expected JSON payload:
        {
            "signature": "0x...",
            "message": "Verification message",
            "timestamp": 1234567890
        }
        
        Returns:
            JSON response with verification status
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
                
            if not current_user.has_wallet():
                return jsonify({'error': 'No wallet linked to account'}), 400
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            signature = data.get('signature', '').strip()
            message = data.get('message', '').strip()
            timestamp = data.get('timestamp')
            
            # Comprehensive validation
            if not signature:
                return jsonify({'error': 'Signature is required'}), 400
            
            if not message:
                return jsonify({'error': 'Message is required'}), 400
            
            if timestamp is None:
                return jsonify({'error': 'Timestamp is required'}), 400
            
            # Validate signature format
            if not signature.startswith('0x'):
                return jsonify({'error': 'Signature must start with 0x'}), 400
            
            if len(signature) < 132:  # 0x + 130 hex chars for Ethereum signature
                return jsonify({'error': 'Signature too short'}), 400
            
            if len(signature) > 150:  # Allow some flexibility but prevent abuse
                return jsonify({'error': 'Signature too long'}), 400
            
            # Validate message length
            if len(message) > 500:
                return jsonify({'error': 'Message too long (max 500 characters)'}), 400
            
            # Validate timestamp (should be recent)
            try:
                timestamp_int = int(timestamp)
                current_timestamp = int(time.time())
                
                # Allow messages up to 5 minutes old
                if timestamp_int < current_timestamp - 300:
                    return jsonify({'error': 'Message timestamp too old (max 5 minutes)'}), 400
                
                # Prevent future timestamps
                if timestamp_int > current_timestamp + 60:
                    return jsonify({'error': 'Message timestamp is in the future'}), 400
                    
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid timestamp format'}), 400
            
            # Verify signature (simplified - in production use proper crypto libraries)
            if self._verify_signature(current_user.wallet_address, message, signature):
                current_user.verify_wallet()
                
                from pgappforge import db
                db.session.commit()
                
                log.info(f"Wallet verified for user {current_user.id}: {current_user.wallet_address[:10]}...")
                
                return jsonify({
                    'message': 'Wallet verified successfully',
                    'wallet_info': current_user.get_wallet_info()
                }), 200
            else:
                return jsonify({'error': 'Signature verification failed'}), 400
                
        except Exception as e:
            log.error(f"Error verifying wallet: {str(e)}")
            return jsonify({'error': 'Failed to verify wallet'}), 500
    
    @expose('/info', methods=['GET'])
    @has_access_api
    @safe
    def get_wallet_info(self):
        """
        Get current user's wallet information.
        
        Returns:
            JSON response with wallet details or null if no wallet
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            wallet_info = current_user.get_wallet_info()
            
            return jsonify({
                'wallet_info': wallet_info,
                'has_wallet': current_user.has_wallet(),
                'is_verified': current_user.is_wallet_verified()
            }), 200
            
        except Exception as e:
            log.error(f"Error getting wallet info: {str(e)}")
            return jsonify({'error': 'Failed to retrieve wallet information'}), 500
    
    @expose('/unlink', methods=['POST'])
    @has_access_api
    @safe
    def unlink_wallet(self):
        """
        Remove wallet from current user's account.
        
        Returns:
            JSON response with success status
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
                
            if not current_user.has_wallet():
                return jsonify({'error': 'No wallet linked to account'}), 400
            
            # Store wallet address for logging
            wallet_address = current_user.wallet_address
            
            current_user.unlink_wallet()
            
            from pgappforge import db
            db.session.commit()
            
            log.info(f"Wallet unlinked for user {current_user.id}: {wallet_address[:10]}...")
            
            return jsonify({
                'message': 'Wallet unlinked successfully'
            }), 200
            
        except Exception as e:
            log.error(f"Error unlinking wallet: {str(e)}")
            return jsonify({'error': 'Failed to unlink wallet'}), 500
    
    @expose('/update-metadata', methods=['POST'])
    @has_access_api
    @safe
    def update_metadata(self):
        """
        Update wallet metadata for current user.
        
        Expected JSON payload:
        {
            "metadata": {
                "chain_id": 1,
                "network_name": "mainnet",
                "custom_field": "value"
            }
        }
        
        Returns:
            JSON response with updated wallet info
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
                
            if not current_user.has_wallet():
                return jsonify({'error': 'No wallet linked to account'}), 400
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            metadata = data.get('metadata', {})
            if not isinstance(metadata, dict):
                return jsonify({'error': 'Metadata must be a valid JSON object'}), 400
            
            # Update metadata
            current_user.wallet_metadata = json.dumps(metadata)
            
            from pgappforge import db
            db.session.commit()
            
            log.info(f"Wallet metadata updated for user {current_user.id}")
            
            return jsonify({
                'message': 'Wallet metadata updated successfully',
                'wallet_info': current_user.get_wallet_info()
            }), 200
            
        except Exception as e:
            log.error(f"Error updating wallet metadata: {str(e)}")
            return jsonify({'error': 'Failed to update wallet metadata'}), 500
    
    def _is_valid_wallet_address(self, address):
        """
        Basic wallet address validation.
        
        Args:
            address: Wallet address string
            
        Returns:
            Boolean indicating if address format is valid
        """
        # Basic validation - in production use proper validation libraries
        if not address or not isinstance(address, str):
            return False
        
        # Ethereum address validation (0x followed by 40 hex characters)
        if address.startswith('0x') and len(address) == 42:
            try:
                int(address[2:], 16)  # Check if hex
                return True
            except ValueError:
                return False
        
        # Bitcoin address validation (basic)
        if len(address) >= 26 and len(address) <= 35:
            return True
            
        # Add more address types as needed
        return False
    
    def _verify_signature(self, wallet_address, message, signature):
        """
        Verify wallet signature using proper cryptographic validation.
        
        Args:
            wallet_address: Wallet address
            message: Signed message
            signature: Cryptographic signature
            
        Returns:
            Boolean indicating verification success
        """
        try:
            log.info(f"Verifying signature for address {wallet_address[:10]}...")
            
            # Ethereum address verification (0x followed by 40 hex characters)
            if wallet_address.startswith('0x') and len(wallet_address) == 42:
                return self._verify_ethereum_signature(wallet_address, message, signature)
            
            # Bitcoin address verification (26-35 characters)
            elif 26 <= len(wallet_address) <= 35 and not wallet_address.startswith('0x'):
                return self._verify_bitcoin_signature(wallet_address, message, signature)
            
            log.warning(f"Unsupported wallet address format: {wallet_address}")
            return False
            
        except Exception as e:
            log.error(f"Signature verification error: {str(e)}")
            return False
    
    def _verify_ethereum_signature(self, wallet_address, message, signature):
        """Verify Ethereum wallet signature."""
        try:
            # Try eth_account library first (production grade)
            from eth_account.messages import encode_defunct
            from eth_account import Account
            
            # Encode message as Ethereum signed message
            encoded_message = encode_defunct(text=message)
            
            # Recover address from signature
            recovered_address = Account.recover_message(encoded_message, signature=signature)
            
            # Compare addresses (case-insensitive)
            return recovered_address.lower() == wallet_address.lower()
            
        except ImportError:
            log.warning("eth_account library not available, using fallback verification")
            return self._verify_ethereum_signature_fallback(wallet_address, message, signature)
        except Exception as e:
            log.error(f"Ethereum signature verification failed: {str(e)}")
            return False
    
    def _verify_ethereum_signature_fallback(self, wallet_address, message, signature):
        """Fallback Ethereum signature verification using web3."""
        try:
            from web3 import Web3
            from eth_hash.auto import keccak
            
            # Create message hash
            message_hash = keccak(f"\x19Ethereum Signed Message:\n{len(message)}{message}".encode())
            
            # Remove 0x prefix from signature
            if signature.startswith('0x'):
                signature = signature[2:]
            
            # Extract r, s, v components
            r = int(signature[:64], 16)
            s = int(signature[64:128], 16)
            v = int(signature[128:130], 16)
            
            # Recover address
            from eth_keys import keys
            signature_obj = keys.Signature(vrs=(v, r, s))
            recovered_address = signature_obj.recover_public_key_from_msg_hash(message_hash).to_checksum_address()
            
            return recovered_address.lower() == wallet_address.lower()
            
        except ImportError:
            log.error("Required cryptographic libraries (web3, eth_hash, eth_keys) not available - signature verification impossible")
            raise RuntimeError("Cryptographic verification dependencies not installed. Install with: pip install web3 eth_hash eth_keys")
        except Exception as e:
            log.error(f"Fallback Ethereum verification failed: {str(e)}")
            return False
    
    def _verify_bitcoin_signature(self, wallet_address, message, signature):
        """Verify Bitcoin wallet signature."""
        try:
            # Try bitcoinlib library
            import bitcoin
            return bitcoin.verify_message(wallet_address, message, signature)
            
        except ImportError:
            log.error("Required Bitcoin libraries not available for signature verification")
            try:
                # Try alternative library
                import bitcoinutils.utils as btc_utils
                return btc_utils.verify_message(wallet_address, signature, message)
            except ImportError:
                log.error("No Bitcoin signature verification libraries available - verification impossible")
                raise RuntimeError("Bitcoin signature verification dependencies not installed. Install with: pip install bitcoinlib or pip install bitcoin-utils")
        except Exception as e:
            log.error(f"Bitcoin signature verification failed: {str(e)}")
            return False
    
    # MPESA Integration Endpoints
    
    @expose('/mpesa/link', methods=['POST'])
    @has_access_api
    @safe
    def link_mpesa_account(self):
        """
        Link MPESA account to current user's wallet.
        
        Expected JSON payload:
        {
            "phone_number": "254712345678",
            "account_name": "John Doe",
            "wallet_id": 1
        }
        
        Returns:
            JSON response with success status and account info
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            phone_number = data.get('phone_number', '').strip()
            account_name = data.get('account_name', '').strip()
            wallet_id = data.get('wallet_id')
            
            # Validate required fields
            if not phone_number:
                return jsonify({'error': 'Phone number is required'}), 400
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Link account
            success, message, mpesa_account = mpesa_service.link_account_to_user(
                user_id=current_user.id,
                phone_number=phone_number,
                account_name=account_name,
                wallet_id=wallet_id
            )
            
            if success:
                return jsonify({
                    'message': message,
                    'account': {
                        'id': mpesa_account.id,
                        'phone_number': mpesa_account.phone_number,
                        'account_name': mpesa_account.account_name,
                        'is_verified': mpesa_account.is_verified,
                        'verification_required': not mpesa_account.is_verified
                    }
                }), 201
            else:
                return jsonify({'error': message}), 400
            
        except Exception as e:
            log.error(f"Error linking MPESA account: {str(e)}")
            return jsonify({'error': 'Failed to link MPESA account'}), 500
    
    @expose('/mpesa/verify', methods=['POST'])
    @has_access_api
    @safe
    def verify_mpesa_account(self):
        """
        Verify MPESA account with SMS verification code.
        
        Expected JSON payload:
        {
            "account_id": 1,
            "verification_code": "123456"
        }
        
        Returns:
            JSON response with verification status
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            account_id = data.get('account_id')
            verification_code = data.get('verification_code', '').strip()
            
            if not account_id or not verification_code:
                return jsonify({'error': 'Account ID and verification code are required'}), 400
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Verify account
            success, message = mpesa_service.verify_account(account_id, verification_code)
            
            if success:
                return jsonify({'message': message}), 200
            else:
                return jsonify({'error': message}), 400
            
        except Exception as e:
            log.error(f"Error verifying MPESA account: {str(e)}")
            return jsonify({'error': 'Failed to verify MPESA account'}), 500
    
    @expose('/mpesa/pay', methods=['POST'])
    @has_access_api
    @safe
    def initiate_mpesa_payment(self):
        """
        Initiate MPESA STK Push payment.
        
        Expected JSON payload:
        {
            "phone_number": "254712345678",
            "amount": 100.00,
            "account_reference": "WALLET_TOPUP",
            "description": "Wallet top-up"
        }
        
        Returns:
            JSON response with payment initiation status
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            phone_number = data.get('phone_number', '').strip()
            amount = data.get('amount')
            account_reference = data.get('account_reference', '').strip()
            description = data.get('description', '').strip()
            
            # Validate required fields
            if not phone_number or not amount:
                return jsonify({'error': 'Phone number and amount are required'}), 400
            
            # Validate amount
            try:
                from decimal import Decimal
                amount = Decimal(str(amount))
                if amount <= 0:
                    return jsonify({'error': 'Amount must be positive'}), 400
                if amount > 70000:
                    return jsonify({'error': 'Maximum amount is KES 70,000'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amount format'}), 400
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Get user's MPESA account
            mpesa_accounts = mpesa_service.get_user_accounts(current_user.id)
            mpesa_account = None
            for acc in mpesa_accounts:
                if acc.phone_number == phone_number or phone_number in acc.phone_number:
                    mpesa_account = acc
                    break
            
            # Initiate STK Push
            success, message, transaction = mpesa_service.initiate_stk_push(
                phone_number=phone_number,
                amount=amount,
                account_reference=account_reference or f"WALLET_{current_user.id}",
                transaction_desc=description or "Wallet Top-up",
                mpesa_account=mpesa_account
            )
            
            if success:
                return jsonify({
                    'message': message,
                    'transaction': {
                        'id': transaction.id,
                        'checkout_request_id': transaction.checkout_request_id,
                        'amount': str(transaction.amount),
                        'status': transaction.status,
                        'phone_number': transaction.phone_number
                    }
                }), 200
            else:
                return jsonify({'error': message}), 400
            
        except Exception as e:
            log.error(f"Error initiating MPESA payment: {str(e)}")
            return jsonify({'error': 'Failed to initiate payment'}), 500
    
    @expose('/mpesa/status/<checkout_request_id>', methods=['GET'])
    @has_access_api
    @safe
    def get_mpesa_payment_status(self, checkout_request_id):
        """
        Get MPESA payment status.
        
        Returns:
            JSON response with payment status
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if not checkout_request_id:
                return jsonify({'error': 'Checkout request ID is required'}), 400
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                from pgappforge import db
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Find transaction
            transaction = db.session.query(MPESATransaction).filter_by(
                checkout_request_id=checkout_request_id
            ).first()
            
            if not transaction:
                return jsonify({'error': 'Transaction not found'}), 404
            
            # Query MPESA for latest status if still pending
            if transaction.is_pending():
                success, message, response_data = mpesa_service.query_stk_status(checkout_request_id)
                if success and response_data:
                    # Update transaction status based on query result using official Safaricom error codes
                    result_code = str(response_data.get('ResultCode', ''))
                    result_desc = response_data.get('ResultDesc', 'Unknown result')
                    
                    if result_code == '0':
                        transaction.status = 'completed'
                    elif result_code == '1032':  # User cancelled
                        transaction.status = 'cancelled'
                        transaction.response_description = result_desc or "User cancelled the payment request"
                    elif result_code == '1037':  # Timeout/unreachable
                        transaction.status = 'timeout'
                        transaction.response_description = result_desc or "Payment request timed out"
                    elif result_code == '1025':  # System error
                        transaction.status = 'failed'
                        transaction.response_description = result_desc or "System error occurred"
                    elif result_code == '1':  # Insufficient balance
                        transaction.status = 'failed'
                        transaction.response_description = result_desc or "Insufficient balance"
                    elif result_code == '2001':  # Wrong PIN
                        transaction.status = 'failed'
                        transaction.response_description = result_desc or "Wrong PIN entered"
                    elif result_code == '1001':  # Unable to lock subscriber
                        transaction.status = 'failed'
                        transaction.response_description = result_desc or "Unable to lock subscriber"
                    elif result_code:
                        transaction.status = 'failed'
                        transaction.response_description = result_desc or f"Payment failed (Code: {result_code})"
                    
                    transaction.response_code = result_code
                    
                    db.session.commit()
            
            return jsonify({
                'transaction': {
                    'id': transaction.id,
                    'checkout_request_id': transaction.checkout_request_id,
                    'mpesa_receipt_number': transaction.mpesa_receipt_number,
                    'amount': str(transaction.amount),
                    'status': transaction.status,
                    'phone_number': transaction.phone_number,
                    'transaction_date': transaction.transaction_date.isoformat() if transaction.transaction_date else None,
                    'response_description': transaction.response_description
                }
            }), 200
            
        except Exception as e:
            log.error(f"Error getting MPESA payment status: {str(e)}")
            return jsonify({'error': 'Failed to get payment status'}), 500
    
    @expose('/mpesa/accounts', methods=['GET'])
    @has_access_api
    @safe
    def get_mpesa_accounts(self):
        """
        Get current user's MPESA accounts.
        
        Returns:
            JSON response with list of MPESA accounts
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Get user accounts
            accounts = mpesa_service.get_user_accounts(current_user.id)
            
            account_list = []
            for account in accounts:
                account_list.append({
                    'id': account.id,
                    'phone_number': account.phone_number,
                    'account_name': account.account_name,
                    'is_verified': account.is_verified,
                    'is_active': account.is_active,
                    'wallet_id': account.wallet_id,
                    'created_on': account.created_on.isoformat() if account.created_on else None
                })
            
            return jsonify({
                'accounts': account_list,
                'total': len(account_list)
            }), 200
            
        except Exception as e:
            log.error(f"Error getting MPESA accounts: {str(e)}")
            return jsonify({'error': 'Failed to get MPESA accounts'}), 500
    
    @expose('/mpesa/transactions', methods=['GET'])
    @has_access_api
    @safe
    def get_mpesa_transactions(self):
        """
        Get current user's MPESA transaction history.
        
        Query parameters:
        - limit: Maximum number of transactions (default: 50)
        - status: Filter by status (pending, completed, failed, cancelled)
        - account_id: Filter by MPESA account ID
        
        Returns:
            JSON response with transaction history
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            # Get query parameters
            limit = min(int(request.args.get('limit', 50)), 100)  # Max 100
            status = request.args.get('status', '').strip()
            account_id = request.args.get('account_id')
            
            # Convert account_id to int if provided
            if account_id:
                try:
                    account_id = int(account_id)
                except ValueError:
                    return jsonify({'error': 'Invalid account ID'}), 400
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                return jsonify({'error': 'MPESA integration not available'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service: {e}")
                return jsonify({'error': 'MPESA service unavailable'}), 503
            
            # Get transaction history
            transactions = mpesa_service.get_transaction_history(
                mpesa_account_id=account_id,
                user_id=current_user.id,
                limit=limit,
                status=status if status else None
            )
            
            transaction_list = []
            for txn in transactions:
                transaction_list.append({
                    'id': txn.id,
                    'checkout_request_id': txn.checkout_request_id,
                    'mpesa_receipt_number': txn.mpesa_receipt_number,
                    'transaction_type': txn.transaction_type,
                    'amount': str(txn.amount),
                    'phone_number': txn.phone_number,
                    'account_reference': txn.account_reference,
                    'transaction_desc': txn.transaction_desc,
                    'status': txn.status,
                    'transaction_date': txn.transaction_date.isoformat() if txn.transaction_date else None,
                    'created_on': txn.created_on.isoformat() if txn.created_on else None,
                    'response_description': txn.response_description
                })
            
            return jsonify({
                'transactions': transaction_list,
                'total': len(transaction_list),
                'limit': limit,
                'filters': {
                    'status': status,
                    'account_id': account_id
                }
            }), 200
            
        except Exception as e:
            log.error(f"Error getting MPESA transactions: {str(e)}")
            return jsonify({'error': 'Failed to get transaction history'}), 500
    
    @expose('/mpesa/callback', methods=['POST'])
    @safe
    def mpesa_callback(self):
        """
        MPESA callback endpoint for STK Push results.
        
        This endpoint receives callbacks from MPESA and processes them.
        Should be publicly accessible (no authentication required).
        
        Returns:
            JSON acknowledgment for MPESA
        """
        try:
            # Log the callback for debugging
            callback_data = request.get_json()
            headers_data = dict(request.headers)
            
            log.info(f"MPESA callback received: {json.dumps(callback_data)}")
            
            # Check MPESA availability and get service
            if not MPESA_AVAILABLE:
                log.error("MPESA integration not available for callback processing")
                return jsonify({'ResultCode': 1, 'ResultDesc': 'Service unavailable'}), 503
            
            try:
                mpesa_service = get_mpesa_service()
            except Exception as e:
                log.error(f"Failed to initialize MPESA service for callback: {e}")
                return jsonify({'ResultCode': 1, 'ResultDesc': 'Service unavailable'}), 503
            
            # Process callback
            success, message = mpesa_service.process_stk_callback(callback_data)
            
            if success:
                # Acknowledge callback to MPESA
                return jsonify({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback processed successfully'
                }), 200
            else:
                log.error(f"Callback processing failed: {message}")
                return jsonify({
                    'ResultCode': 1,
                    'ResultDesc': f'Processing failed: {message}'
                }), 200  # Still return 200 to MPESA to avoid retries
            
        except Exception as e:
            log.error(f"MPESA callback error: {str(e)}")
            # Return success to MPESA to avoid endless retries
            return jsonify({
                'ResultCode': 1,
                'ResultDesc': f'Callback error: {str(e)}'
            }), 200
    
    # Wallet Operations Endpoints
    
    @expose('/cashout', methods=['POST'])
    @has_access_api
    @safe
    def cashout(self):
        """
        Cash out funds from user's wallet to external system.
        
        Expected JSON payload:
        {
            "wallet_id": 1,
            "amount": 1000.00,
            "destination": "254712345678",
            "description": "Cash out to MPESA",
            "reference": "TXN12345"
        }
        
        Returns:
            JSON response with transaction details
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            wallet_id = data.get('wallet_id')
            amount = data.get('amount')
            destination = data.get('destination', '').strip()
            description = data.get('description', '').strip()
            reference = data.get('reference', '').strip()
            
            # Validate required fields
            if not wallet_id or not amount or not destination:
                return jsonify({'error': 'Wallet ID, amount, and destination are required'}), 400
            
            # Validate amount
            try:
                from decimal import Decimal
                amount = Decimal(str(amount))
                if amount <= 0:
                    return jsonify({'error': 'Amount must be positive'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amount format'}), 400
            
            # Get user's wallet
            if not WALLET_MODELS_AVAILABLE:
                return jsonify({'error': 'Wallet system not available'}), 503
            
            try:
                from pgappforge import db
                
                wallet = db.session.query(UserWallet).filter_by(
                    id=wallet_id, 
                    user_id=current_user.id
                ).first()
                
                if not wallet:
                    return jsonify({'error': 'Wallet not found or access denied'}), 404
                
                # Perform cashout
                transaction = wallet.cashout(
                    amount=amount,
                    destination=destination,
                    description=description or f"Cashout to {destination}",
                    reference=reference,
                    auto_commit=True
                )
                
                return jsonify({
                    'message': 'Cashout successful',
                    'transaction': {
                        'id': transaction.id,
                        'amount': str(transaction.amount),
                        'destination': destination,
                        'description': transaction.description,
                        'reference': transaction.reference_number,
                        'status': transaction.status,
                        'transaction_date': transaction.transaction_date.isoformat() if transaction.transaction_date else None
                    },
                    'wallet': {
                        'id': wallet.id,
                        'name': wallet.wallet_name,
                        'new_balance': str(wallet.balance),
                        'currency': wallet.currency_code
                    }
                }), 200
                
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            except Exception as e:
                log.error(f"Error during cashout: {e}")
                return jsonify({'error': 'Cashout failed'}), 500
            
        except Exception as e:
            log.error(f"Error processing cashout request: {str(e)}")
            return jsonify({'error': 'Failed to process cashout'}), 500
    
    @expose('/withdraw', methods=['POST'])
    @has_access_api
    @safe
    def withdraw(self):
        """
        Withdraw funds from user's wallet.
        
        Expected JSON payload:
        {
            "wallet_id": 1,
            "amount": 500.00,
            "description": "ATM withdrawal",
            "reference": "ATM12345"
        }
        
        Returns:
            JSON response with transaction details
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            wallet_id = data.get('wallet_id')
            amount = data.get('amount')
            description = data.get('description', '').strip()
            reference = data.get('reference', '').strip()
            
            # Validate required fields
            if not wallet_id or not amount:
                return jsonify({'error': 'Wallet ID and amount are required'}), 400
            
            # Validate amount
            try:
                from decimal import Decimal
                amount = Decimal(str(amount))
                if amount <= 0:
                    return jsonify({'error': 'Amount must be positive'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amount format'}), 400
            
            # Get user's wallet
            if not WALLET_MODELS_AVAILABLE:
                return jsonify({'error': 'Wallet system not available'}), 503
            
            try:
                from pgappforge import db
                
                wallet = db.session.query(UserWallet).filter_by(
                    id=wallet_id,
                    user_id=current_user.id
                ).first()
                
                if not wallet:
                    return jsonify({'error': 'Wallet not found or access denied'}), 404
                
                # Perform withdrawal
                transaction = wallet.withdraw(
                    amount=amount,
                    description=description or "Withdrawal",
                    reference=reference,
                    auto_commit=True
                )
                
                return jsonify({
                    'message': 'Withdrawal successful',
                    'transaction': {
                        'id': transaction.id,
                        'amount': str(transaction.amount),
                        'description': transaction.description,
                        'reference': transaction.reference_number,
                        'status': transaction.status,
                        'transaction_date': transaction.transaction_date.isoformat() if transaction.transaction_date else None
                    },
                    'wallet': {
                        'id': wallet.id,
                        'name': wallet.wallet_name,
                        'new_balance': str(wallet.balance),
                        'currency': wallet.currency_code
                    }
                }), 200
                
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            except Exception as e:
                log.error(f"Error during withdrawal: {e}")
                return jsonify({'error': 'Withdrawal failed'}), 500
            
        except Exception as e:
            log.error(f"Error processing withdrawal request: {str(e)}")
            return jsonify({'error': 'Failed to process withdrawal'}), 500
    
    @expose('/transfer', methods=['POST'])
    @has_access_api
    @safe
    def transfer(self):
        """
        Transfer funds between wallets.
        
        Expected JSON payload:
        {
            "from_wallet_id": 1,
            "to_wallet_id": 2,
            "amount": 500.00,
            "description": "Transfer to savings"
        }
        
        Returns:
            JSON response with transaction details
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Invalid JSON payload'}), 400
            
            from_wallet_id = data.get('from_wallet_id')
            to_wallet_id = data.get('to_wallet_id')
            amount = data.get('amount')
            description = data.get('description', '').strip()
            
            # Validate required fields
            if not from_wallet_id or not to_wallet_id or not amount:
                return jsonify({'error': 'Source wallet, destination wallet, and amount are required'}), 400
            
            if from_wallet_id == to_wallet_id:
                return jsonify({'error': 'Cannot transfer to the same wallet'}), 400
            
            # Validate amount
            try:
                from decimal import Decimal
                amount = Decimal(str(amount))
                if amount <= 0:
                    return jsonify({'error': 'Amount must be positive'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid amount format'}), 400
            
            # Get user's wallets
            if not WALLET_MODELS_AVAILABLE:
                return jsonify({'error': 'Wallet system not available'}), 503
            
            try:
                from pgappforge import db
                
                from_wallet = db.session.query(UserWallet).filter_by(
                    id=from_wallet_id,
                    user_id=current_user.id
                ).first()
                
                to_wallet = db.session.query(UserWallet).filter_by(
                    id=to_wallet_id,
                    user_id=current_user.id
                ).first()
                
                if not from_wallet:
                    return jsonify({'error': 'Source wallet not found or access denied'}), 404
                
                if not to_wallet:
                    return jsonify({'error': 'Destination wallet not found or access denied'}), 404
                
                # Perform transfer
                outgoing_txn, incoming_txn = from_wallet.transfer_to(
                    target_wallet=to_wallet,
                    amount=amount,
                    description=description or f"Transfer to {to_wallet.wallet_name}",
                    auto_commit=True
                )
                
                return jsonify({
                    'message': 'Transfer successful',
                    'outgoing_transaction': {
                        'id': outgoing_txn.id,
                        'wallet_id': outgoing_txn.wallet_id,
                        'amount': str(outgoing_txn.amount),
                        'description': outgoing_txn.description,
                        'status': outgoing_txn.status
                    },
                    'incoming_transaction': {
                        'id': incoming_txn.id,
                        'wallet_id': incoming_txn.wallet_id,
                        'amount': str(incoming_txn.amount),
                        'description': incoming_txn.description,
                        'status': incoming_txn.status
                    },
                    'wallets': {
                        'from_wallet': {
                            'id': from_wallet.id,
                            'name': from_wallet.wallet_name,
                            'new_balance': str(from_wallet.balance),
                            'currency': from_wallet.currency_code
                        },
                        'to_wallet': {
                            'id': to_wallet.id,
                            'name': to_wallet.wallet_name,
                            'new_balance': str(to_wallet.balance),
                            'currency': to_wallet.currency_code
                        }
                    }
                }), 200
                
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            except Exception as e:
                log.error(f"Error during transfer: {e}")
                return jsonify({'error': 'Transfer failed'}), 500
            
        except Exception as e:
            log.error(f"Error processing transfer request: {str(e)}")
            return jsonify({'error': 'Failed to process transfer'}), 500
    
    @expose('/statement/<int:wallet_id>', methods=['GET'])
    @has_access_api
    @safe
    def get_statement(self, wallet_id):
        """
        Get detailed wallet statement.
        
        Query parameters:
        - start_date: Start date (YYYY-MM-DD format)
        - end_date: End date (YYYY-MM-DD format)  
        - transaction_type: Filter by type (income, expense, transfer)
        - limit: Maximum transactions to return
        - include_balance: Include running balance (true/false)
        
        Returns:
            JSON response with detailed statement
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            # Get user's wallet
            if not WALLET_MODELS_AVAILABLE:
                return jsonify({'error': 'Wallet system not available'}), 503
            
            from pgappforge import db
            
            wallet = db.session.query(UserWallet).filter_by(
                id=wallet_id,
                user_id=current_user.id
            ).first()
            
            if not wallet:
                return jsonify({'error': 'Wallet not found or access denied'}), 404
            
            # Parse query parameters
            from datetime import datetime
            
            start_date = None
            end_date = None
            
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                except ValueError:
                    return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD'}), 400
            
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                    # Set to end of day
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                except ValueError:
                    return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD'}), 400
            
            transaction_type = request.args.get('transaction_type')
            limit = request.args.get('limit')
            include_balance = request.args.get('include_balance', 'true').lower() == 'true'
            
            if limit:
                try:
                    limit = int(limit)
                    if limit <= 0 or limit > 1000:
                        return jsonify({'error': 'Limit must be between 1 and 1000'}), 400
                except ValueError:
                    return jsonify({'error': 'Invalid limit parameter'}), 400
            
            # Generate statement
            statement = wallet.get_statement(
                start_date=start_date,
                end_date=end_date,
                transaction_type=transaction_type,
                limit=limit,
                include_balance=include_balance
            )
            
            return jsonify(statement), 200
            
        except Exception as e:
            log.error(f"Error generating wallet statement: {str(e)}")
            return jsonify({'error': 'Failed to generate statement'}), 500
    
    @expose('/monthly-summary/<int:wallet_id>', methods=['GET'])
    @has_access_api
    @safe
    def get_monthly_summary(self, wallet_id):
        """
        Get monthly wallet summary.
        
        Query parameters:
        - year: Year (defaults to current year)
        - month: Month (defaults to current month)
        
        Returns:
            JSON response with monthly summary
        """
        try:
            if not current_user or not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            # Get user's wallet
            if not WALLET_MODELS_AVAILABLE:
                return jsonify({'error': 'Wallet system not available'}), 503
            
            from pgappforge import db
            
            wallet = db.session.query(UserWallet).filter_by(
                id=wallet_id,
                user_id=current_user.id
            ).first()
            
            if not wallet:
                return jsonify({'error': 'Wallet not found or access denied'}), 404
            
            # Parse query parameters
            year = request.args.get('year')
            month = request.args.get('month')
            
            if year:
                try:
                    year = int(year)
                    if year < 2000 or year > 2100:
                        return jsonify({'error': 'Year must be between 2000 and 2100'}), 400
                except ValueError:
                    return jsonify({'error': 'Invalid year parameter'}), 400
            
            if month:
                try:
                    month = int(month)
                    if month < 1 or month > 12:
                        return jsonify({'error': 'Month must be between 1 and 12'}), 400
                except ValueError:
                    return jsonify({'error': 'Invalid month parameter'}), 400
            
            # Generate monthly summary
            summary = wallet.get_monthly_summary(year=year, month=month)
            
            return jsonify(summary), 200
            
        except Exception as e:
            log.error(f"Error generating monthly summary: {str(e)}")
            return jsonify({'error': 'Failed to generate monthly summary'}), 500


class WalletView(BaseView):
    """
    Wallet management view for PgAppForge admin interface.
    """
    
    route_base = '/wallet'
    
    @expose('/')
    def index(self):
        """Wallet management interface"""
        return self.render_template(
            'wallet/index.html',
            current_user=current_user
        )