# Strategic Sourcing Plugin — Design Comparison

## vs. Odoo Purchase (purchase.order + purchase.requisition)

| Dimension | Odoo | This plugin |
|---|---|---|
| RFQ concept | `purchase.order` in draft = RFQ | Explicit `RFQ` model with `rfq_type` (COMPETITIVE/SOLE_SOURCE/LIMITED) |
| Bid collection | No native multi-supplier bid comparison | `SupplierBid` per supplier; UniqueConstraint prevents duplicate bids |
| Evaluation | Manual price comparison in UI | Weighted composite scoring: price + quality + delivery |
| Bid deadline | Not enforced at model level | `submission_deadline` checked in `submit_bid()` |
| Award to PO | Manual conversion | `award_rfq()` calls `SCMService.create_purchase_order()` automatically |
| Evaluation criteria | None | JSONB `evaluation_criteria` per RFQ with configurable weight split |
| Multi-tenancy | Company-level | `tenant_id` UUID on every row |
| Events | Log note / activity | Domain events via `foundation.events` |

## vs. SAP SRM (Supplier Relationship Management) / Ariba

| Dimension | SAP Ariba | This plugin |
|---|---|---|
| RFx types | RFQ / RFP / RFI / Reverse Auction | RFQ with type=COMPETITIVE/SOLE_SOURCE/LIMITED |
| Scoring | Complex weighted scorecard with sub-criteria | Two-tier: price_score + technical_score + delivery_score, configurable weights |
| Supplier portal | Full self-service portal | Delegates to SupplierPortal plugin; `invited_suppliers` list on RFQ |
| Workflow | Multi-stage approval + committee scoring | BPMActionRegistry integration; evaluation callable from workflow |
| Award split | Partial award to multiple suppliers | Single winner; `award_rfq()` marks one bid AWARDED, rest REJECTED |
| Negotiation | Back-and-forth rounds | Not supported — submit_bid() is one-shot per supplier |
| PO integration | Native Ariba PO | Advisory call to SCM plugin; graceful degradation when SCM not loaded |

## Design decisions

### Evaluation formula
```
price_score   = (min_bid_price / this_bid_price) * 100   # 100 = lowest price, proportional
delivery_score = (1 / delivery_days) * 100                # 100 = 1-day, diminishing returns
composite = price_score * (price_w/100)
          + technical_score * (quality_w/100)
          + delivery_score * (delivery_w/100)
```
`technical_score` defaults to 50 when evaluators have not set it, giving a neutral
contribution. This prevents unscored bids from being artificially advantaged or penalised.

### Why JSONB for items and invited_suppliers?
RFQ line items mirror SCM requisition items — same structure, no independent lifecycle.
Storing them in JSONB avoids a second table and makes RFQ creation a single INSERT.
`invited_suppliers` is a list of UUIDs; the SupplierPortal plugin is optional.

### Why UniqueConstraint(rfq_id, supplier_id) on SupplierBid?
One bid per supplier per RFQ is the standard tender rule. `DuplicateBidError` is raised
instead of silently overwriting, which would risk losing a submitted price inadvertently.
Suppliers wanting to revise must go through a cancel-and-resubmit path (not yet implemented).

### SCM integration via best-effort import
`award_rfq()` attempts `SCMService.create_purchase_order()` in a try/except.
When SCM plugin is absent, `po_id=""` and the award still completes.
This keeps sourcing independently deployable.

### Deadline enforcement
`submission_deadline` is a `DateTime(timezone=True)` compared against `now(utc)`.
Server-side enforcement means deadline cannot be bypassed via client clock manipulation.

## Limitations / future work

- No bid revision / amendment round.
- No reverse auction (descending price rounds).
- No split award (percentage allocation across multiple suppliers).
- technical_score and commercial_score must be set by evaluators via direct DB update
  or a future `/evaluate` UI endpoint — no dedicated evaluation workflow yet.
- Invitation notifications to suppliers are not sent — that requires a notification plugin
  or email integration not included here.
- No approval workflow before publish (e.g. finance director sign-off on RFQ scope).
