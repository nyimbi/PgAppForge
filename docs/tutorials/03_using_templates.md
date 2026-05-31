# Tutorial 03: Applying Schema Templates

Templates are pre-designed database schemas that you apply to PostgreSQL and then generate an application from. This tutorial walks through selecting the CRM template, applying it to a database, and generating a running app from it.

## Prerequisites

- pgappforge installed: `pip install pgappforge`
- A PostgreSQL database you can write to: `createdb mycrm`

## Step 1 — List Available Templates

```bash
flask forge templates list
```

Sample output:

```
NAME                   SCHEMA             TABLES  SOURCE     TAGS
────────────────────────────────────────────────────────────────────────────────────
ap                     ap                     10  bundled    finance, ap, invoicing
ar                     ar                      8  bundled    finance, ar, invoicing
crm                    crm                    14  bundled    crm, sales, marketing
ecommerce              ecommerce              17  bundled    retail, ecommerce
gl                     gl                      9  bundled    finance, reporting
hrm                    hrm                    15  bundled    hr, payroll
inventory              inventory              13  bundled    supply-chain, logistics

21 template(s) available.
Run: flask forge templates info <name>  for details.
```

Filter by domain tag:

```bash
flask forge templates list --tag finance
```

## Step 2 — Inspect the CRM Template

```bash
flask forge templates info crm
```

```
────────────────────────────────────────────────────────────
  CRM (Customer Relationship Management)
────────────────────────────────────────────────────────────
  Name:        crm
  Schema:      crm
  Version:     1.0.0
  Description: Full-cycle CRM covering accounts, contacts, leads, opportunities,
               activities, tasks, campaigns, quotes, contracts, and support cases.
  Tags:        crm, sales, marketing

  Tables (14):
    • crm_account           (id, name, account_type, industry, website, ...)
    • crm_contact           (id, account_id, first_name, last_name, email, ...)
    • crm_lead              (id, first_name, last_name, company, email, ...)
    • crm_opportunity       (id, account_id, name, stage, amount, ...)
    • crm_activity          (id, subject, activity_type, due_date, ...)
    • crm_task              (id, subject, status, priority, ...)
    • crm_campaign          (id, name, campaign_type, status, ...)
    • crm_quote             (id, opportunity_id, quote_number, ...)
    • crm_contract          (id, account_id, contract_number, ...)
    • crm_case              (id, account_id, case_number, subject, ...)
    • (+ 4 more tables)
```

## Step 3 — Apply the Template to PostgreSQL

```bash
flask forge templates apply crm \
  --database-uri postgresql://localhost/mycrm
```

This creates the `crm` schema and all 14 tables (`IF NOT EXISTS` — safe to re-run):

```
Schema: crm
  ✓ Schema 'crm' ready
Applying 14 tables from 'crm' ...
  ✓ Applied 14 table(s) successfully.
```

To preview the DDL without executing:

```bash
flask forge templates apply crm \
  --database-uri postgresql://localhost/mycrm \
  --dry-run
```

## Step 4 — Generate the Application

```bash
flask forge gen all \
  --uri postgresql://localhost/mycrm \
  --name MyCRM \
  --output-dir ./mycrm_app/
```

The generator introspects the `crm` schema, detects the FK relationships between accounts → contacts → opportunities, and produces properly linked views.

## Step 5 — Run the App and Explore CRM Views

```bash
cd mycrm_app
pip install -r requirements.txt
flask fab create-admin --username admin --password admin --email admin@example.com
flask run
```

Open `http://127.0.0.1:5000`. The generated CRM app has:

**Accounts** (`/crmaccountmodelview/list/`)
Full account list with type, industry, and website. The detail view shows related contacts, opportunities, and open cases in sub-panels.

**Contacts** (`/crmcontactmodelview/list/`)
Linked to accounts via `account_id`. Add/edit forms include the account relationship picker. List view shows email, phone, and account name.

**Leads** (`/crmleadmodelview/list/`)
Unqualified prospects not yet linked to an account. The status column (`NEW`, `CONTACTED`, `QUALIFIED`, `DISQUALIFIED`) is displayed as a badge. Converting a lead to an opportunity creates the account/contact records automatically when you implement the `post_add` hook.

**Opportunities** (`/crmopportunitymodelview/list/`)
Pipeline view with stage, amount, and close date. The list can be sorted by amount to see the largest deals. Related quotes and activities appear in the detail view.

## What's Next

- Apply the `ar` template alongside `crm` and link the two schemas (the AR customer `account_number` maps to the CRM account) — see [Business Templates](../templates/business-templates.md)
- Add an audit trail so every pipeline stage change is tamper-evidently recorded — see [Tutorial 05](05_audit_and_compliance.md)
- Connect a Slack integration to fire a notification when an opportunity moves to `CLOSED_WON` — see [Tutorial 07](07_integration_hub.md)
