"""
Configuration Migration Tools.

CLI commands for migrating and managing tenant configuration encryption.
"""

import logging
import sys
from typing import List, Dict, Any

import click
from flask import current_app
from flask.cli import with_appcontext
from pgappforge import db

from ..models.tenant_models import TenantConfig
from ..security.config_encryption import ConfigEncryption, ConfigEncryptionError

log = logging.getLogger(__name__)


@click.group()
def config():
	"""Tenant configuration management commands."""
	pass


@config.command()
@with_appcontext
def encrypt_sensitive():
	"""Encrypt all sensitive tenant configurations that are currently in plain text."""
	
	try:
		# Initialize encryption system
		encryption = ConfigEncryption(current_app)
		
		# Find all sensitive configs that might need encryption
		sensitive_configs = TenantConfig.query.filter_by(is_sensitive=True).all()
		
		if not sensitive_configs:
			click.echo("✅ No sensitive configurations found.")
			return
		
		encrypted_count = 0
		error_count = 0
		already_encrypted_count = 0
		
		click.echo(f"🔍 Found {len(sensitive_configs)} sensitive configuration(s)...")
		
		for config in sensitive_configs:
			try:
				# Check if already encrypted
				if encryption.is_encrypted(str(config.config_value)):
					already_encrypted_count += 1
					continue
				
				# Get the current plain text value
				plain_value = config.config_value
				
				# Encrypt it
				click.echo(f"🔐 Encrypting {config.config_key} for tenant {config.tenant_id}...")
				config.set_sensitive_value(plain_value)
				
				encrypted_count += 1
				
			except Exception as e:
				error_count += 1
				click.echo(f"❌ Failed to encrypt {config.config_key} for tenant {config.tenant_id}: {e}")
				log.error(f"Encryption failed for config {config.id}: {e}")
		
		# Commit all changes
		if encrypted_count > 0:
			db.session.commit()
			click.echo(f"✅ Successfully encrypted {encrypted_count} configuration(s)")
		
		if already_encrypted_count > 0:
			click.echo(f"ℹ️  {already_encrypted_count} configuration(s) were already encrypted")
		
		if error_count > 0:
			click.echo(f"⚠️  {error_count} configuration(s) failed to encrypt")
			sys.exit(1)
		
		click.echo("🎉 Encryption migration completed successfully!")
		
	except ConfigEncryptionError as e:
		click.echo(f"❌ Encryption system error: {e}")
		sys.exit(1)
	except Exception as e:
		click.echo(f"❌ Migration failed: {e}")
		log.error(f"Config migration failed: {e}")
		sys.exit(1)


@config.command()
@with_appcontext
def verify_encryption():
	"""Verify that all sensitive configurations are properly encrypted."""
	
	try:
		encryption = ConfigEncryption(current_app)
		
		sensitive_configs = TenantConfig.query.filter_by(is_sensitive=True).all()
		
		if not sensitive_configs:
			click.echo("✅ No sensitive configurations found.")
			return
		
		encrypted_count = 0
		unencrypted_count = 0
		error_count = 0
		
		for config in sensitive_configs:
			try:
				if encryption.is_encrypted(str(config.config_value)):
					# Try to decrypt to verify it works
					decrypted = config.decrypted_value
					encrypted_count += 1
				else:
					click.echo(f"⚠️  Unencrypted sensitive config: {config.config_key} (tenant {config.tenant_id})")
					unencrypted_count += 1
			
			except Exception as e:
				click.echo(f"❌ Verification failed for {config.config_key} (tenant {config.tenant_id}): {e}")
				error_count += 1
		
		click.echo(f"\n📊 Encryption Status Report:")
		click.echo(f"   ✅ Encrypted: {encrypted_count}")
		click.echo(f"   ⚠️  Unencrypted: {unencrypted_count}")
		click.echo(f"   ❌ Errors: {error_count}")
		
		if unencrypted_count > 0 or error_count > 0:
			click.echo(f"\n💡 Run 'flask fab config encrypt-sensitive' to encrypt unencrypted configs")
			sys.exit(1)
		else:
			click.echo(f"\n🎉 All sensitive configurations are properly encrypted!")
		
	except Exception as e:
		click.echo(f"❌ Verification failed: {e}")
		sys.exit(1)


@config.command()
@click.option('--tenant-id', type=int, help='Specific tenant ID to audit')
@with_appcontext
def audit_config_security(tenant_id):
	"""Audit tenant configuration security posture."""
	
	try:
		query = TenantConfig.query
		if tenant_id:
			query = query.filter_by(tenant_id=tenant_id)
		
		all_configs = query.all()
		
		if not all_configs:
			click.echo("✅ No configurations found.")
			return
		
		# Categorize configs by sensitivity
		total_configs = len(all_configs)
		sensitive_configs = [c for c in all_configs if c.is_sensitive]
		non_sensitive_configs = [c for c in all_configs if not c.is_sensitive]
		
		# Check for potentially sensitive configs that aren't marked as sensitive
		potentially_sensitive_keys = [
			'password', 'secret', 'key', 'token', 'credential', 'auth',
			'api_key', 'private_key', 'oauth', 'stripe', 'webhook_secret'
		]
		
		potentially_sensitive = []
		for config in non_sensitive_configs:
			key_lower = config.config_key.lower()
			if any(keyword in key_lower for keyword in potentially_sensitive_keys):
				potentially_sensitive.append(config)
		
		# Report
		click.echo(f"📊 Configuration Security Audit Report")
		if tenant_id:
			click.echo(f"   🏢 Tenant ID: {tenant_id}")
		else:
			click.echo(f"   🌐 All Tenants")
		
		click.echo(f"\n📈 Overview:")
		click.echo(f"   Total Configurations: {total_configs}")
		click.echo(f"   🔐 Sensitive (encrypted): {len(sensitive_configs)}")
		click.echo(f"   📝 Non-sensitive: {len(non_sensitive_configs)}")
		
		if potentially_sensitive:
			click.echo(f"\n⚠️  Potentially Sensitive (not marked as sensitive):")
			for config in potentially_sensitive:
				click.echo(f"   - {config.config_key} (tenant {config.tenant_id})")
			click.echo(f"\n💡 Consider marking these as sensitive and re-running encryption")
		
		# Check encryption status for sensitive configs
		if sensitive_configs:
			encryption = ConfigEncryption(current_app)
			encrypted_count = 0
			for config in sensitive_configs:
				if encryption.is_encrypted(str(config.config_value)):
					encrypted_count += 1
			
			click.echo(f"\n🔒 Encryption Status:")
			click.echo(f"   ✅ Properly encrypted: {encrypted_count}/{len(sensitive_configs)}")
			
			if encrypted_count < len(sensitive_configs):
				click.echo(f"   ⚠️  Unencrypted sensitive configs: {len(sensitive_configs) - encrypted_count}")
		
		click.echo(f"\n✅ Audit completed!")
		
	except Exception as e:
		click.echo(f"❌ Audit failed: {e}")
		sys.exit(1)


@config.command()
@click.option('--config-key', required=True, help='Configuration key to mark as sensitive')
@click.option('--tenant-id', type=int, help='Specific tenant ID (optional - affects all tenants if not specified)')
@click.option('--encrypt-now', is_flag=True, help='Encrypt the value immediately after marking as sensitive')
@with_appcontext
def mark_sensitive(config_key, tenant_id, encrypt_now):
	"""Mark a configuration key as sensitive (requiring encryption)."""
	
	try:
		query = TenantConfig.query.filter_by(config_key=config_key)
		if tenant_id:
			query = query.filter_by(tenant_id=tenant_id)
		
		configs = query.all()
		
		if not configs:
			click.echo(f"❌ No configurations found for key '{config_key}'")
			if tenant_id:
				click.echo(f"   (checked tenant {tenant_id})")
			sys.exit(1)
		
		updated_count = 0
		for config in configs:
			if not config.is_sensitive:
				config.is_sensitive = True
				
				if encrypt_now:
					# Get current value and encrypt it
					current_value = config.config_value
					config.set_sensitive_value(current_value)
					click.echo(f"🔐 Marked and encrypted '{config_key}' for tenant {config.tenant_id}")
				else:
					click.echo(f"🏷️  Marked '{config_key}' as sensitive for tenant {config.tenant_id}")
				
				updated_count += 1
			else:
				click.echo(f"ℹ️  '{config_key}' already marked as sensitive for tenant {config.tenant_id}")
		
		if updated_count > 0:
			db.session.commit()
			click.echo(f"✅ Updated {updated_count} configuration(s)")
			
			if not encrypt_now:
				click.echo(f"💡 Run 'flask fab config encrypt-sensitive' to encrypt the values")
		
	except Exception as e:
		click.echo(f"❌ Failed to mark configuration as sensitive: {e}")
		sys.exit(1)


@config.command()
@with_appcontext
def encryption_status():
	"""Show encryption system status and configuration."""
	
	try:
		click.echo("🔐 Tenant Configuration Encryption Status")
		
		# Check if encryption is properly configured
		try:
			encryption = ConfigEncryption(current_app)
			click.echo("✅ Encryption system: Initialized")
			
			# Check for master key
			import os
			master_key = os.environ.get('PGAF_CONFIG_MASTER_KEY')
			if master_key:
				click.echo("✅ Master key: Configured via environment")
			else:
				click.echo("⚠️  Master key: Using development key (set PGAF_CONFIG_MASTER_KEY for production)")
			
		except ConfigEncryptionError as e:
			click.echo(f"❌ Encryption system: Failed to initialize - {e}")
			return
		
		# Count sensitive configurations
		total_sensitive = TenantConfig.query.filter_by(is_sensitive=True).count()
		click.echo(f"📊 Sensitive configurations: {total_sensitive}")
		
		if total_sensitive > 0:
			# Check encryption status
			encrypted_count = 0
			for config in TenantConfig.query.filter_by(is_sensitive=True):
				if encryption.is_encrypted(str(config.config_value)):
					encrypted_count += 1
			
			click.echo(f"🔒 Encrypted configurations: {encrypted_count}/{total_sensitive}")
			
			if encrypted_count < total_sensitive:
				click.echo(f"⚠️  {total_sensitive - encrypted_count} sensitive config(s) not encrypted")
				click.echo(f"💡 Run 'flask fab config encrypt-sensitive' to encrypt them")
		
		click.echo("\n🎯 Recommended Actions:")
		click.echo("1. Set PGAF_CONFIG_MASTER_KEY environment variable for production")
		click.echo("2. Run 'flask fab config audit-config-security' to check for unmarked sensitive configs") 
		click.echo("3. Run 'flask fab config encrypt-sensitive' to encrypt all sensitive configs")
		click.echo("4. Run 'flask fab config verify-encryption' to verify encryption status")
		
	except Exception as e:
		click.echo(f"❌ Status check failed: {e}")
		sys.exit(1)


# Register with Flask CLI
def init_config_commands(app):
	"""Initialize configuration management CLI commands."""
	app.cli.add_command(config)