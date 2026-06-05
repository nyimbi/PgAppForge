# Configuring Access Control with the Security Designer

The Security Designer is a graph-based UI that lets administrators visualise
and manage the entire role/permission topology of a running PgAppForge
application. No SQL, no config file edits — changes are live immediately and
every state can be snapshotted and diffed.

---

## 1. Accessing the Security Designer

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

Navigate to `/security-designer/` while logged in as an **Admin** user. Any
user without the Admin role receives HTTP 403 — the `_require_security_admin()`
guard enforces this on every endpoint, with `@has_access` as a secondary
session check.

---

## 2. Understanding the Graph

The canvas renders the live security model fetched from
`GET /security-designer/api/graph`. Three node types appear:

| Node type | Colour | Represents |
|-----------|--------|------------|
| Role | Blue, large | A `ab_role` row (e.g. `Admin`, `Sales Manager`) |
| View/Permission | Green, small | A `ViewMenu` registered in the app |
| User (in Matrix) | Purple | A `ab_user` row (Matrix tab only) |

Directed edges go from a Role node to a ViewMenu node and are labelled with
the permission name (`can_list`, `can_add`, etc.). A role with 42 permissions
shows a `perm_count: 42` badge. The `fcose` force-directed layout handles
60+ roles without overlap.

The **Matrix** tab in the left sidebar shows the same data as a compact
`Role × View` grid — a checkmark means the role holds at least one permission
on that view.

---

## 3. Creating a Role

Click **+ Role** in the toolbar. Enter the role name — for example,
`Sales Manager` — and click **Create**.

The designer calls:

```
POST /security-designer/api/roles
Content-Type: application/json
X-CSRFToken: <token>

{"name": "Sales Manager"}
```

The new role node appears on the canvas immediately. To add permissions to it:

1. Click the `Sales Manager` node to select it.
2. In the right panel, click **+ Add Permission**.
3. In the dialog, choose:
   - **View**: `CustomerModelView`
   - **Permission**: `can_list`
4. Click **Grant**. Repeat for additional permissions.

To grant `can_read` on `CustomerView` and `can_write` on `OrderView` via the
REST API directly (useful for scripted setup):

```python
import requests, os

base = "http://localhost:8080/security-designer/api"
headers = {"X-CSRFToken": csrf_token, "Content-Type": "application/json"}

for view, perm in [("CustomerView", "can_list"), ("CustomerView", "can_show"),
                   ("OrderView", "can_add"), ("OrderView", "can_edit")]:
    requests.post(f"{base}/permissions", json={
        "role_id": sales_manager_id,
        "view_name": view,
        "permission_name": perm,
    }, headers=headers)
```

To revoke a permission, click its edge on the canvas. The right panel shows
the source role, target view, and permission name, plus a **Revoke** button
that calls `DELETE /api/permissions/<pv_id>`.

---

## 4. Using Role Templates

Templates give you a pre-wired permission set in one click. Click **Apply
Template** in the toolbar, then choose a template and a target role name.

The five built-in templates:

| Template | Permissions granted |
|----------|---------------------|
| `Admin` | `can_list`, `can_show`, `can_add`, `can_edit`, `can_delete`, `menu_access` on all views |
| `Editor` | `can_list`, `can_show`, `can_add`, `can_edit`, `menu_access` on all views |
| `Viewer` | `can_list`, `can_show`, `menu_access` on all views |
| `API-only` | `can_get`, `can_post`, `can_put`, `can_delete` on all views |
| `Auditor` | `can_list`, `can_show` on all views; plus `menu_access` on `Security*` views |

Templates are applied against all currently registered `ViewMenu` entries, so
adding a new view to your app and re-applying a template picks up the new view
automatically.

**Extending templates with custom presets** — add `FAB_SECURITY_ROLE_TEMPLATES`
to `config.py`. User-defined entries take priority over built-ins with the
same key:

```python
FAB_SECURITY_ROLE_TEMPLATES = {
    "SalesManager": {
        "label": "Sales Manager",
        "description": "Read access everywhere, write access on sales views.",
        "permissions": [
            {"view_pattern": "*",        "actions": ["can_list", "can_show"]},
            {"view_pattern": "Customer*", "actions": ["can_list", "can_show", "can_add", "can_edit"]},
            {"view_pattern": "Order*",    "actions": ["can_list", "can_show", "can_add", "can_edit"]},
        ],
    }
}
```

After restarting the app, `SalesManager` appears in the **Apply Template**
dropdown. Applying it to the `Sales Manager` role creates all matching
permission assignments in one request.

---

## 5. YAML Export and Import

### Exporting

Click **Export YAML** to download the complete role/permission/user
configuration. The file is diff-friendly and suitable for version control.

Example output:

```yaml
roles:
  - name: Sales Manager
    permissions:
      - view: CustomerModelView
        permission: can_list
      - view: CustomerModelView
        permission: can_show
      - view: OrderModelView
        permission: can_add
      - view: OrderModelView
        permission: can_edit

users:
  - username: alice
    roles:
      - Sales Manager
  - username: bob
    roles:
      - Viewer
```

Commit this file alongside your application code so RBAC changes are
reviewed in pull requests like any other config change.

### Importing

On a new deployment (staging environment, fresh container, post-restore):

1. Click **Import YAML** and paste the exported file content.
2. Toggle **Dry run** to preview what would be created without persisting anything.
3. Once satisfied, disable dry run and click **Import**.

The import is **idempotent and add-only**: running the same YAML twice creates
no duplicates, and it never deletes existing roles or permissions. A malicious
or corrupted import cannot remove the Admin role. The `users` section is
exported for reference but not processed during import — user-role assignments
are managed separately.

---

## 6. Taking and Comparing Snapshots

### Taking a snapshot

Before any significant permission change (adding a new module, restructuring
roles), capture the current state:

Click **Snapshot** in the toolbar, enter a name such as
`pre-sales-module-2026-06-01`, and click **Save**.

The designer calls `POST /api/snapshots` and stores a YAML blob in the
`security_snapshot` table:

```
security_snapshot
  id            3
  name          "pre-sales-module-2026-06-01"
  snapshot_json {… full YAML blob …}
  taken_at      2026-06-01 09:00:00 UTC
  taken_by_id   1   (admin user)
```

### Diffing snapshots

After making changes, click **Snapshots** in the toolbar to list saved
snapshots. Click **Diff** next to `pre-sales-module-2026-06-01`.

The diff compares the snapshot against the current live state from
`GET /api/diff?snapshot_id=3` and reports:

```json
{
  "snapshot_id": 3,
  "roles_added": ["Sales Manager"],
  "roles_removed": [],
  "permissions_added": [
    "Sales Manager:can_list@CustomerModelView",
    "Sales Manager:can_show@CustomerModelView",
    "Sales Manager:can_add@OrderModelView",
    "Sales Manager:can_edit@OrderModelView"
  ],
  "permissions_removed": [],
  "total_changes": 5
}
```

Diffs are displayed as colour-coded cards in a modal: green for additions,
red for removals. Use them during access reviews to demonstrate exactly what
changed between audit periods.

---

## 7. Running a Health Check

Click **Health Check** in the toolbar. The designer calls
`GET /api/health-check` which runs three SQL queries:

| Severity | Rule | What it detects |
|----------|------|-----------------|
| `critical` | `no_admin_user` | No active user is assigned the Admin role — the application is locked out |
| `warning` | `empty_role` | A role exists with zero permissions — likely a misconfiguration |
| `info` | `orphan_permission_view` | A `PermissionView` row is assigned to no role — dead weight in the permission table |

Results appear in colour-coded cards inside a modal. A clean system shows no
findings. A `critical` finding should be resolved immediately — assign or
create an Admin user before any other work.

Example finding JSON from the API:

```json
{
  "findings": [
    {
      "severity": "warning",
      "rule": "empty_role",
      "message": "Role 'Sales Manager' has no permissions assigned."
    },
    {
      "severity": "info",
      "rule": "orphan_permission_view",
      "message": "PermissionView id=88 (can_export @ ReportView) is assigned to no role."
    }
  ]
}
```

Run health checks routinely — after imports, after template applications, and
before production deployments.

---

## 8. Security Model Best Practices

**Principle of least privilege.** Start with the `Viewer` template and add
permissions incrementally. Roles with broad `Admin`-level access should be
reserved for application administrators, not operational users.

**Snapshot before changes.** Take a named snapshot before every significant
permission change. The diff report gives you an instant audit trail without
querying the database directly.

**YAML in source control.** Export YAML after each configuration change and
commit it. This gives you a reviewable history of who had access to what, and
lets you reproduce the permission state on a fresh deployment with a single
import.

**Finer-grained write control.** By default, any Admin can mutate permissions.
If you need a separate "Security Admin" role that can write to the designer
without full application Admin access, add a custom permission:

```python
appbuilder.security_manager.add_permission_view_menu(
    "can_write", "SecurityDesignerView"
)
```

Then gate write endpoints on this permission in addition to the session check.

**Treat snapshots as sensitive data.** The `security_snapshot` table stores
raw YAML including all role and permission names. Restrict PostgreSQL
row-level access to this table to Admin database users only.

**Validate imports in dry-run first.** Always preview a YAML import with
**Dry run** enabled before applying it. The preview shows exactly which roles
and permissions would be created — confirm it matches expectations before
committing.
