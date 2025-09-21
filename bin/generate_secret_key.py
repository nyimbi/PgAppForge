#!/usr/bin/env python3
"""
Secure secret key generator for Flask-AppBuilder applications.

This utility generates cryptographically secure secret keys suitable for
production use with Flask applications.

SECURITY NOTICE:
- Secret keys should NEVER be hardcoded in source code
- Always store secret keys in environment variables
- Use different keys for different environments
- Keys should be at least 32 characters long
- Keys should be random and unpredictable

Usage:
    python generate_secret_key.py [options]

Examples:
    # Generate a 64-character URL-safe key (recommended)
    python generate_secret_key.py

    # Generate a hex key
    python generate_secret_key.py --format hex

    # Generate a key with custom length
    python generate_secret_key.py --length 128

    # Generate multiple keys
    python generate_secret_key.py --count 3

    # Show environment variable export commands
    python generate_secret_key.py --export
"""

import argparse
import secrets
import sys
import os


def generate_secret_key(length=64, format_type='urlsafe'):
    """
    Generate a cryptographically secure secret key.

    Args:
        length: Length of the key (minimum 32)
        format_type: 'urlsafe', 'hex', or 'bytes'

    Returns:
        Secure random string suitable for use as SECRET_KEY
    """
    if length < 32:
        raise ValueError("Secret key must be at least 32 characters long for security")

    if format_type == 'urlsafe':
        return secrets.token_urlsafe(length)
    elif format_type == 'hex':
        return secrets.token_hex(length // 2)  # hex uses 2 chars per byte
    elif format_type == 'bytes':
        return secrets.token_bytes(length)
    else:
        raise ValueError("Format must be 'urlsafe', 'hex', or 'bytes'")


def validate_existing_key(key):
    """
    Validate an existing secret key for security compliance.

    Args:
        key: Secret key to validate

    Returns:
        Tuple of (is_valid, warnings)
    """
    warnings = []

    if not key:
        return False, ["Secret key is empty"]

    if len(key) < 32:
        warnings.append(f"Key length {len(key)} is below recommended minimum of 32 characters")

    # Check for common weak patterns
    weak_patterns = [
        'secret',
        'password',
        'key',
        'test',
        'dev',
        'demo',
        'example',
        '123',
        'abc',
        'thisismyscretkey'
    ]

    key_lower = key.lower()
    for pattern in weak_patterns:
        if pattern in key_lower:
            warnings.append(f"Key contains weak pattern: '{pattern}'")

    # Check for repeated characters
    if len(set(key)) < len(key) * 0.5:  # Less than 50% unique characters
        warnings.append("Key has too many repeated characters")

    is_valid = len(warnings) == 0
    return is_valid, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate secure secret keys for Flask-AppBuilder applications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--length', '-l',
        type=int,
        default=64,
        help='Length of the secret key (minimum 32, default: 64)'
    )

    parser.add_argument(
        '--format', '-f',
        choices=['urlsafe', 'hex', 'bytes'],
        default='urlsafe',
        help='Format of the generated key (default: urlsafe)'
    )

    parser.add_argument(
        '--count', '-c',
        type=int,
        default=1,
        help='Number of keys to generate (default: 1)'
    )

    parser.add_argument(
        '--export', '-e',
        action='store_true',
        help='Show export commands for setting environment variable'
    )

    parser.add_argument(
        '--validate',
        metavar='KEY',
        help='Validate an existing secret key for security compliance'
    )

    parser.add_argument(
        '--check-env',
        action='store_true',
        help='Check if SECRET_KEY environment variable is set and valid'
    )

    args = parser.parse_args()

    # Validate existing key
    if args.validate:
        is_valid, warnings = validate_existing_key(args.validate)
        print(f"Key validation: {'VALID' if is_valid else 'INVALID'}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        return 0 if is_valid else 1

    # Check environment variable
    if args.check_env:
        env_key = os.environ.get('SECRET_KEY')
        if not env_key:
            print("❌ SECRET_KEY environment variable is not set")
            print("Generate a key and set it:")
            print("  export SECRET_KEY=$(python generate_secret_key.py)")
            return 1

        is_valid, warnings = validate_existing_key(env_key)
        print(f"SECRET_KEY environment variable: {'✅ VALID' if is_valid else '❌ INVALID'}")
        if warnings:
            print("Issues found:")
            for warning in warnings:
                print(f"  ⚠️  {warning}")
            return 1
        return 0

    # Validate arguments
    if args.length < 32:
        print("ERROR: Secret key length must be at least 32 characters", file=sys.stderr)
        return 1

    if args.count < 1:
        print("ERROR: Count must be at least 1", file=sys.stderr)
        return 1

    try:
        # Generate keys
        keys = []
        for i in range(args.count):
            key = generate_secret_key(args.length, args.format)
            keys.append(key)

        # Output keys
        if args.count == 1:
            if args.export:
                print("# Set your secret key:")
                print(f"export SECRET_KEY='{keys[0]}'")
                print("")
                print("# Or for permanent setting, add to your ~/.bashrc or ~/.zshrc:")
                print(f"echo \"export SECRET_KEY='{keys[0]}'\" >> ~/.bashrc")
                print("")
                print("# For Docker environments:")
                print(f"docker run -e SECRET_KEY='{keys[0]}' your-app")
                print("")
                print("# For Python scripts:")
                print(f"os.environ['SECRET_KEY'] = '{keys[0]}'")
            else:
                print(keys[0])
        else:
            for i, key in enumerate(keys, 1):
                if args.export:
                    print(f"# Key {i}:")
                    print(f"export SECRET_KEY_{i}='{key}'")
                    print("")
                else:
                    print(f"Key {i}: {key}")

        if not args.export and args.count == 1:
            print("\n# To set this key:", file=sys.stderr)
            print(f"export SECRET_KEY='{keys[0]}'", file=sys.stderr)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())