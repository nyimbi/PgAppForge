# Intercompany Posting — Competitive Comparison

## vs Microsoft Dynamics 365 Business Central (NAV) Intercompany

| Dimension | NAV Intercompany | PgAppForge IntercompanyPlugin |
|-----------|-----------------|------------------------------|
| **Architecture** | Separate IC partner setup; IC Inbox/Outbox journals per company | ICOutboxTransaction + ICInboxTransaction; same-DB atomic create; cross-DB via event bus |
| **Transaction types** | IC Sales Order, IC Purchase Order, IC General Journal | PO_MIRROR / SO_MIRROR / JOURNAL_MIRROR / PAYMENT_MIRROR |
| **Partner setup** | IC Partner card with GL account mapping | entity_id soft FK; mapping in document_data JSONB |
| **Outbox/Inbox model** | Per-company IC Inbox/Outbox journal queues | ic_outbox + ic_inbox tables; correlation_id links pair |
| **Auto-posting** | Manual accept or auto-accept per partner setup | accept_transaction() explicit; IC_AUTO_MIRROR_PO config for SCM trigger |
| **GL account mapping** | IC Chart of Accounts mapping per partner | GL mirror in _mirror_journal() reverses debit/credit; mapping in document_data |
| **Intercompany dimensions** | Supported via dimension mapping | entity_id + document_data JSONB for dimension payload |
| **Currency handling** | Multi-currency with exchange rate entry | document_data carries currency_code; conversion delegated to GL/AR plugins |
| **Reconciliation** | IC Reconciliation report (manual) | reconcile_ic_balances(): matched/unmatched + ICDivergenceDetectedEvent |
| **Divergence handling** | Manual journal correction | ICDivergenceDetectedEvent → downstream handler; manual correction flow |
| **Rejection** | Not natively supported (manual deletion) | reject_transaction() → REJECTED status + rejection_reason on outbox |
| **Audit trail** | G/L Entries + IC Inbox/Outbox history | DomainEventLog (emit_event) + ic_outbox/ic_inbox immutable status history |
| **Multi-company** | NAV company isolation (separate databases) | Same tenant, multiple entity_ids; cross-tenant via message queue extension |
| **Setup complexity** | High: IC partners, dimension mapping, GL mapping | Low: entity_id strings; document_data carries all payload |

### NAV IC features not in scope for v1
- Automatic dimension mapping between companies
- IC Allocation lines (cost allocation across companies)
- Cross-database IC (NAV handles via file/email or direct DB link)
- IC Customer/Vendor master synchronisation

---

## vs SAP S/4HANA Intercompany Posting

| Dimension | SAP Intercompany | PgAppForge IntercompanyPlugin |
|-----------|-----------------|------------------------------|
| **Framework** | ALE/IDoc + clearing accounts; ICM (Intercompany Matching) | ICOutboxTransaction/ICInboxTransaction + reconcile_ic_balances() |
| **Transaction types** | SD billing doc → FI posting; MM invoice → IC clearing | PO_MIRROR / SO_MIRROR / JOURNAL_MIRROR / PAYMENT_MIRROR |
| **Clearing accounts** | Mandatory: AR clearing (entity A) + AP clearing (entity B) | document_data carries account refs; GL plugin handles clearing |
| **Matching** | ICM: automated matching on amount + company code + period | reconcile_ic_balances(): correlation_id matching + amount comparison |
| **Tolerance** | Configurable tolerance in ICM | IC_RECONCILIATION_TOLERANCE_CENTS config (default 0) |
| **Elimination** | Consolidated elimination via EC-CS / S/4 Group Reporting | Out of scope; consolidation plugin would consume reconciliation events |
| **IDoc / EDI** | IDoc FIDCC1/FIDCC2 for cross-system IC | document_data JSONB — structured like IDoc segment but lighter; no EDI in v1 |
| **Cross-system IC** | Via ALE distribution model (separate SAP systems) | Same DB (one tenant); cross-tenant by extending send_transaction() with async queue |
| **Profit centre accounting** | PCA documents posted per IC transaction | entity_id maps to profit centre; extend document_data with profit_centre field |
| **Period lock** | IC transactions blocked in closed periods (FI period) | No period lock in v1; add check via GL plugin period status |
| **Netting** | IC netting via SAP In-House Cash | Out of scope; netting would aggregate payables/receivables across entities |
| **Audit / SOX** | Full change documents; segregation of duties | DomainEventLog + ICOutboxTransaction status history; SoD via GRC plugin |
| **Workflow** | SAP Business Workflow / Flexible Workflow | accept/reject explicit calls; BPM plugin for approval routing |
| **Currency** | Full multi-currency with translation and rounding | document_data carries amounts in cents + currency_code; FX via GL plugin |

### SAP IC features deferred to future iterations
- Cross-company stock transfer orders (STO) with billing
- Intercompany profit elimination (group reporting)
- IC netting and in-house cash
- Period-specific IC balance reporting by segment
- IDoc-compatible message format for SAP integration
