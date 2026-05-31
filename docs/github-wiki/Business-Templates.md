# Business Templates

[Home](Home) > Business Templates

Seven of the 62 bundled templates cover the standard operational domains of a small-to-mid enterprise. These are the templates most likely to be applied together as a foundation for a line-of-business application.

---

## Operational Template Summary

| Template | Name | Tables | Key entities |
|---|---|---|---|
| `ar` | Accounts Receivable | 8 | customer, invoice, payment, credit_note, aging_bucket |
| `ap` | Accounts Payable | 10 | vendor, purchase_order, bill, payment_run, bank_account |
| `gl` | General Ledger | 9 | chart_of_accounts, journal_entry, period, cost_centre, trial_balance |
| `crm` | Customer Relationship Management | 12 | contact, lead, opportunity, activity, pipeline_stage |
| `hrm` | Human Resource Management | 15 | employee, position, department, payroll_run, leave_request |
| `inventory` | Inventory & Warehouse | 13 | product, warehouse, stock_movement, purchase_order, supplier |
| `ecommerce` | E-commerce | 17 | product, category, order, order_line, cart, shipment, review |

---

## Applying Multiple Templates

Each template deploys to its own PostgreSQL schema to avoid name collisions:

```bash
flask forge templates apply ar         --schema finance
flask forge templates apply ap         --schema finance
flask forge templates apply gl         --schema finance
flask forge templates apply crm        --schema sales
flask forge templates apply hrm        --schema hr
flask forge templates apply inventory  --schema ops
flask forge templates apply ecommerce  --schema store
```

After applying, run `flask forge gen all` pointed at each schema to generate the corresponding Flask views and API endpoints.

---

## Actor Patterns in Business Templates

| Template | Actor table | Actor type |
|---|---|---|
| `ar` | `customer` | Customer |
| `ap` | `vendor` | Vendor |
| `crm` | `contact` | Contact / Lead |
| `hrm` | `employee` | Employee |
| `ecommerce` | `customer` | Customer |

See [Actor Pattern](Actor-Pattern) for how the generator uses these declarations.

---

## Further Reading

Full reference: [docs/templates/business-templates.md](../templates/business-templates.md)

---

## See also

- [Schema Templates](Schema-Templates)
- [Actor Pattern](Actor-Pattern)
- [Code Generator](Code-Generator)
- [ERD Designer](ERD-Designer)
- [CLI Reference](../api/cli.md)
