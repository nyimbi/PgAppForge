# PgAppForge — World-Class Open-Source ERP Platform

**Africa-first. SAP-depth. Fraction of the cost.**

**170 ERP modules · 10 domains · 3,800+ tests · Open source · Apache 2.0**

## What It Is

PgAppForge is a Flask-AppBuilder RAD framework with a full ERP layer: 170 assessed ERP modules, automatic CRUD, RBAC, SQLAlchemy models, REST surfaces, and a single PostgreSQL backend. It is PostgreSQL-native by design, with no Oracle or MySQL dependency in the ERP runtime.

PgAppForge is Africa-first: 8-country payroll, Kenya eTIMS, NLLB support for 60 African languages, Hyperion-X payments for M-Pesa, MTN MoMo, Airtel Money, and Flutterwave, denied-party screening, and embedded Ollama AI all live inside the same open platform.

## Module Inventory

| Domain | # Modules | Key Capabilities |
|---|---:|---|
| Analytics | 4 | `ai`, `cdp`, `operational`, `predictive` |
| CRM | 22 | `accounts`, `appointments`, `commerce`, `contacts`, `contracts`, `cpq`, `customer_portal`, `events`, `field_service`, `leads`, `loyalty`, `marketing`, `marketing_automation`, `opportunities`, `pos`, `prm`, `sales`, `service`, `service_contracts`, `sign`, `subscriptions`, `territory_management` |
| Finance | 23 | `ap`, `ap_automation`, `ar`, `assets`, `consolidation`, `credit_management`, `entities`, `fpa`, `gl`, `grants`, `hedge_accounting`, `intercompany`, `joint_venture`, `lease_accounting`, `material_ledger`, `multi_book`, `period_close`, `product_costing`, `profit_center`, `revenue_recognition`, `tax`, `tax_compliance`, `treasury` |
| GRC | 7 | `anti_bribery`, `controls`, `erm`, `ethics`, `privacy`, `sod`, `sustainability` |
| HCM | 23 | `analytics`, `benefits`, `compensation`, `contingent`, `equity_compensation`, `journeys`, `lms`, `lunch`, `org`, `payroll`, `performance`, `personnel`, `position_management`, `recruiting`, `referral`, `self_service`, `skills`, `talent`, `time`, `travel_expense`, `variable_pay`, `wellness`, `workforce_planning` |
| Industry | 25 | `agritech`, `clubs`, `consumer_goods`, `cybersecurity`, `education`, `energy`, `financial_contracts`, `financial_services`, `health`, `insurance`, `intl_aid`, `legal`, `life_sciences`, `manufacturing`, `media`, `nonprofit`, `oil_gas`, `procurement`, `public_sector`, `real_estate`, `research`, `smart_city`, `track_trace`, `utilities`, `water` |
| Operations | 17 | `assembly`, `capacity_scheduling`, `demand_planning`, `eam`, `fleet`, `inventory`, `lean`, `mrp`, `plm`, `process_manufacturing`, `production`, `quality`, `rental`, `repair`, `scm`, `transport`, `warehouse` |
| Platform | 36 | `analytics_engine`, `anomaly_detection`, `apg_bridge`, `audit_viewer`, `carbon`, `credentials`, `discuss`, `document_intelligence`, `documents`, `edi`, `education_platform`, `email`, `events`, `identity`, `ipaas`, `landing`, `mes`, `ml_predictions`, `nl_analytics`, `nlp`, `notifications`, `observability`, `predictions`, `process_mining`, `rag`, `regulatory_reporting`, `report_builder`, `row_security`, `scheduler`, `social`, `surveys`, `tenant_control`, `versioning`, `whatsapp`, `workflow_designer`, `workflow_launcher` |
| Procurement | 4 | `sourcing`, `spend_analytics`, `supplier_portal`, `trade_compliance` |
| Projects | 4 | `models.py`, `services.py`, `views.py`, `events.py` package capabilities |

## Africa-First Differentiators

- 8-country statutory payroll: KE, UG, TZ, GH, NG, ZA, RW, ET.
- KE eTIMS invoice compliance.
- NLLB 60 African language NLU.
- Hyperion-X payments: M-Pesa, MTN MoMo, Airtel Money, Flutterwave.
- Denied-party and sanctions screening.

## PgAppForge vs SAP/Oracle

| Feature | PgAppForge | SAP S/4HANA | Oracle Fusion |
|---|---|---|---|
| License cost | Open source core | Enterprise license | Enterprise subscription |
| Deploy time | Days to a working ERP | Long implementation program | Long implementation program |
| Database | Single PostgreSQL backend | SAP HANA | Oracle Database / Oracle Cloud |
| Africa payroll | Built-in 8-country payroll | Localization project | Localization project |
| AI inference | Local Ollama inference | SAP-managed AI services | Oracle-managed AI services |
| Source access | Full source access | Proprietary | Proprietary |

## Finance Standards

- IFRS 16 / ASC 842 lease accounting.
- IFRS 9 financial instruments.
- IAS 2 inventory costing.
- Decimal arithmetic throughout; no float for money.
- 9-test regression suite for finance arithmetic.

## Quick Start

```bash
git clone https://github.com/nyimbi/fab-ext
cd fab-ext
uv venv && source .venv/bin/activate && uv pip install -e .
flask fab create-admin
flask run
```

## AI Assistant

- 27 registered tools.
- Ollama ReAct loop with local inference.
- RBAC-gated per role.
- See [docs/dev_assistant.md](docs/dev_assistant.md).

## Development

- Run `pytest tests/ci` against real PostgreSQL; no mocks and no SQLite for ERP persistence behavior.
- See [docs/analysis-world-class-assessment.md](docs/analysis-world-class-assessment.md) for the full capability audit.

## License

Apache 2.0
