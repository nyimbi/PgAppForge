# Security Designer

[Home](Home) > Security Designer

The Visual Security Designer is a graph-based RBAC editor embedded in pgappforge. It lets administrators visualise, manage, and audit the entire role/permission topology of a running application — without writing SQL.

---

## Accessing the Designer

```python
from pgappforge.views.security_designer import SecurityDesignerView

appbuilder.add_view(
    SecurityDesignerView,
    "Security Designer",
    icon="fa-shield",
    category="Security",
)
```

Navigate to `/security-designer/`. Requires Admin role.

---

## Features

### Live Security Graph

A Cytoscape.js canvas (fcose force-directed layout) renders every `Role` as a large coloured node and every `ViewMenu` as a smaller satellite. Directed edges represent individual `PermissionView` assignments (`can_list`, `can_add`, etc.). Scales to 60+ roles without overlap.

### Role Management

- **+ Role** — create a new role.
- Click a role node → contextual panel with **Delete Role**, **Add Permission**, **Simulate Access** (lists every view the role can reach).

### Permission Management

- **+ Permission** — grant any `(role_id, view_name, permission_name)` triple.
- Click any permission edge → **Revoke** button appears in the right panel.

### Permission Matrix

Switch to the **Matrix** tab in the left sidebar for a compact Role × View grid. A check-mark indicates the role has at least one permission on that view.

### YAML Export

**Export YAML** downloads the complete role/permission/user assignment as a human-readable YAML document, suitable for version control and diff review.

### YAML Import

**Import YAML** accepts a previously exported (or hand-authored) YAML document.

- Enable **Dry run** to preview changes without persisting.
- Import is **idempotent and add-only** — it never deletes existing roles or permissions.

### Health Check

Runs a three-rule diagnostic suite:

| Severity | Rule | Description |
|---|---|---|
| critical | `no_admin_user` | No active user assigned to the Admin role |
| warning | `empty_role` | A role exists with zero permissions |
| info | `orphan_permission_view` | A PermissionView assigned to no role |

### Snapshot / Diff

Take a point-in-time snapshot of the permission topology. Compare two snapshots to see what changed between deployments.

---

## Security Model

All mutating endpoints require the Admin role. Read-only endpoints (graph load, export) require any authenticated role with view permission. CSRF validation is enforced on all JSON POST endpoints via `X-CSRFToken` header.

---

## Further Reading

Full technical reference: [docs/SECURITY_DESIGNER.md](../SECURITY_DESIGNER.md)

---

## See also

- [Architecture](Architecture)
- [ERD Designer](ERD-Designer)
- [FAQ — How do I add authentication?](FAQ)
- [Configuration Reference](../api/configuration.md)
- [Python API Reference](../api/python.md)
