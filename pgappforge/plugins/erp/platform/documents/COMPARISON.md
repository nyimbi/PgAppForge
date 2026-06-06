# Document Management System — World-Class Comparison

## Our Implementation
- Upload with atomic version creation; full version history (version_number, checksum_sha256, is_current flag)
- PostgreSQL native full-text search via `tsvector`/`tsquery` with `ts_rank_cd` relevance ranking
- Fine-grained ACL: VIEW/COMMENT/EDIT/ADMIN per USER or ROLE, with optional expiry
- Cross-plugin attachment: any module can bind documents to its records via `(source_module, source_record_id)`
- BPM actions: `platform.documents.attach` and `platform.documents.request_signature` for workflow integration
- Recursive CTE folder tree (arbitrary depth) with per-entity scoping

**Integration points:** BPM workflow engine, E-Sign Portal (crm.sign), domain event bus

---

## Benchmark: Odoo Documents

| Feature | Ours | Odoo |
|---|---|---|
| Version history with checksums | ✓ | ✓ |
| Full-text search | ✓ (PG native) | ✓ (Elasticsearch optional) |
| Folder hierarchy | ✓ recursive CTE | ✓ |
| Role-based ACL with expiry | ✓ | ✓ |
| Kanban/board UI | ✗ | ✓ |
| PDF split/merge | ✗ | ✓ |
| Digital signing integration | ✓ (via crm.sign) | ✓ (Odoo Sign) |
| Cross-module record attachment | ✓ first-class | ✓ (chatter) |
| Spreadsheet editor | ✗ | ✓ |

## Benchmark: Google Drive Integration

| Feature | Ours | Google Drive |
|---|---|---|
| Real-time collaborative editing | ✗ | ✓ |
| External share links | ✗ | ✓ |
| MIME-type preview | ✗ (stored path only) | ✓ |
| Offline access | ✗ | ✓ |
| Native storage (no vendor lock-in) | ✓ | ✗ |
| ERP record binding | ✓ | ✗ |
| Transactional consistency (same DB txn) | ✓ | ✗ |

---

## Differentiation

**Where we exceed:**
- Transactional consistency: version creation, ACL grants, and event emission all occur in the same SQLAlchemy unit of work — no partial state possible
- BPM-first: documents are first-class workflow participants, not bolted-on attachments
- PostgreSQL FTS with weighted ranking (title > description) without external search infrastructure

**Remaining gaps:**
- No in-browser preview or editor (PDF, Office formats)
- No public share links or external guest access
- No storage backend abstraction (S3, GCS) — `file_path` is a bare string; callers manage storage
- No OCR or content extraction from scanned documents
