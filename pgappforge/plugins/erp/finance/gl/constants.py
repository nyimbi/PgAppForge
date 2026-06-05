"""Standard GL account codes for PgAppForge ERP.

These are DEFAULT codes. Override per-tenant via the cb_gl_mapping table.
Import these constants instead of using string literals in plugin services.

Usage::

    from pgappforge.plugins.erp.finance.gl.constants import (
        CASH_AND_NOSTRO,
        AR_CONTROL,
        SALARIES_AND_WAGES,
    )

    lines = [
        {"account_code": CASH_AND_NOSTRO, "debit_cents": 100_000, "credit_cents": 0},
        {"account_code": AR_CONTROL,      "debit_cents": 0,        "credit_cents": 100_000},
    ]

All codes correspond to rows documented in CHART_OF_ACCOUNTS.md.
Each plugin that posts to GL should resolve codes through _resolve_gl() to
honour per-tenant overrides stored in the cb_gl_mapping table.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Assets — Cash & Liquid
# ---------------------------------------------------------------------------

CASH_AND_NOSTRO: str = "1011"
"""Primary cash / bank clearing accounts; core banking settlement ledger,
treasury bank accounts, and CB nostro accounts."""

PETTY_CASH_FLOAT: str = "1013"
"""Petty cash advances and small cash disbursements."""

# ---------------------------------------------------------------------------
# Assets — Receivables
# ---------------------------------------------------------------------------

AR_CONTROL: str = "1200"
"""Accounts Receivable control account.  AR sub-ledger total;
debited on invoice issuance, credited on cash receipt."""

ADVANCE_RECEIVABLE: str = "1300"
"""Travel cash advances disbursed to employees.
Debited when advance is disbursed; credited when expense report is approved."""

INTERCO_RECEIVABLE: str = "1400"
"""Intercompany receivable.  Amounts owed by related entities within the group."""

# ---------------------------------------------------------------------------
# Assets — Inventory
# ---------------------------------------------------------------------------

INVENTORY: str = "1140"
"""Raw materials inventory.  Debited on goods receipt, credited on
goods issue / cost of sales recognition."""

INVENTORY_IN_TRANSIT: str = "1150"
"""Goods on shipment not yet received at destination warehouse."""

WIP: str = "1160"
"""Work in Progress.  Production orders in progress; materials issued to floor."""

FINISHED_GOODS: str = "1170"
"""Finished goods.  Completed production orders transferred from WIP."""

# ---------------------------------------------------------------------------
# Assets — Other Current
# ---------------------------------------------------------------------------

PREPAID_EXPENSES: str = "1500"
"""Prepaid insurance, rent, subscriptions."""

PREPAID_TAX: str = "1510"
"""Withholding tax credits, instalment tax prepayments."""

VAT_RECOVERABLE: str = "1520"
"""Input VAT claimable on purchases."""

ACCRUED_INCOME: str = "1560"
"""Revenue earned but not yet invoiced; reversed on invoice issuance."""

# ---------------------------------------------------------------------------
# Assets — Non-Current
# ---------------------------------------------------------------------------

FIXED_ASSETS_COST: str = "1600"
"""Property, Plant & Equipment at cost.  Managed by finance.assets plugin.
Also used for IFRS 16 right-of-use asset recognition."""

ACCUMULATED_DEPRECIATION: str = "1610"
"""Accumulated depreciation — contra-asset account.
Credited by periodic depreciation runs."""

# ---------------------------------------------------------------------------
# Liabilities — Current
# ---------------------------------------------------------------------------

AP_CONTROL: str = "2000"
"""Accounts Payable control account.  AP sub-ledger total;
credited on supplier invoice receipt, debited on payment."""

ACCRUED_EXPENSES: str = "2100"
"""General period-end accruals not yet invoiced by suppliers."""

ACCRUED_SALARIES: str = "2110"
"""Payroll accrual — unpaid salary at period end."""

ACCRUED_LEAVE: str = "2120"
"""Annual leave liability balance."""

VAT_PAYABLE: str = "2200"
"""Output VAT collected from customers; remitted on VAT return filing."""

WITHHOLDING_TAX_PAYABLE: str = "2250"
"""Withholding tax deducted from supplier payments; remitted to KRA."""

PAYE_PAYABLE: str = "2300"
"""Employee PAYE income tax withheld from payroll; monthly KRA remittance."""

NSSF_SHIF_PAYABLE: str = "2310"
"""Statutory pension and health deductions — employee and employer portions
(NSSF Tier I/II and SHIF).  Remitted to NSSF/SHA monthly."""

CUSTOMER_DEPOSITS: str = "2400"
"""Advance payments received from customers before service delivery.
Released to revenue on delivery / milestone achievement."""

LEASE_LIABILITY: str = "2500"
"""IFRS 16 lease liability — present value of future lease payments.
Managed by CLM plugin's calculate_lease_schedule()."""

# ---------------------------------------------------------------------------
# Equity
# ---------------------------------------------------------------------------

RETAINED_EARNINGS: str = "3200"
"""Retained earnings / accumulated surplus.
Debited/credited on period close transfer from P&L."""

# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

REVENUE_SERVICES: str = "4000"
"""Primary service revenue.  T&M and fixed-fee project invoices,
retainer fees, professional services billing."""

REVENUE_GOODS: str = "4100"
"""Product sales revenue.  Goods invoiced to customers."""

REVENUE_SUBSCRIPTIONS: str = "4150"
"""Recurring subscription revenue; straight-line recognition."""

INTEREST_INCOME: str = "4200"
"""Bank interest earned; treasury income on deposits and nostro balances."""

FX_GAIN: str = "4300"
"""Foreign exchange revaluation gains and FX deal settlement gains."""

OTHER_INCOME: str = "4500"
"""Miscellaneous income — grants, penalties received, sundry."""

# ---------------------------------------------------------------------------
# Expenses — Cost of Sales
# ---------------------------------------------------------------------------

COGS: str = "5100"
"""Cost of Goods Sold.  Inventory consumption matched to goods revenue."""

DIRECT_LABOUR: str = "5200"
"""Direct labour cost applied to projects and production orders."""

FX_LOSS: str = "5500"
"""Foreign exchange revaluation losses and FX deal settlement losses."""

FINANCE_CHARGES: str = "5600"
"""Loan interest, bank charges, IFRS 16 interest on lease liability."""

# ---------------------------------------------------------------------------
# Expenses — Operating
# ---------------------------------------------------------------------------

SALARIES_AND_WAGES: str = "6100"
"""Net pay — posted by payroll run (gross pay minus all deductions)."""

EMPLOYER_STATUTORY: str = "6200"
"""Employer statutory contributions — NSSF employer match, Housing Levy
employer portion, NITA levy."""

TRAVEL_AND_ENTERTAINMENT: str = "6300"
"""Approved travel expense reports, per-diem, accommodation, conference fees."""

MILEAGE_CLAIMS: str = "6350"
"""Vehicle mileage reimbursements to employees."""

DEPRECIATION_EXPENSE: str = "6400"
"""Periodic depreciation expense charged to P&L by the assets plugin."""


# ---------------------------------------------------------------------------
# Convenience mapping: default_code → constant name (for tooling / docs)
# ---------------------------------------------------------------------------

ALL_CODES: dict[str, str] = {
	CASH_AND_NOSTRO: "CASH_AND_NOSTRO",
	PETTY_CASH_FLOAT: "PETTY_CASH_FLOAT",
	AR_CONTROL: "AR_CONTROL",
	ADVANCE_RECEIVABLE: "ADVANCE_RECEIVABLE",
	INTERCO_RECEIVABLE: "INTERCO_RECEIVABLE",
	INVENTORY: "INVENTORY",
	INVENTORY_IN_TRANSIT: "INVENTORY_IN_TRANSIT",
	WIP: "WIP",
	FINISHED_GOODS: "FINISHED_GOODS",
	PREPAID_EXPENSES: "PREPAID_EXPENSES",
	PREPAID_TAX: "PREPAID_TAX",
	VAT_RECOVERABLE: "VAT_RECOVERABLE",
	ACCRUED_INCOME: "ACCRUED_INCOME",
	FIXED_ASSETS_COST: "FIXED_ASSETS_COST",
	ACCUMULATED_DEPRECIATION: "ACCUMULATED_DEPRECIATION",
	AP_CONTROL: "AP_CONTROL",
	ACCRUED_EXPENSES: "ACCRUED_EXPENSES",
	ACCRUED_SALARIES: "ACCRUED_SALARIES",
	ACCRUED_LEAVE: "ACCRUED_LEAVE",
	VAT_PAYABLE: "VAT_PAYABLE",
	WITHHOLDING_TAX_PAYABLE: "WITHHOLDING_TAX_PAYABLE",
	PAYE_PAYABLE: "PAYE_PAYABLE",
	NSSF_SHIF_PAYABLE: "NSSF_SHIF_PAYABLE",
	CUSTOMER_DEPOSITS: "CUSTOMER_DEPOSITS",
	LEASE_LIABILITY: "LEASE_LIABILITY",
	RETAINED_EARNINGS: "RETAINED_EARNINGS",
	REVENUE_SERVICES: "REVENUE_SERVICES",
	REVENUE_GOODS: "REVENUE_GOODS",
	REVENUE_SUBSCRIPTIONS: "REVENUE_SUBSCRIPTIONS",
	INTEREST_INCOME: "INTEREST_INCOME",
	FX_GAIN: "FX_GAIN",
	OTHER_INCOME: "OTHER_INCOME",
	COGS: "COGS",
	DIRECT_LABOUR: "DIRECT_LABOUR",
	FX_LOSS: "FX_LOSS",
	FINANCE_CHARGES: "FINANCE_CHARGES",
	SALARIES_AND_WAGES: "SALARIES_AND_WAGES",
	EMPLOYER_STATUTORY: "EMPLOYER_STATUTORY",
	TRAVEL_AND_ENTERTAINMENT: "TRAVEL_AND_ENTERTAINMENT",
	MILEAGE_CLAIMS: "MILEAGE_CLAIMS",
	DEPRECIATION_EXPENSE: "DEPRECIATION_EXPENSE",
}

__all__ = [
	"CASH_AND_NOSTRO",
	"PETTY_CASH_FLOAT",
	"AR_CONTROL",
	"ADVANCE_RECEIVABLE",
	"INTERCO_RECEIVABLE",
	"INVENTORY",
	"INVENTORY_IN_TRANSIT",
	"WIP",
	"FINISHED_GOODS",
	"PREPAID_EXPENSES",
	"PREPAID_TAX",
	"VAT_RECOVERABLE",
	"ACCRUED_INCOME",
	"FIXED_ASSETS_COST",
	"ACCUMULATED_DEPRECIATION",
	"AP_CONTROL",
	"ACCRUED_EXPENSES",
	"ACCRUED_SALARIES",
	"ACCRUED_LEAVE",
	"VAT_PAYABLE",
	"WITHHOLDING_TAX_PAYABLE",
	"PAYE_PAYABLE",
	"NSSF_SHIF_PAYABLE",
	"CUSTOMER_DEPOSITS",
	"LEASE_LIABILITY",
	"RETAINED_EARNINGS",
	"REVENUE_SERVICES",
	"REVENUE_GOODS",
	"REVENUE_SUBSCRIPTIONS",
	"INTEREST_INCOME",
	"FX_GAIN",
	"OTHER_INCOME",
	"COGS",
	"DIRECT_LABOUR",
	"FX_LOSS",
	"FINANCE_CHARGES",
	"SALARIES_AND_WAGES",
	"EMPLOYER_STATUTORY",
	"TRAVEL_AND_ENTERTAINMENT",
	"MILEAGE_CLAIMS",
	"DEPRECIATION_EXPENSE",
	"ALL_CODES",
]
