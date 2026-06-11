"""
pgappforge/security/managers

FAB SecurityManager subclasses — one per auth provider.

Each subclass extends FAB's SecurityManager so that all existing views,
@has_access decorators, and permission auto-generation continue to work
unchanged while delegating to the configured external provider.

Usage::

  from pgappforge.security.providers import get_security_manager_class

  appbuilder = AppBuilder(app, db.session,
      security_manager_class=get_security_manager_class())

Or explicitly::

  from pgappforge.security.managers.keycloak_manager import KeycloakSecurityManager

  appbuilder = AppBuilder(app, db.session,
      security_manager_class=KeycloakSecurityManager)
"""
