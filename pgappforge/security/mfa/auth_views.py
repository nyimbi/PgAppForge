"""
MFA-enhanced Authentication Views for PgAppForge.

This module provides enhanced authentication views that integrate
with the Multi-Factor Authentication system.
"""

import logging
from flask import flash, g, redirect, request, session, url_for
from pgappforge._compat import as_unicode
from pgappforge.security.decorators import no_cache
from pgappforge.security.views import AuthDBView as BaseAuthDBView
from pgappforge.utils.base import get_safe_redirect
from pgappforge.views import expose
from flask_babel import lazy_gettext
from flask_login import login_user

log = logging.getLogger(__name__)


class MFAEnabledAuthDBView(BaseAuthDBView):
    """
    Enhanced database authentication view with MFA support.
    
    This view extends the standard AuthDBView to handle MFA verification
    after successful password authentication.
    """
    
    @expose("/login/", methods=["GET", "POST"])
    @no_cache
    def login(self):
        """
        Handle login with MFA support.
        
        This method first performs standard username/password authentication,
        then redirects to MFA verification if required, or logs the user in
        directly if MFA is not required.
        """
        if g.user is not None and g.user.is_authenticated:
            return redirect(self.appbuilder.get_url_for_index)
            
        # Check if this is MFA verification step
        if session.get('mfa_user_id') and request.method == "GET":
            return redirect(url_for('MFAVerificationView.verify'))
        
        form = self.form()
        if form.validate_on_submit():
            next_url = get_safe_redirect(request.args.get("next", ""))
            
            # Attempt database authentication
            user = self.appbuilder.sm.auth_user_db(
                form.username.data, form.password.data
            )
            
            if not user:
                flash(as_unicode(self.invalid_login_message), "warning")
                return redirect(self.appbuilder.get_url_for_login_with(next_url))
            
            # Check if MFA is required for this user
            if hasattr(self.appbuilder.sm, 'is_mfa_required') and \
               (self.appbuilder.sm.is_mfa_required(user) or 
                self.appbuilder.sm.is_mfa_enabled_for_user(user)):
                
                # Store user info in session for MFA verification
                session['mfa_user_id'] = user.id
                session['mfa_username'] = user.username
                session['mfa_next_url'] = next_url or self.appbuilder.get_url_for_index
                
                flash(lazy_gettext("Please complete Multi-Factor Authentication"), "info")
                return redirect(url_for('MFAVerificationView.verify'))
            
            # No MFA required, log user in directly
            login_user(user, remember=False)
            return redirect(next_url or self.appbuilder.get_url_for_index)
        
        return self.render_template(
            self.login_template, 
            title=self.title, 
            form=form, 
            appbuilder=self.appbuilder
        )


class MFAAuthMixin:
    """
    Mixin to add MFA functionality to any authentication view.
    
    This mixin can be used to enhance existing authentication views
    with MFA support without completely replacing them.
    """
    
    def _handle_mfa_authentication(self, user, next_url=None):
        """
        Handle MFA authentication logic.
        
        Args:
            user: The authenticated user object
            next_url: URL to redirect to after successful authentication
            
        Returns:
            Flask response (redirect)
        """
        if not user:
            return None
            
        # Check if MFA is required
        if hasattr(self.appbuilder.sm, 'is_mfa_required') and \
           (self.appbuilder.sm.is_mfa_required(user) or 
            self.appbuilder.sm.is_mfa_enabled_for_user(user)):
            
            # Store user info in session for MFA verification
            session['mfa_user_id'] = user.id
            session['mfa_username'] = user.username
            session['mfa_next_url'] = next_url or self.appbuilder.get_url_for_index
            
            flash(lazy_gettext("Please complete Multi-Factor Authentication"), "info")
            return redirect(url_for('MFAVerificationView.verify'))
        
        # No MFA required, log user in directly
        login_user(user, remember=False)
        return redirect(next_url or self.appbuilder.get_url_for_index)


# Enhanced authentication views for different auth types
class MFAEnabledAuthLDAPView(MFAAuthMixin, BaseAuthDBView):
    """LDAP authentication view with MFA support."""
    pass


class MFAEnabledAuthOIDView(MFAAuthMixin, BaseAuthDBView):
    """OpenID authentication view with MFA support."""
    pass


class MFAEnabledAuthOAuthView(MFAAuthMixin, BaseAuthDBView):
    """OAuth authentication view with MFA support."""
    pass


class MFAEnabledAuthRemoteUserView(MFAAuthMixin, BaseAuthDBView):
    """Remote User authentication view with MFA support."""
    pass