"""pgappforge security integrations: Keycloak SSO and SpiceDB authorization."""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

from flask import Blueprint, redirect, request, session, url_for

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
	"""Convert an arbitrary name to a safe identifier (lowercase, hyphens)."""
	return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _permission_to_scope(permission_name: str) -> str:
	"""
	Map a FAB permission name like 'can_read' to a SpiceDB scope token.
	Strips the conventional 'can_' prefix when present.
	"""
	if permission_name.startswith("can_"):
		return permission_name[4:]
	return _slugify(permission_name)


# ===========================================================================
# KeycloakIntegration
# ===========================================================================

class KeycloakIntegration:
	"""
	Bridge between pgappforge RBAC and a Keycloak realm.

	Responsibilities
	----------------
	- Export the full role/permission graph as a Keycloak realm JSON blob so
	  the realm can be imported via the Keycloak admin REST API or the
	  ``keycloak-import`` CLI flag.
	- Sync Keycloak users back into the pgappforge ``ab_user`` table.
	- Produce a self-contained Flask Blueprint that handles the OIDC
	  authorization-code flow against a Keycloak server.

	All network calls use ``requests`` (optional dep); import errors are
	surfaced explicitly rather than hidden behind silent no-ops.
	"""

	def __init__(
		self,
		realm_name: str = "pgappforge",
		client_id: str = "pgappforge-client",
	) -> None:
		self.realm_name = realm_name
		self.client_id = client_id

	# ------------------------------------------------------------------
	# export_realm
	# ------------------------------------------------------------------

	def export_realm(self, appbuilder: Any) -> dict[str, Any]:
		"""
		Build a Keycloak realm representation from the live AppBuilder instance.

		The returned dict is valid JSON and can be POSTed to
		``POST /admin/realms`` on a Keycloak server or written to a file for
		offline import.

		Parameters
		----------
		appbuilder:
			The AppBuilder instance (provides ``appbuilder.sm`` – the security
			manager – where roles, permissions, and view-menus are stored).

		Returns
		-------
		dict
			Keycloak realm definition with:
			- ``roles.realm`` – one entry per FAB role
			- ``authorizationSettings.resources`` – one resource per
			  ViewMenu with scopes derived from its permissions
			- ``clients`` – a single confidential client stub
			- ``userFederationProviders`` – placeholder for LDAP/AD federation
		"""
		sm = appbuilder.sm

		# --- roles -------------------------------------------------------
		kc_roles: list[dict[str, Any]] = []
		for role in sm.get_all_roles():
			kc_roles.append({
				"name": role.name,
				"description": f"Imported from pgappforge role: {role.name}",
				"composite": False,
				"clientRole": False,
				"containerId": self.realm_name,
			})

		# --- resources (ViewMenu) + scopes (Permission) -------------------
		resources: list[dict[str, Any]] = []

		# Collect (view_menu_name -> set[permission_name]) mapping
		view_perms: dict[str, set[str]] = {}
		for pv in sm.get_all_permissions():
			if pv.view_menu is None or pv.permission is None:
				continue
			vm_name = pv.view_menu.name
			p_name = pv.permission.name
			view_perms.setdefault(vm_name, set()).add(p_name)

		for vm_name, perms in view_perms.items():
			scopes = [{"name": _permission_to_scope(p)} for p in sorted(perms)]
			resources.append({
				"name": vm_name,
				"type": "urn:pgappforge:resources:view",
				"ownerManagedAccess": False,
				"displayName": vm_name.replace("_", " "),
				"scopes": scopes,
				"attributes": {},
			})

		# --- role → resource-scope policies -------------------------------
		policies: list[dict[str, Any]] = []
		for role in sm.get_all_roles():
			associated_resources: list[str] = []
			for pv in role.permissions:
				if pv.view_menu:
					associated_resources.append(pv.view_menu.name)

			if associated_resources:
				policies.append({
					"name": f"{role.name}-policy",
					"type": "role",
					"logic": "POSITIVE",
					"decisionStrategy": "UNANIMOUS",
					"roles": [{"id": role.name, "required": False}],
					"resources": list(set(associated_resources)),
				})

		# --- client stub --------------------------------------------------
		client_def: dict[str, Any] = {
			"clientId": self.client_id,
			"name": self.client_id,
			"enabled": True,
			"clientAuthenticatorType": "client-secret",
			"redirectUris": ["*"],
			"webOrigins": ["+"],
			"standardFlowEnabled": True,
			"implicitFlowEnabled": False,
			"directAccessGrantsEnabled": False,
			"serviceAccountsEnabled": True,
			"authorizationServicesEnabled": True,
			"protocol": "openid-connect",
			"authorizationSettings": {
				"allowRemoteResourceManagement": False,
				"policyEnforcementMode": "ENFORCING",
				"resources": resources,
				"policies": policies,
				"decisionStrategy": "UNANIMOUS",
			},
		}

		# --- user federation placeholder ----------------------------------
		user_federation: list[dict[str, Any]] = [
			{
				"_comment": (
					"Placeholder: configure LDAP/AD provider here. "
					"See https://www.keycloak.org/docs/latest/server_admin/#_ldap"
				),
				"providerName": "ldap",
				"config": {
					"enabled": ["false"],
					"connectionUrl": ["ldap://ldap.example.com"],
					"bindDn": ["cn=admin,dc=example,dc=com"],
					"bindCredential": ["CHANGE_ME"],
					"usersDn": ["ou=users,dc=example,dc=com"],
					"userObjectClasses": ["inetOrgPerson, organizationalPerson"],
					"usernameLDAPAttribute": ["uid"],
					"rdnLDAPAttribute": ["uid"],
					"uuidLDAPAttribute": ["entryUUID"],
					"syncRegistrations": ["false"],
				},
			}
		]

		realm: dict[str, Any] = {
			"realm": self.realm_name,
			"enabled": True,
			"sslRequired": "external",
			"registrationAllowed": False,
			"loginWithEmailAllowed": True,
			"duplicateEmailsAllowed": False,
			"resetPasswordAllowed": True,
			"editUsernameAllowed": False,
			"bruteForceProtected": True,
			"roles": {
				"realm": kc_roles,
				"client": {self.client_id: []},
			},
			"clients": [client_def],
			"userFederationProviders": user_federation,
		}

		log.debug(
			"KeycloakIntegration.export_realm: %d roles, %d resources",
			len(kc_roles),
			len(resources),
		)
		return realm

	# ------------------------------------------------------------------
	# import_users_from_keycloak
	# ------------------------------------------------------------------

	def import_users_from_keycloak(
		self,
		realm_url: str,
		client_id: str,
		client_secret: str,
		*,
		appbuilder: Any | None = None,
		dry_run: bool = False,
	) -> int:
		"""
		Pull users from a live Keycloak realm and upsert them into the
		pgappforge ``ab_user`` table.

		The method obtains a service-account token via the
		``client_credentials`` grant, pages through
		``GET /admin/realms/{realm}/users``, then calls
		``appbuilder.sm.add_user()`` (or updates the existing record) for
		each Keycloak user.

		Parameters
		----------
		realm_url:
			Base URL of the realm, e.g.
			``https://keycloak.example.com/realms/pgappforge``.
		client_id:
			OAuth2 client with the ``view-users`` service-account role.
		client_secret:
			Corresponding client secret.
		appbuilder:
			AppBuilder instance.  When *None* the method is a no-op (useful
			in unit tests that only verify the HTTP plumbing).
		dry_run:
			When *True* perform all network calls but skip database writes;
			returns the count of users that *would* have been synced.

		Returns
		-------
		int
			Number of users successfully synced (created or updated).

		Raises
		------
		ImportError
			If ``requests`` is not installed.
		RuntimeError
			If the token endpoint or users endpoint returns a non-2xx status.
		"""
		try:
			import requests  # type: ignore[import-untyped]
		except ImportError as exc:
			raise ImportError(
				"KeycloakIntegration.import_users_from_keycloak requires "
				"the 'requests' package: pip install requests"
			) from exc

		# 1. Obtain service-account token -----------------------------------
		token_url = urljoin(realm_url.rstrip("/") + "/", "protocol/openid-connect/token")
		resp = requests.post(
			token_url,
			data={
				"grant_type": "client_credentials",
				"client_id": client_id,
				"client_secret": client_secret,
			},
			timeout=10,
		)
		if not resp.ok:
			raise RuntimeError(
				f"Keycloak token request failed {resp.status_code}: {resp.text}"
			)
		access_token: str = resp.json()["access_token"]
		headers = {"Authorization": f"Bearer {access_token}"}

		# 2. Derive admin API base from realm URL ----------------------------
		# realm_url pattern: https://host/realms/{realm}
		# admin API pattern: https://host/admin/realms/{realm}
		admin_url = re.sub(r"/realms/", "/admin/realms/", realm_url.rstrip("/"))
		users_url = f"{admin_url}/users"

		# 3. Page through all users -----------------------------------------
		synced = 0
		page_size = 100
		offset = 0

		while True:
			resp = requests.get(
				users_url,
				headers=headers,
				params={"first": offset, "max": page_size},
				timeout=10,
			)
			if not resp.ok:
				raise RuntimeError(
					f"Keycloak users fetch failed {resp.status_code}: {resp.text}"
				)
			batch: list[dict[str, Any]] = resp.json()
			if not batch:
				break

			for kc_user in batch:
				username: str = kc_user.get("username", "")
				email: str = kc_user.get("email", "")
				first_name: str = kc_user.get("firstName", "")
				last_name: str = kc_user.get("lastName", "")
				enabled: bool = kc_user.get("enabled", True)

				if not username or not email:
					log.warning(
						"KeycloakIntegration: skipping user with missing "
						"username/email: %s",
						kc_user.get("id"),
					)
					continue

				if not dry_run and appbuilder is not None:
					sm = appbuilder.sm
					existing = sm.find_user(username=username)
					if existing is None:
						sm.add_user(
							username=username,
							first_name=first_name or username,
							last_name=last_name or "",
							email=email,
							role=sm.find_role(sm.auth_role_public),
						)
						log.debug(
							"KeycloakIntegration: created user %s", username
						)
					else:
						existing.first_name = first_name or existing.first_name
						existing.last_name = last_name or existing.last_name
						existing.email = email
						existing.active = enabled
						sm.update_user(existing)
						log.debug(
							"KeycloakIntegration: updated user %s", username
						)

				synced += 1

			if len(batch) < page_size:
				break
			offset += page_size

		log.info(
			"KeycloakIntegration.import_users_from_keycloak: synced %d users "
			"(dry_run=%s)",
			synced,
			dry_run,
		)
		return synced

	# ------------------------------------------------------------------
	# keycloak_oauth_blueprint
	# ------------------------------------------------------------------

	def keycloak_oauth_blueprint(
		self,
		realm_url: str,
		client_id: str,
		client_secret: str,
		redirect_uri: str | None = None,
		*,
		post_login_endpoint: str = "index.index",
		post_logout_endpoint: str = "index.index",
	) -> Blueprint:
		"""
		Return a Flask Blueprint implementing Keycloak OIDC authorization-code
		flow.

		Endpoints
		---------
		``GET /auth/keycloak/login``
			Redirects the browser to Keycloak's authorization endpoint.
		``GET /auth/keycloak/callback``
			Receives the authorization code, exchanges it for tokens, creates
			or updates the local user session, then redirects to
			*post_login_endpoint*.
		``GET /auth/keycloak/logout``
			Clears the local session and redirects to Keycloak's end-session
			endpoint so the SSO session is also terminated.

		Parameters
		----------
		realm_url:
			Base URL of the Keycloak realm (no trailing slash).
		client_id / client_secret:
			OIDC client credentials.
		redirect_uri:
			Full callback URL registered in Keycloak.  When *None* the
			blueprint generates it at request time via ``url_for``.
		post_login_endpoint / post_logout_endpoint:
			Flask endpoint names (``blueprint.view_name``) to redirect to
			after successful login / logout.

		Returns
		-------
		Blueprint
			Register with ``app.register_blueprint(bp)``.

		Usage example::

			integration = KeycloakIntegration(realm_name="myrealm")
			bp = integration.keycloak_oauth_blueprint(
				realm_url="https://keycloak.example.com/realms/myrealm",
				client_id="my-client",
				client_secret="s3cr3t",
			)
			app.register_blueprint(bp)
		"""
		import secrets as _secrets

		try:
			import requests as _requests  # type: ignore[import-untyped]
		except ImportError as exc:
			raise ImportError(
				"keycloak_oauth_blueprint requires the 'requests' package: "
				"pip install requests"
			) from exc

		_realm_url = realm_url.rstrip("/")
		_authorize_url = f"{_realm_url}/protocol/openid-connect/auth"
		_token_url = f"{_realm_url}/protocol/openid-connect/token"
		_userinfo_url = f"{_realm_url}/protocol/openid-connect/userinfo"
		_end_session_url = f"{_realm_url}/protocol/openid-connect/logout"

		bp = Blueprint(
			"keycloak_oidc",
			__name__,
			url_prefix="/auth/keycloak",
		)

		@bp.route("/login")
		def login():  # type: ignore[return]
			state = _secrets.token_urlsafe(32)
			nonce = _secrets.token_urlsafe(32)
			session["oidc_state"] = state
			session["oidc_nonce"] = nonce

			cb = redirect_uri or url_for(
				"keycloak_oidc.callback", _external=True
			)
			params = "&".join([
				f"response_type=code",
				f"client_id={client_id}",
				f"redirect_uri={cb}",
				f"scope=openid+email+profile",
				f"state={state}",
				f"nonce={nonce}",
			])
			return redirect(f"{_authorize_url}?{params}")

		@bp.route("/callback")
		def callback():  # type: ignore[return]
			error = request.args.get("error")
			if error:
				log.warning("Keycloak OIDC error: %s", error)
				return redirect(url_for(post_login_endpoint))

			returned_state = request.args.get("state", "")
			expected_state = session.pop("oidc_state", None)
			if not expected_state or returned_state != expected_state:
				log.warning("Keycloak OIDC: state mismatch – possible CSRF")
				return redirect(url_for(post_login_endpoint))

			code = request.args.get("code")
			if not code:
				log.warning("Keycloak OIDC callback: missing code")
				return redirect(url_for(post_login_endpoint))

			cb = redirect_uri or url_for(
				"keycloak_oidc.callback", _external=True
			)
			token_resp = _requests.post(
				_token_url,
				data={
					"grant_type": "authorization_code",
					"client_id": client_id,
					"client_secret": client_secret,
					"redirect_uri": cb,
					"code": code,
				},
				timeout=10,
			)
			if not token_resp.ok:
				log.error(
					"Keycloak token exchange failed %d: %s",
					token_resp.status_code,
					token_resp.text,
				)
				return redirect(url_for(post_login_endpoint))

			tokens: dict[str, Any] = token_resp.json()
			access_token: str = tokens.get("access_token", "")
			id_token: str = tokens.get("id_token", "")

			userinfo_resp = _requests.get(
				_userinfo_url,
				headers={"Authorization": f"Bearer {access_token}"},
				timeout=10,
			)
			if not userinfo_resp.ok:
				log.error(
					"Keycloak userinfo fetch failed %d", userinfo_resp.status_code
				)
				return redirect(url_for(post_login_endpoint))

			userinfo: dict[str, Any] = userinfo_resp.json()

			session["keycloak_access_token"] = access_token
			session["keycloak_id_token"] = id_token
			session["keycloak_userinfo"] = userinfo
			session["keycloak_sub"] = userinfo.get("sub")

			log.info(
				"Keycloak OIDC login: sub=%s email=%s",
				userinfo.get("sub"),
				userinfo.get("email"),
			)
			return redirect(url_for(post_login_endpoint))

		@bp.route("/logout")
		def logout():  # type: ignore[return]
			id_token = session.pop("keycloak_id_token", None)
			session.pop("keycloak_access_token", None)
			session.pop("keycloak_userinfo", None)
			session.pop("keycloak_sub", None)

			# Build end-session URL so Keycloak also terminates the SSO cookie
			post_logout = url_for(post_logout_endpoint, _external=True)
			end_session = (
				f"{_end_session_url}"
				f"?post_logout_redirect_uri={post_logout}"
				f"&client_id={client_id}"
			)
			if id_token:
				end_session += f"&id_token_hint={id_token}"

			return redirect(end_session)

		return bp


# ===========================================================================
# SpiceDBIntegration
# ===========================================================================

class SpiceDBIntegration:
	"""
	Bridge between pgappforge RBAC and SpiceDB (authzed.com).

	Responsibilities
	----------------
	- Generate a SpiceDB schema (``definition`` blocks) from the live
	  AppBuilder view/permission graph.
	- Produce SpiceDB relationship tuples for every user→role→permission
	  assignment stored in the FAB database.
	- Write both schema and relationships to a running SpiceDB instance via
	  the authzed Python client (``pip install authzed``).

	SpiceDB schema conventions used here
	-------------------------------------
	Object types
		``user``   – maps to FAB User
		``role``   – maps to FAB Role
		``view_menu`` (one per FAB ViewMenu) – owns permission scopes

	Relations
		Each FAB Permission name becomes both a *relation* (who holds it) and
		a *permission* (can they exercise it).

	Relationship tuples
		``role:<role_name>#member@user:<username>``
		``view_menu:<vm_name>#<permission>@role:<role_name>#member``
	"""

	# ------------------------------------------------------------------
	# export_schema
	# ------------------------------------------------------------------

	def export_schema(self, appbuilder: Any) -> str:
		"""
		Return a SpiceDB schema string for all registered views and roles.

		The schema is deterministic (sorted) so it can be diff'd or stored in
		version control.

		Parameters
		----------
		appbuilder:
			AppBuilder instance providing ``appbuilder.sm``.

		Returns
		-------
		str
			SpiceDB schema text ready to be written via
			``WriteSchema`` / ``zed schema write``.

		Example output::

			definition user {}

			definition role {
			    relation member: user
			}

			definition view_menu_UserModelView {
			    relation admin: user | role#member
			    relation viewer: user | role#member
			    permission can_add = admin
			    permission can_delete = admin
			    permission can_edit = admin
			    permission can_list = viewer + admin
			    permission can_show = viewer + admin
			}
		"""
		sm = appbuilder.sm

		# Collect view_menu → permissions mapping
		view_perms: dict[str, set[str]] = {}
		for pv in sm.get_all_permissions():
			if pv.view_menu is None or pv.permission is None:
				continue
			vm_name = pv.view_menu.name
			p_name = pv.permission.name
			view_perms.setdefault(vm_name, set()).add(p_name)

		# Collect all role names
		all_roles = [r.name for r in sm.get_all_roles()]

		lines: list[str] = []

		# -- user --
		lines.append("definition user {}")
		lines.append("")

		# -- role --
		lines.append("definition role {")
		lines.append("\trelation member: user")
		lines.append("}")
		lines.append("")

		# -- one definition per ViewMenu --
		for vm_name in sorted(view_perms):
			type_name = _slugify(vm_name).replace("-", "_")
			perms = sorted(view_perms[vm_name])

			# Split permissions into write-like vs read-like heuristically
			write_perms = [p for p in perms if any(
				kw in p for kw in ("add", "edit", "delete", "create", "write", "import", "export")
			)]
			read_perms = [p for p in perms if p not in write_perms]

			lines.append(f"definition {type_name} {{")

			# Admin relation covers write ops; viewer covers read ops
			lines.append("\trelation admin: user | role#member")
			if read_perms:
				lines.append("\trelation viewer: user | role#member")

			for p in sorted(write_perms):
				scope = _permission_to_scope(p)
				lines.append(f"\tpermission {scope} = admin")

			for p in sorted(read_perms):
				scope = _permission_to_scope(p)
				lines.append(f"\tpermission {scope} = viewer + admin")

			lines.append("}")
			lines.append("")

		schema = "\n".join(lines)
		log.debug(
			"SpiceDBIntegration.export_schema: %d view definitions generated",
			len(view_perms),
		)
		return schema

	# ------------------------------------------------------------------
	# export_relationships
	# ------------------------------------------------------------------

	def export_relationships(
		self,
		appbuilder: Any,
		session: Any,
	) -> list[str]:
		"""
		Return SpiceDB relationship tuple strings for all user→role and
		role→view_menu assignments in the database.

		The tuples follow the SpiceDB/Authzed wire format::

			<object_type>:<object_id>#<relation>@<subject_type>:<subject_id>[#<subject_relation>]

		Parameters
		----------
		appbuilder:
			AppBuilder instance.
		session:
			Active SQLAlchemy session used to query the FAB security tables.

		Returns
		-------
		list[str]
			Sorted list of relationship tuple strings, deduplicated.
		"""
		sm = appbuilder.sm
		tuples: set[str] = set()

		# 1. user → role membership ----------------------------------------
		all_users = session.execute(
			__import__("sqlalchemy").select(sm.user_model)
		).scalars().all()

		for user in all_users:
			uid = user.username.replace(" ", "_")
			for role in user.roles:
				rid = _slugify(role.name).replace("-", "_")
				tuples.add(f"role:{rid}#member@user:{uid}")

		# 2. role → view_menu permission grants ----------------------------
		all_roles = sm.get_all_roles()
		for role in all_roles:
			rid = _slugify(role.name).replace("-", "_")
			for pv in role.permissions:
				if pv.view_menu is None or pv.permission is None:
					continue
				vm_type = _slugify(pv.view_menu.name).replace("-", "_")
				scope = _permission_to_scope(pv.permission.name)
				# Express as: view_menu type grants role#member the scope
				tuples.add(
					f"{vm_type}:{vm_type}#admin@role:{rid}#member"
				)
				# Also emit the viewer relation for read-type permissions
				if not any(
					kw in pv.permission.name
					for kw in ("add", "edit", "delete", "create", "write", "import", "export")
				):
					tuples.add(
						f"{vm_type}:{vm_type}#viewer@role:{rid}#member"
					)

		result = sorted(tuples)
		log.debug(
			"SpiceDBIntegration.export_relationships: %d tuples", len(result)
		)
		return result

	# ------------------------------------------------------------------
	# sync_to_spicedb
	# ------------------------------------------------------------------

	def sync_to_spicedb(
		self,
		endpoint: str,
		token: str,
		appbuilder: Any,
		session: Any,
	) -> dict[str, Any]:
		"""
		Write schema and relationships to a live SpiceDB instance.

		Uses the ``authzed`` Python client library
		(``pip install authzed grpcio``).  Both imports are guarded; a
		descriptive ``ImportError`` is raised when they are absent rather than
		failing silently.

		Parameters
		----------
		endpoint:
			gRPC target of the SpiceDB instance, e.g.
			``"grpc.authzed.com:443"`` or ``"localhost:50051"``.
		token:
			Pre-shared auth token / API key for the SpiceDB instance.
		appbuilder:
			AppBuilder instance.
		session:
			Active SQLAlchemy session (forwarded to
			:meth:`export_relationships`).

		Returns
		-------
		dict
			Summary with keys:
			- ``"schema_written"`` (bool) – schema write succeeded
			- ``"relationships_written"`` (int) – count of tuples written
			- ``"errors"`` (list[str]) – any non-fatal per-tuple errors

		Raises
		------
		ImportError
			When ``grpcio`` or ``authzed`` are not installed.
		RuntimeError
			On fatal gRPC errors (schema write failure, etc.).
		"""
		try:
			import grpc  # type: ignore[import-untyped]  # noqa: F401
		except ImportError as exc:
			raise ImportError(
				"SpiceDBIntegration.sync_to_spicedb requires grpcio: "
				"pip install grpcio"
			) from exc

		try:
			from authzed.api.v1 import (  # type: ignore[import-untyped]
				Client,
				Relationship,
				RelationshipUpdate,
				ObjectReference,
				SubjectReference,
				WriteRelationshipsRequest,
				WriteSchemaRequest,
				WriteSchemaResponse,
			)
			from grpc import ssl_channel_credentials  # type: ignore[import-untyped]
		except ImportError as exc:
			raise ImportError(
				"SpiceDBIntegration.sync_to_spicedb requires the authzed "
				"Python client: pip install authzed"
			) from exc

		result: dict[str, Any] = {
			"schema_written": False,
			"relationships_written": 0,
			"errors": [],
		}

		# Determine channel security from endpoint heuristic
		if endpoint.startswith("localhost") or endpoint.startswith("127."):
			creds = grpc.local_channel_credentials()
		else:
			creds = ssl_channel_credentials()

		client = Client(
			target=endpoint,
			credentials=creds,
			options={"bearer-token": token},
		)

		# 1. Write schema --------------------------------------------------
		schema_text = self.export_schema(appbuilder)
		try:
			client.WriteSchema(WriteSchemaRequest(schema=schema_text))
			result["schema_written"] = True
			log.info("SpiceDBIntegration: schema written to %s", endpoint)
		except Exception as exc:  # grpc.RpcError is the concrete type
			raise RuntimeError(
				f"SpiceDBIntegration: WriteSchema failed: {exc}"
			) from exc

		# 2. Write relationships -------------------------------------------
		raw_tuples = self.export_relationships(appbuilder, session)
		updates: list[RelationshipUpdate] = []

		for raw in raw_tuples:
			# Parse: object_type:object_id#relation@subject_type:subject_id[#sub_rel]
			try:
				obj_part, subj_part = raw.split("@", 1)
				obj_type_id, relation = obj_part.rsplit("#", 1)
				obj_type, obj_id = obj_type_id.split(":", 1)

				if "#" in subj_part:
					subj_type_id, subj_relation = subj_part.rsplit("#", 1)
				else:
					subj_type_id = subj_part
					subj_relation = ""

				subj_type, subj_id = subj_type_id.split(":", 1)

				subj_ref = SubjectReference(
					object=ObjectReference(object_type=subj_type, object_id=subj_id),
					optional_relation=subj_relation,
				)
				updates.append(
					RelationshipUpdate(
						operation=RelationshipUpdate.OPERATION_TOUCH,
						relationship=Relationship(
							resource=ObjectReference(object_type=obj_type, object_id=obj_id),
							relation=relation,
							subject=subj_ref,
						),
					)
				)
			except Exception as exc:
				msg = f"Failed to parse tuple '{raw}': {exc}"
				log.warning("SpiceDBIntegration: %s", msg)
				result["errors"].append(msg)

		if updates:
			# SpiceDB recommends batches ≤ 1000
			batch_size = 500
			written = 0
			for i in range(0, len(updates), batch_size):
				batch = updates[i : i + batch_size]
				try:
					client.WriteRelationships(
						WriteRelationshipsRequest(updates=batch)
					)
					written += len(batch)
				except Exception as exc:
					msg = f"Batch {i//batch_size} failed: {exc}"
					log.error("SpiceDBIntegration: %s", msg)
					result["errors"].append(msg)

			result["relationships_written"] = written
			log.info(
				"SpiceDBIntegration: wrote %d relationships to %s",
				written,
				endpoint,
			)

		return result


__all__ = ["KeycloakIntegration", "SpiceDBIntegration"]
