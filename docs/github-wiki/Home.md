# pgappforge

[Home](Home)

pgappforge is a PostgreSQL-native rapid application development framework. It introspects a live PostgreSQL database and generates production-ready Flask web applications — models, views, REST APIs, mobile clients, and desktop shells — without requiring schema-first design.

Version 0.90.0 | Python 3.12+ | Flask 3.x | PostgreSQL 14+

---

## Feature Matrix

| Capability | Details |
|---|---|
| **Code Generator** | Generates models, views, REST APIs, mobile (React Native), desktop (Electron/Tauri) from live PG schema |
| **ERD Designer** | Cytoscape.js visual schema editor with DDL execution, AI suggestions, migration log |
| **Security Designer** | Graph-based RBAC editor with YAML export/import, health diagnostics, permission matrix |
| **Audit Trail** | `AuditMixin` — field-level diffs, hash chain, PII masking, GDPR `anonymize()` |
| **Data Hub** | Chunked CSV/Excel import/export, transformation pipelines |
| **Form Builder** | Drag-and-drop multi-step forms, conditional logic, public embed, custom field palette |
| **Realtime** | `pg_notify`-based WebSocket sync, live cursors, conflict resolution |
| **Integration Hub** | OAuth 2.0 / REST / GraphQL connectors; Stripe, Salesforce, HubSpot, Slack pre-built |
| **Schema Templates** | 62 bundled templates (FHIR R4, ISO 20022, GTFS, SCIM, and more) |
| **Actor Pattern** | Person/organisation playing roles — auto-detected from table comments |
| **Multi-tenancy** | Row-level security mixin, tenant-scoped views |
| **Auth Methods** | Database, LDAP, OAuth 2.0, OpenID, REMOTE_USER |

---

## Quick Navigation

| Section | Pages |
|---|---|
| **Getting Started** | [Installation](Installation) · [Quick Start](Quick-Start) |
| **Architecture** | [Architecture](Architecture) · [Code Generator](Code-Generator) |
| **Designers** | [ERD Designer](ERD-Designer) · [Security Designer](Security-Designer) |
| **Plugins** | [Audit Trail](Plugin-Audit-Trail) · [Data Hub](Plugin-Data-Hub) · [Form Builder](Plugin-Form-Builder) · [Realtime](Plugin-Realtime) · [Integration Hub](Plugin-Integration-Hub) |
| **Templates** | [Schema Templates](Schema-Templates) · [Business Templates](Business-Templates) · [Actor Pattern](Actor-Pattern) |
| **Reference** | [FAQ](FAQ) |

---

## See also

- [Installation](Installation)
- [Quick Start](Quick-Start)
- [Architecture](Architecture)
- [Schema Templates](Schema-Templates)
- [FAQ](FAQ)
