# Visual Security Designer

The Visual Security Designer is an interactive, graph-based UI embedded in PgAppForge
that lets administrators visualise, manage, and audit the entire role/permission topology
of a running application — without writing a single SQL query.

---

## Quick Start

Register the view during application setup:

```python
from pgappforge.views.security_designer import SecurityDesignerView

appbuilder.add_view(
    SecurityDesignerView,
    "Security Designer",
    icon="fa-shield",
    category="Security",
)
```

Navigate to `/security-designer/` in your browser while logged in as an Admin user.

---

## Features

### 1. Live Security Graph

A Cytoscape.js canvas renders every `Role` as a large coloured node and every
`ViewMenu` as a smaller satellite node. Directed edges represent individual
`PermissionView` assignments (e.g. `can_list`, `can_add`). The graph uses the
`fcose` force-directed layout — 60+ roles render without overlap.

### 2. Role Management

Click **+ Role** in the toolbar to create a new role. Select any role node in the
graph to reveal contextual actions in the right panel:

- **Delete Role** — removes the role (and all its permission assignments).
- **Add Permission** — grants a named permission on a view to the role.
- **Simulate Access** — lists every view the role can reach.

### 3. Permission Management

Click **+ Permission** to open a dialog and grant any arbitrary
`(role_id, view_name, permission_name)` triple. Click any edge (permission arrow)
in the graph to reveal a **Revoke** button in the right panel.

### 4. Permission Matrix

Switch to the **Matrix** tab in the left sidebar for a compact `Role × View` grid.
A check-mark indicates the role has at least one permission on that view. The matrix
auto-populates from the same `/api/graph` data used by the canvas.

### 5. YAML Export

Click **Export YAML** to download the complete role/permission/user assignment
configuration as a human-readable YAML document. The format is diff-friendly and
can be committed to version control.

### 6. YAML Import

Click **Import YAML** and paste a previously exported (or hand-authored) YAML
document. Enable **Dry run** to preview what would change without persisting
anything. The import is **idempotent and add-only** — it never deletes existing
roles or permissions.

### 7. Health Check

Click **Health Check** to run a three-rule diagnostic suite:

| Severity | Rule | Description |
|----------|------|-------------|
| critical | `no_admin_user` | No active user is assigned the Admin role |
| warning  | `empty_role` | A role exists with zero permissions |
| info     | `orphan_permission_view` | A PermissionView is assigned to no role |

Results are displayed in colour-coded cards inside a modal.

### 8. Role Templates

Click **Apply Template** to create (or augment) a role from one of five built-in
presets:

| Template | Description |
|----------|-------------|
| `Admin` | Full CRUD + menu access on all views |
| `Editor` | Create and update; no delete |
| `Viewer` | Read-only list + show |
| `API-only` | REST verbs only; no UI navigation |
| `Auditor` | Read-only; extra access to Security views |

Templates are applied against all currently registered `ViewMenu` entries.

#### Built-in template permission strings

| Template | `view_pattern` | Actions granted |
|----------|---------------|------------------|
| `Admin` | `*` (all views) | `can_list`, `can_show`, `can_add`, `can_edit`, `can_delete`, `menu_access` |
| `Editor` | `*` (all views) | `can_list`, `can_show`, `can_add`, `can_edit`, `menu_access` |
| `Viewer` | `*` (all views) | `can_list`, `can_show`, `menu_access` |
| `API-only` | `*` (all views) | `can_get`, `can_post`, `can_put`, `can_delete` |
| `Auditor` | `*` (all views) | `can_list`, `can_show` |
| `Auditor` | `Security*` | `can_list`, `can_show`, `menu_access` |

User-defined templates (via `FAB_SECURITY_ROLE_TEMPLATES`) follow the same schema:

```python
FAB_SECURITY_ROLE_TEMPLATES = {
    "DataScientist": {
        "label": "Data Scientist",
        "description": "Read access plus ability to run reports.",
        "permissions": [
            {"view_pattern": "*", "actions": ["can_list", "can_show"]},
            {"view_pattern": "Report*", "actions": ["can_list", "can_show", "can_add"]},
        ],
    }
}
```

### 9. Snapshots

Click **Snapshot** to capture the current security state (as a YAML blob) into
the `security_snapshot` database table. Click **Snapshots** to list all saved
snapshots. Each snapshot entry shows the capture timestamp and the user who
took it.

### 10. Diff

From the Snapshots list, click **Diff** next to any snapshot to compare it with
the current live state. The diff report shows:

- Roles added since the snapshot
- Roles removed since the snapshot
- Individual permission assignments added or removed

---

## YAML Format Reference

```yaml
roles:
  - name: Admin
    permissions:
      - view: UserModelView
        permission: can_list
      - view: UserModelView
        permission: can_add
      - view: RoleModelView
        permission: can_list
  - name: Viewer
    permissions:
      - view: UserModelView
        permission: can_list

users:
  - username: admin
    roles:
      - Admin
  - username: readonly_user
    roles:
      - Viewer
```

**Rules:**

- `roles[].name` — must be a non-empty string (max 64 chars, matches `ab_role.name`).
- `roles[].permissions[].view` — must match a registered `ViewMenu.name`.
- `roles[].permissions[].permission` — must match a registered `Permission.name`.
- `users` section is exported for reference only; import currently processes `roles` only.
- Import is **idempotent**: running the same YAML twice produces no duplicates.

---

## REST API Endpoint Reference

All endpoints are mounted under `/security-designer/` and require an authenticated
session. Access is gated by `_require_security_admin()`, which enforces that the
current user holds the Admin role (configured via `AUTH_ROLE_ADMIN`, default `'Admin'`).

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Serves the designer HTML page |
| `GET`  | `/api/graph` | Returns Cytoscape node/edge JSON |
| `POST` | `/api/roles` | Create a role `{name}` |
| `DELETE` | `/api/roles/<id>` | Delete a role by integer ID |
| `POST` | `/api/permissions` | Grant `{role_id, view_name, permission_name}` |
| `DELETE` | `/api/permissions/<pv_id>` | Revoke a PermissionView by ID |
| `GET`  | `/api/export/yaml` | Export all roles as YAML `{yaml: "..."}` |
| `POST` | `/api/import/yaml` | Import YAML `{yaml_text, dry_run}` |
| `GET`  | `/api/health-check` | Run health checks, return `{findings: [...]}` |
| `POST` | `/api/simulate` | List accessible views for `{role_id}` |
| `GET`  | `/api/templates` | List available template names |
| `POST` | `/api/templates/apply` | Apply template `{template_name, role_name}` |
| `POST` | `/api/snapshots` | Save snapshot `{name}` |
| `GET`  | `/api/snapshots` | List all snapshots |
| `GET`  | `/api/diff?snapshot_id=X` | Diff current state vs snapshot |

### `/api/graph` response shape

```json
{
  "nodes": [
    {"id": "role_1", "label": "Admin", "type": "role", "perm_count": 42},
    {"id": "view_UserModelView", "label": "UserModelView", "type": "view"}
  ],
  "edges": [
    {
      "id": "pv_17",
      "source": "role_1",
      "target": "view_UserModelView",
      "type": "permission",
      "perm_name": "can_list"
    }
  ]
}
```

### `/api/diff` response shape

```json
{
  "snapshot_id": 3,
  "roles_added": ["NewRole"],
  "roles_removed": [],
  "permissions_added": ["NewRole:can_list@UserModelView"],
  "permissions_removed": ["OldRole:can_delete@UserModelView"],
  "total_changes": 2
}
```

### `/api/health-check` finding shape

```json
{
  "findings": [
    {
      "severity": "critical",
      "rule": "no_admin_user",
      "message": "No active user is assigned the Admin role."
    }
  ]
}
```

---

## Database Model

The `SecuritySnapshot` model (`pgappforge/models/security_designer_models.py`) is
registered in the shared `Model` metadata and is created automatically when
`Base.metadata.create_all()` runs during application startup.

```
security_snapshot
  id            SERIAL PRIMARY KEY
  name          VARCHAR(255) NOT NULL
  description   VARCHAR(500)
  snapshot_json JSONB
  taken_at      TIMESTAMP NOT NULL  (UTC)
  taken_by_id   INTEGER REFERENCES ab_user(id) ON DELETE SET NULL
```

---

## Configuration

No additional configuration is required beyond registering the view. Optional
config keys:

| Key | Default | Description |
|-----|---------|-------------|
| `FAB_SECURITY_DESIGNER_ENABLED` | `True` | Set to `False` to disable the view entirely (not yet enforced — gate at registration) |
| `FAB_SECURITY_ROLE_TEMPLATES` | `{}` | Dict of user-defined role templates that extend the built-in 5. Keys are template names; values follow the same schema as `ROLE_TEMPLATES` (see below). User entries take priority over built-ins with the same key. |

---

---

## CSRF Requirements

All mutating endpoints (`POST`, `DELETE`) validate the `X-CSRFToken` request header.
The token is generated server-side via Flask-WTF and exposed in `window.SD_CONFIG.csrfToken`
on the designer page.

| Endpoint type | CSRF required |
|---------------|---------------|
| `GET` reads   | No |
| `POST` / `DELETE` mutations | Yes — include `X-CSRFToken: <token>` header |

If the header is missing or invalid the server returns `400 Bad Request`.
Flask-WTF must be installed; the server returns `500` if it is absent.

## Security Considerations

- All endpoints require the Admin role (configured via `AUTH_ROLE_ADMIN`, default
  `'Admin'`). The `_require_security_admin()` guard enforces this on every handler;
  `@has_access` is a secondary Flask-AppBuilder gate that requires a valid session.
- Destructive operations (role delete, permission revoke) require the same access
  level; there is no separate write permission today — add one via
  `appbuilder.security_manager.add_permission_view_menu("can_write", "SecurityDesignerView")`
  if finer-grained control is needed.
- The YAML import is add-only and never deletes; a malicious import cannot remove
  the Admin role or revoke permissions.
- Snapshots store the raw YAML — treat them as sensitive configuration data and
  restrict DB-level read access to the `security_snapshot` table accordingly.
