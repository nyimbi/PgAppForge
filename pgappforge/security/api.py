from flask import request, Response
from typing import TYPE_CHECKING

# Use lazy import to avoid circular dependency with pgappforge.api
if TYPE_CHECKING:
    from pgappforge.api import BaseApi, safe
else:
    # Import BaseApi and safe at runtime to break circular import
    BaseApi = None
    safe = None

from pgappforge.const import (
    API_SECURITY_ACCESS_TOKEN_KEY,
    API_SECURITY_PROVIDER_DB,
    API_SECURITY_PROVIDER_LDAP,
    API_SECURITY_REFRESH_TOKEN_KEY,
    API_SECURITY_VERSION,
)
from pgappforge.security.schemas import login_post
from pgappforge.views import expose
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)
from marshmallow import ValidationError


def _get_base_api_class():
    """Get BaseApi class via lazy import to avoid circular dependency."""
    global BaseApi
    if BaseApi is None:
        from pgappforge.api import BaseApi as _BaseApi
        BaseApi = _BaseApi
    return BaseApi


def _get_safe_decorator():
    """Get safe decorator via lazy import to avoid circular dependency."""
    global safe
    if safe is None:
        from pgappforge.api import safe as _safe
        safe = _safe
    return safe


class SecurityApi:
    """Security API for authentication endpoints."""
    resource_name = "security"
    version = API_SECURITY_VERSION
    openapi_spec_tag = "Security"

    def __init__(self):
        # Dynamically inherit from BaseApi at runtime
        base_class = _get_base_api_class()
        self.__class__ = type(
            self.__class__.__name__,
            (base_class,),
            dict(self.__class__.__dict__)
        )
        # Initialize the base class
        if hasattr(base_class, '__init__'):
            base_class.__init__(self)

    def add_apispec_components(self, api_spec):
        super(SecurityApi, self).add_apispec_components(api_spec)
        jwt_scheme = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        api_spec.components.security_scheme("jwt", jwt_scheme)
        api_spec.components.security_scheme("jwt_refresh", jwt_scheme)

    @expose("/login", methods=["POST"])
    def login(self) -> Response:
        """Login endpoint for the API returns a JWT and optionally a refresh token
        ---
        post:
          description: >-
            Authenticate and get a JWT access and refresh token
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    username:
                      description: The username for authentication
                      example: admin
                      type: string
                    password:
                      description: The password for authentication
                      example: complex-password
                      type: string
                    provider:
                      description: Choose an authentication provider
                      example: db
                      type: string
                      enum:
                      - db
                      - ldap
                    refresh:
                      description: If true a refresh token is provided also
                      example: true
                      type: boolean
          responses:
            200:
              description: Authentication Successful
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      access_token:
                        type: string
                      refresh_token:
                        type: string
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            500:
              $ref: '#/components/responses/500'
        """
        # Apply safe decorator at runtime
        safe_decorator = _get_safe_decorator()
        actual_login = safe_decorator(self._login_impl)
        return actual_login()

    def _login_impl(self) -> Response:
        """Implementation of login functionality."""
        if not request.is_json:
            return self.response_400(message="Request payload is not JSON")
        try:
            login_payload = login_post.load(request.json)
        except ValidationError as error:
            return self.response_400(message=error.messages)

        # AUTH
        user = None
        if login_payload["provider"] == API_SECURITY_PROVIDER_DB:
            user = self.appbuilder.sm.auth_user_db(
                login_payload["username"], login_payload["password"]
            )
        elif login_payload["provider"] == API_SECURITY_PROVIDER_LDAP:
            user = self.appbuilder.sm.auth_user_ldap(
                login_payload["username"], login_payload["password"]
            )
        if not user:
            return self.response_401()

        # Identity can be any data that is json serializable
        resp = dict()
        resp[API_SECURITY_ACCESS_TOKEN_KEY] = create_access_token(
            identity=str(user.id), fresh=True
        )
        if "refresh" in login_payload and login_payload["refresh"]:
            resp[API_SECURITY_REFRESH_TOKEN_KEY] = create_refresh_token(
                identity=str(user.id)
            )
        return self.response(200, **resp)

    @expose("/refresh", methods=["POST"])
    @jwt_required(refresh=True)
    def refresh(self) -> Response:
        """
            Security endpoint for the refresh token, so we can obtain a new
            token without forcing the user to login again
        ---
        post:
          description: >-
            Use the refresh token to get a new JWT access token
          responses:
            200:
              description: Refresh Successful
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      access_token:
                        description: A new refreshed access token
                        type: string
            401:
              $ref: '#/components/responses/401'
            500:
              $ref: '#/components/responses/500'
          security:
            - jwt_refresh: []
        """
        # Apply safe decorator at runtime
        safe_decorator = _get_safe_decorator()
        actual_refresh = safe_decorator(self._refresh_impl)
        return actual_refresh()

    def _refresh_impl(self) -> Response:
        """Implementation of refresh functionality."""
        resp = {
            API_SECURITY_ACCESS_TOKEN_KEY: create_access_token(
                identity=get_jwt_identity(), fresh=False
            )
        }
        return self.response(200, **resp)