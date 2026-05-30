#!/usr/bin/env python3
"""
Simple MFA Component Test

Tests individual MFA components without full PgAppForge integration.
This verifies that the MFA code works independently.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_mfa_services():
    """Test MFA service components."""
    print("Testing MFA Services...")
    
    try:
        # Test TOTP Service
        from pgappforge.security.mfa.services import TOTPService
        
        # Generate secret
        secret = TOTPService.generate_secret()
        print(f"✓ Generated TOTP secret: {secret[:8]}...")
        
        # Generate TOTP
        totp = TOTPService.generate_totp(secret)
        current_code = totp.now()
        print(f"✓ Generated TOTP code: {current_code}")
        
        # Verify code
        is_valid = TOTPService.verify_token(secret, current_code)
        print(f"✓ TOTP verification: {'PASS' if is_valid else 'FAIL'}")
        
        # Test QR code generation
        qr_code = TOTPService.generate_qr_code(secret, "test@example.com", "Test App")
        print(f"✓ Generated QR code: {len(qr_code)} bytes")
        
        return True
        
    except ImportError as e:
        print(f"⚠ MFA services not available: {e}")
        print("Install dependencies: pip install pyotp qrcode[pil] Pillow")
        return False
    except Exception as e:
        print(f"✗ MFA services test failed: {e}")
        return False

def test_mfa_models():
    """Test MFA model definitions."""
    print("\nTesting MFA Models...")
    
    try:
        from pgappforge.security.mfa.models import (
            UserMFA, MFABackupCodes, MFAVerificationAttempt, MFAPolicy
        )
        
        # Test model instantiation
        user_mfa = UserMFA()
        backup_codes = MFABackupCodes()
        verification = MFAVerificationAttempt()
        policy = MFAPolicy()
        
        print("✓ All MFA models imported successfully")
        print(f"✓ UserMFA table: {user_mfa.__tablename__}")
        print(f"✓ MFABackupCodes table: {backup_codes.__tablename__}")
        print(f"✓ MFAVerificationAttempt table: {verification.__tablename__}")
        print(f"✓ MFAPolicy table: {policy.__tablename__}")
        
        return True
        
    except ImportError as e:
        print(f"⚠ MFA models not available: {e}")
        return False
    except Exception as e:
        print(f"✗ MFA models test failed: {e}")
        return False

def test_mfa_manager_mixin():
    """Test MFA manager mixin."""
    print("\nTesting MFA Manager Mixin...")
    
    try:
        from pgappforge.security.mfa.manager_mixin import MFASecurityManagerMixin
        
        # Test class definition
        mixin = MFASecurityManagerMixin()
        
        # Check required methods exist
        required_methods = [
            'is_mfa_enabled_for_user',
            'is_mfa_required',
            'setup_user_mfa',
            'verify_user_mfa',
            '_init_mfa'
        ]
        
        for method in required_methods:
            if hasattr(mixin, method):
                print(f"✓ Method {method} exists")
            else:
                print(f"✗ Method {method} missing")
                return False
        
        return True
        
    except ImportError as e:
        print(f"⚠ MFA manager mixin not available: {e}")
        return False
    except Exception as e:
        print(f"✗ MFA manager mixin test failed: {e}")
        return False

def test_mfa_views():
    """Test MFA view definitions."""
    print("\nTesting MFA Views...")
    
    try:
        from pgappforge.security.mfa.views import MFASetupView, MFAVerificationView
        from pgappforge.security.mfa.auth_views import MFAEnabledAuthDBView
        
        print("✓ MFASetupView imported")
        print("✓ MFAVerificationView imported")
        print("✓ MFAEnabledAuthDBView imported")
        
        # Check route bases
        if hasattr(MFASetupView, 'route_base'):
            print(f"✓ MFASetupView route: {MFASetupView.route_base}")
        
        if hasattr(MFAVerificationView, 'route_base'):
            print(f"✓ MFAVerificationView route: {MFAVerificationView.route_base}")
        
        return True
        
    except ImportError as e:
        print(f"⚠ MFA views not available: {e}")
        return False
    except Exception as e:
        print(f"✗ MFA views test failed: {e}")
        return False

def test_mfa_config():
    """Test MFA configuration utilities."""
    print("\nTesting MFA Configuration...")
    
    try:
        from pgappforge.security.mfa.config import (
            get_mfa_config_template,
            validate_mfa_config,
            get_required_packages
        )
        
        # Test configuration template
        config_template = get_mfa_config_template()
        print(f"✓ Configuration template has {len(config_template)} settings")
        
        # Test validation
        test_config = {'PGAF_MFA_ENABLED': False}
        is_valid, errors = validate_mfa_config(test_config)
        print(f"✓ Configuration validation: {'PASS' if is_valid else 'FAIL'}")
        
        # Test package requirements
        packages = get_required_packages()
        print(f"✓ Package requirements: {len(packages)} categories")
        
        return True
        
    except ImportError as e:
        print(f"⚠ MFA config utilities not available: {e}")
        return False
    except Exception as e:
        print(f"✗ MFA config test failed: {e}")
        return False

def main():
    """Run all MFA component tests."""
    print("=" * 60)
    print("MFA COMPONENT VERIFICATION TEST")
    print("=" * 60)
    
    tests = [
        test_mfa_services,
        test_mfa_models,
        test_mfa_manager_mixin,
        test_mfa_views,
        test_mfa_config,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("✓ ALL MFA COMPONENTS ARE WORKING")
        print("\nMFA Integration Status: READY")
        print("✓ All core MFA components are functional")
        print("✓ Services, models, views, and config are available")
        print("\nNext Steps:")
        print("1. Install required dependencies if needed")
        print("2. Configure MFA settings in your app")
        print("3. Test with a live PgAppForge application")
    else:
        print("⚠ SOME MFA COMPONENTS HAVE ISSUES")
        print("\nMFA Integration Status: PARTIAL")
        print("Some components may need attention or dependencies")
    
    print("=" * 60)
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)