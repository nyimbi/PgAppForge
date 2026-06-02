# Platform Identity Plugin — SPEC

## Domain
`platform` — identity & access management

## Purpose
Provides SSO provider configuration, user session lifecycle, MFA device
management, and fine-grained ALLOW/DENY access policies.

## Entities

### IdentityProvider
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| name | VARCHAR(200) | |
| provider_type | VARCHAR(10) | SAML \| OIDC \| LDAP \| LOCAL |
| config | JSONB | provider-specific settings |
| is_default | BOOL | at most one default per tenant |
| is_active | BOOL | |
| created_at / updated_at | TIMESTAMPTZ | |

### UserSession
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| user_id | INT FK ab_user | |
| session_token | CHAR(64) UNIQUE | 64-char hex; store hashed in prod |
| ip_address | VARCHAR(45) | IPv4/IPv6 string |
| user_agent | TEXT | |
| started_at | TIMESTAMPTZ DEFAULT NOW() | |
| last_activity_at | TIMESTAMPTZ | sliding expiry basis |
| expires_at | TIMESTAMPTZ | hard expiry |
| mfa_verified | BOOL DEFAULT false | |
| is_active | BOOL | revocation flag |

### MFADevice
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| user_id | INT FK ab_user | |
| device_type | VARCHAR(10) | TOTP \| SMS \| EMAIL \| WEBAUTHN |
| device_name | VARCHAR(200) | user label |
| secret_encrypted | TEXT | KMS-encrypted seed/blob |
| is_primary | BOOL | exactly one per user; service-enforced |
| verified_at | TIMESTAMPTZ | NULL until first challenge passed |
| created_at / updated_at | TIMESTAMPTZ | |

### AccessPolicy
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| policy_name | VARCHAR(300) UNIQUE | |
| resource_type | VARCHAR(200) | model class or '*' |
| resource_id | VARCHAR(64) | NULL = all instances |
| principal_type | VARCHAR(10) | USER \| ROLE \| GROUP |
| principal_id | VARCHAR(64) | |
| permissions | TEXT[] | array of action strings |
| conditions | JSONB | JSONLogic expression |
| effect | VARCHAR(5) | ALLOW \| DENY |
| is_active | BOOL | |
| created_at / updated_at | TIMESTAMPTZ | |

## Business Rules
1. At most one default IdentityProvider per tenant.
2. Session expires_at must be in the future at creation.
3. Exactly one primary MFADevice per user (service-enforced, not DB constraint).
4. DENY effect overrides ALLOW for the same (principal, resource, action).
5. secret_encrypted: encryption is the caller's responsibility.
6. Implicit deny: if no policy matches, access is denied.

## Events Emitted
- `identity.provider.created / deactivated`
- `identity.session.started / expired`
- `identity.mfa.device_verified / challenge_failed`
- `identity.policy.created / changed`

## Events Consumed
None (platform-level; consumed by GRC controls for SoD re-evaluation).

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /identity/providers/ | List providers |
| POST | /identity/providers/ | Create provider |
| POST | /identity/providers/{id}/deactivate | Deactivate |
| POST | /identity/sessions/ | Create session |
| GET | /identity/sessions/{id}/validate | Validate + touch |
| POST | /identity/sessions/{id}/revoke | Revoke |
| POST | /identity/mfa/devices/ | Register MFA device |
| POST | /identity/mfa/devices/{id}/verify | Mark verified |
| GET | /identity/policies/ | List policies |
| POST | /identity/policies/ | Create policy |
| GET | /identity/policies/evaluate | Evaluate access |
| GET | /identity/reports/active-sessions | Active sessions by tenant |
| GET | /identity/reports/mfa-coverage | % users with verified MFA |
| GET | /identity/reports/policy-summary | Policy counts by effect |

## Rules Engine Rulesets (4)
1. `identity_provider.single_default` — one default per tenant
2. `user_session.expiry_required` — expires_at in future
3. `mfa_device.single_primary` — one primary device per user
4. `access_policy.deny_overrides_allow` — effect must be ALLOW or DENY

## Cross-plugin Composability
- **Upstream**: foundation
- **Downstream**: grc.controls (SoD re-evaluation on role changes)
