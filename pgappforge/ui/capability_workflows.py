"""
pgappforge/ui/capability_workflows.py

Pre-built guided workflows for all major ERP and fintech capabilities.

Call once at app startup::

	from pgappforge.ui.capability_workflows import register_all_capability_workflows
	n = register_all_capability_workflows()
	# n == number of wizards registered
"""
from __future__ import annotations

from pgappforge.ui.wizard import WizardStep, WorkflowWizard, register_workflow


def register_all_capability_workflows() -> int:
	"""Register pre-built guided workflows for all major capabilities.

	Returns:
		Total count of wizards registered.
	"""
	count = 0
	count += _register_sacco_workflows()
	count += _register_loan_workflows()
	count += _register_finance_workflows()
	count += _register_hcm_workflows()
	count += _register_crm_workflows()
	count += _register_inventory_workflows()
	count += _register_clubs_workflows()
	return count


# ---------------------------------------------------------------------------
# SACCO — member management
# ---------------------------------------------------------------------------

def _register_sacco_workflows() -> int:
	register_workflow("sacco.member", WorkflowWizard(
		id="new_member_registration",
		title="Register New SACCO Member",
		description="Complete all steps to register a new member in the SACCO system.",
		icon="fa-user-plus",
		steps=[
			WizardStep(
				id="personal_info",
				title="Personal Information",
				icon="fa-user",
				description="Enter the member's personal details.",
				estimated_minutes=5,
				fields=[
					{"name": "full_name",      "type": "text",   "label": "Full Name",           "required": True},
					{"name": "national_id",    "type": "text",   "label": "National ID Number",   "required": True, "placeholder": "12345678"},
					{"name": "date_of_birth",  "type": "date",   "label": "Date of Birth",        "required": True},
					{"name": "gender",         "type": "select", "label": "Gender",               "required": True,
					 "choices": [("M", "Male"), ("F", "Female"), ("O", "Other / Prefer not to say")]},
					{"name": "phone",          "type": "phone",  "label": "M-Pesa Phone",         "required": True, "placeholder": "+254700000000"},
					{"name": "email",          "type": "email",  "label": "Email Address"},
					{"name": "postal_address", "type": "text",   "label": "Postal Address",       "placeholder": "P.O. Box 1234-00100"},
				],
			),
			WizardStep(
				id="employment",
				title="Employment Details",
				icon="fa-briefcase",
				description="Provide employer and income information.",
				estimated_minutes=3,
				fields=[
					{"name": "employer_name",         "type": "text",   "label": "Employer Name",                "required": True},
					{"name": "employer_code",         "type": "text",   "label": "Employer Code",                "required": True},
					{"name": "staff_number",          "type": "text",   "label": "Staff / Payroll Number",       "required": True},
					{"name": "gross_salary_cents",    "type": "money",  "label": "Gross Monthly Salary (KES)",   "required": True},
					{"name": "employment_type",       "type": "select", "label": "Employment Type",
					 "choices": [("PERMANENT", "Permanent"), ("CONTRACT", "Contract"), ("SELF_EMPLOYED", "Self-Employed")]},
				],
			),
			WizardStep(
				id="membership_type",
				title="Membership Category",
				icon="fa-id-card",
				description="Select membership type and initial share capital.",
				estimated_minutes=2,
				fields=[
					{"name": "member_type_id",              "type": "select", "label": "Membership Type",                "required": True},
					{"name": "initial_shares",              "type": "number", "label": "Initial Shares to Purchase",     "required": True, "min": 1},
					{"name": "monthly_contribution_cents",  "type": "money",  "label": "Monthly Contribution (KES)",     "required": True},
					{"name": "proposer_member_number",      "type": "text",   "label": "Proposer Member Number",        "required": True},
					{"name": "seconder_member_number",      "type": "text",   "label": "Seconder Member Number"},
				],
			),
			WizardStep(
				id="documents",
				title="Upload Documents",
				icon="fa-file",
				description="Upload required KYC documents.",
				estimated_minutes=5,
				fields=[
					{"name": "national_id_photo", "type": "file", "label": "National ID (Front & Back)", "required": True, "accept": "image/*,application/pdf"},
					{"name": "passport_photo",    "type": "file", "label": "Passport Photo",             "required": True, "accept": "image/*"},
					{"name": "payslip",           "type": "file", "label": "Recent Payslip",             "required": True, "accept": "application/pdf,image/*"},
					{"name": "bank_statement",    "type": "file", "label": "3-Month Bank Statement",                       "accept": "application/pdf"},
				],
			),
			WizardStep(
				id="review",
				title="Review & Submit",
				icon="fa-check-circle",
				description="Review all details before submitting the application.",
				estimated_minutes=2,
			),
		],
		submit_label="Submit Membership Application",
		success_message="Membership application submitted successfully. Reference number sent to your phone.",
	))
	return 1


# ---------------------------------------------------------------------------
# SACCO — loan application
# ---------------------------------------------------------------------------

def _register_loan_workflows() -> int:
	register_workflow("sacco.loan", WorkflowWizard(
		id="loan_application",
		title="Apply for SACCO Loan",
		description="Submit a loan application for review by the credit committee.",
		icon="fa-money",
		steps=[
			WizardStep(
				id="loan_details",
				title="Loan Details",
				icon="fa-calculator",
				estimated_minutes=3,
				fields=[
					{"name": "product_id",        "type": "select",   "label": "Loan Product",            "required": True},
					{"name": "amount_cents",       "type": "money",    "label": "Amount Requested (KES)",  "required": True, "min": 0},
					{"name": "tenor_months",       "type": "number",   "label": "Repayment Period (Months)", "required": True, "min": 1, "max": 120},
					{"name": "purpose",            "type": "textarea", "label": "Loan Purpose",            "required": True, "rows": 3},
					{"name": "repayment_source",   "type": "select",   "label": "Repayment Source",
					 "choices": [("SALARY", "Salary Deduction"), ("BUSINESS", "Business Income"), ("OTHER", "Other")]},
				],
			),
			WizardStep(
				id="guarantors",
				title="Guarantors",
				icon="fa-users",
				description="Provide details of at least 2 active member guarantors.",
				estimated_minutes=5,
				fields=[
					{"name": "guarantor1_member_number",  "type": "text",  "label": "Guarantor 1 Member Number",       "required": True},
					{"name": "guarantor1_amount_cents",   "type": "money", "label": "Guarantor 1 Guarantee Amount (KES)", "required": True},
					{"name": "guarantor2_member_number",  "type": "text",  "label": "Guarantor 2 Member Number",       "required": True},
					{"name": "guarantor2_amount_cents",   "type": "money", "label": "Guarantor 2 Guarantee Amount (KES)", "required": True},
					{"name": "guarantor3_member_number",  "type": "text",  "label": "Guarantor 3 Member Number (optional)"},
					{"name": "guarantor3_amount_cents",   "type": "money", "label": "Guarantor 3 Guarantee Amount (KES)"},
				],
			),
			WizardStep(
				id="collateral",
				title="Collateral",
				icon="fa-home",
				is_optional=True,
				estimated_minutes=2,
				fields=[
					{"name": "collateral_type",        "type": "select",   "label": "Collateral Type",
					 "choices": [("NONE", "None"), ("PROPERTY", "Property"), ("VEHICLE", "Vehicle"), ("SAVINGS", "Savings"), ("OTHER", "Other")]},
					{"name": "collateral_value_cents", "type": "money",    "label": "Estimated Value (KES)"},
					{"name": "collateral_description", "type": "textarea", "label": "Description", "rows": 2},
				],
			),
			WizardStep(
				id="declaration",
				title="Declaration",
				icon="fa-pen",
				estimated_minutes=1,
				fields=[
					{"name": "agree_terms",        "type": "checkbox", "label": "I confirm all information is accurate and I agree to the loan terms.", "required": True},
					{"name": "agree_credit_check", "type": "checkbox", "label": "I consent to a CRB credit check.",                                    "required": True},
				],
			),
		],
		submit_label="Submit Loan Application",
		success_message="Loan application submitted. The credit committee will contact you within 3 business days.",
	))
	return 1


# ---------------------------------------------------------------------------
# Finance — AP and AR
# ---------------------------------------------------------------------------

def _register_finance_workflows() -> int:
	count = 0

	# Accounts Payable: supplier invoice capture
	register_workflow("finance.ap", WorkflowWizard(
		id="supplier_invoice_capture",
		title="Capture Supplier Invoice",
		description="Record a supplier invoice for approval and payment processing.",
		icon="fa-file-text",
		steps=[
			WizardStep(
				id="vendor",
				title="Vendor Details",
				icon="fa-building",
				estimated_minutes=2,
				fields=[
					{"name": "vendor_id",       "type": "select", "label": "Vendor",         "required": True},
					{"name": "invoice_number",  "type": "text",   "label": "Invoice Number",  "required": True},
					{"name": "invoice_date",    "type": "date",   "label": "Invoice Date",    "required": True},
					{"name": "due_date",        "type": "date",   "label": "Due Date",        "required": True},
					{"name": "currency_code",   "type": "select", "label": "Currency",
					 "choices": [("KES", "KES"), ("USD", "USD"), ("EUR", "EUR"), ("UGX", "UGX"), ("NGN", "NGN"), ("GHS", "GHS"), ("ZAR", "ZAR")]},
				],
			),
			WizardStep(
				id="line_items",
				title="Line Items",
				icon="fa-list",
				estimated_minutes=5,
				fields=[
					{"name": "description",      "type": "text",   "label": "Description",                           "required": True},
					{"name": "quantity",         "type": "number", "label": "Quantity",                              "required": True, "min": 0},
					{"name": "unit_price_cents", "type": "money",  "label": "Unit Price (KES)",                      "required": True},
					{"name": "tax_rate_pct",     "type": "number", "label": "Tax Rate %",
					 "help": "16% for standard VAT; 0% for exempt; 8% for hotel levy"},
					{"name": "cost_center",      "type": "text",   "label": "Cost Centre"},
					{"name": "gl_account",       "type": "text",   "label": "GL Account Code"},
				],
			),
			WizardStep(
				id="approval",
				title="Approval",
				icon="fa-check",
				estimated_minutes=1,
				fields=[
					{"name": "po_number",       "type": "text",     "label": "Purchase Order Number (if applicable)"},
					{"name": "goods_received",  "type": "checkbox", "label": "Goods / services have been received and verified."},
					{"name": "notes",           "type": "textarea", "label": "Notes for Approver", "rows": 2},
				],
			),
		],
		submit_label="Submit Invoice for Approval",
		success_message="Invoice submitted for approval. You will be notified when it is processed.",
	))
	count += 1

	# Accounts Receivable: customer invoice
	register_workflow("finance.ar", WorkflowWizard(
		id="create_customer_invoice",
		title="Create Customer Invoice",
		description="Generate an invoice for a customer and submit to KRA eTIMS.",
		icon="fa-file-invoice",
		steps=[
			WizardStep(
				id="customer",
				title="Customer",
				icon="fa-user",
				estimated_minutes=2,
				fields=[
					{"name": "customer_id",   "type": "select", "label": "Customer",      "required": True},
					{"name": "invoice_date",  "type": "date",   "label": "Invoice Date",  "required": True},
					{"name": "due_date",      "type": "date",   "label": "Due Date",      "required": True},
					{"name": "reference",     "type": "text",   "label": "Your Reference / Order Number"},
				],
			),
			WizardStep(
				id="items",
				title="Items & Services",
				icon="fa-shopping-cart",
				estimated_minutes=5,
				fields=[
					{"name": "description",      "type": "text",   "label": "Item Description", "required": True},
					{"name": "quantity",         "type": "number", "label": "Quantity",         "required": True, "min": 0},
					{"name": "unit_price_cents", "type": "money",  "label": "Unit Price (KES)", "required": True},
					{"name": "vat_rate_pct",     "type": "number", "label": "VAT Rate %",
					 "help": "16% standard / 0% exempt / 8% hotel levy"},
					{"name": "discount_pct",     "type": "number", "label": "Discount %",       "min": 0, "max": 100},
				],
			),
			WizardStep(
				id="etims",
				title="eTIMS Submission",
				icon="fa-paper-plane",
				estimated_minutes=1,
				fields=[
					{"name": "customer_pin",     "type": "text",     "label": "Customer KRA PIN",
					 "help": "Leave blank for non-VAT-registered buyers."},
					{"name": "payment_type",     "type": "select",   "label": "Expected Payment Method",
					 "choices": [("MPESA", "M-Pesa"), ("BANK", "Bank Transfer"), ("CASH", "Cash"), ("CHEQUE", "Cheque"), ("CREDIT", "Credit Terms")]},
					{"name": "submit_to_etims",  "type": "checkbox", "label": "Submit to KRA eTIMS automatically on save."},
				],
			),
		],
		submit_label="Generate Invoice",
		success_message="Invoice created and queued for eTIMS submission.",
	))
	count += 1

	return count


# ---------------------------------------------------------------------------
# HCM — recruiting
# ---------------------------------------------------------------------------

def _register_hcm_workflows() -> int:
	register_workflow("hcm.recruiting", WorkflowWizard(
		id="job_application_intake",
		title="Process Job Application",
		description="Review and move a job application through the hiring pipeline.",
		icon="fa-user-plus",
		steps=[
			WizardStep(
				id="screening",
				title="Initial Screening",
				icon="fa-search",
				estimated_minutes=5,
				fields=[
					{"name": "candidate_name",     "type": "text",     "label": "Candidate Name",         "required": True},
					{"name": "email",              "type": "email",    "label": "Email",                  "required": True},
					{"name": "phone",              "type": "phone",    "label": "Phone"},
					{"name": "years_experience",   "type": "number",   "label": "Years of Experience",    "min": 0},
					{"name": "current_salary",     "type": "money",    "label": "Current / Last Salary (KES)"},
					{"name": "expected_salary",    "type": "money",    "label": "Expected Salary (KES)"},
					{"name": "meets_minimum",      "type": "checkbox", "label": "Meets minimum requirements for the role."},
					{"name": "screening_notes",    "type": "textarea", "label": "Screening Notes", "rows": 3},
				],
			),
			WizardStep(
				id="interview",
				title="Interview Scheduling",
				icon="fa-calendar",
				estimated_minutes=3,
				fields=[
					{"name": "interview_date",    "type": "date",   "label": "Interview Date",     "required": True},
					{"name": "interview_type",    "type": "select", "label": "Interview Type",
					 "choices": [("VIDEO", "Video Call"), ("IN_PERSON", "In-Person"), ("PHONE", "Phone")]},
					{"name": "interviewer_id",    "type": "select", "label": "Lead Interviewer",   "required": True},
					{"name": "panel_members",     "type": "text",   "label": "Other Panel Members (comma-separated)"},
					{"name": "interview_notes",   "type": "textarea", "label": "Interview Notes",  "rows": 3},
				],
			),
			WizardStep(
				id="decision",
				title="Decision",
				icon="fa-gavel",
				estimated_minutes=3,
				fields=[
					{"name": "overall_rating", "type": "select",   "label": "Overall Rating",
					 "choices": [("5", "Exceptional"), ("4", "Strong"), ("3", "Adequate"), ("2", "Weak"), ("1", "Not Suitable")]},
					{"name": "decision",       "type": "select",   "label": "Decision",    "required": True,
					 "choices": [("HIRE", "Proceed to Offer"), ("HOLD", "Place on Hold"), ("REJECT", "Decline")]},
					{"name": "offer_salary",   "type": "money",    "label": "Proposed Offer Salary (KES)"},
					{"name": "feedback",       "type": "textarea", "label": "Interview Feedback (shared with hiring manager)", "required": True, "rows": 4},
				],
			),
		],
		submit_label="Save Application Decision",
		success_message="Application decision recorded. Next steps initiated.",
	))
	return 1


# ---------------------------------------------------------------------------
# CRM — sales qualification
# ---------------------------------------------------------------------------

def _register_crm_workflows() -> int:
	register_workflow("crm.sales", WorkflowWizard(
		id="qualify_lead",
		title="Qualify a Lead",
		description="Guide a prospect through the BANT qualification framework.",
		icon="fa-filter",
		steps=[
			WizardStep(
				id="contact",
				title="Contact Information",
				icon="fa-address-card",
				estimated_minutes=3,
				fields=[
					{"name": "company_name",  "type": "text",   "label": "Company Name",   "required": True},
					{"name": "contact_name",  "type": "text",   "label": "Contact Name",   "required": True},
					{"name": "email",         "type": "email",  "label": "Email",          "required": True},
					{"name": "phone",         "type": "phone",  "label": "Phone"},
					{"name": "linkedin_url",  "type": "url",    "label": "LinkedIn URL"},
					{"name": "source",        "type": "select", "label": "Lead Source",
					 "choices": [
						 ("REFERRAL", "Referral"), ("WEBSITE", "Website"),
						 ("EVENT", "Event"), ("COLD_CALL", "Cold Call"), ("SOCIAL", "Social Media"),
					 ]},
				],
			),
			WizardStep(
				id="qualification",
				title="BANT Qualification",
				icon="fa-check-square",
				estimated_minutes=5,
				help_text="BANT: Budget · Authority · Need · Timeline",
				fields=[
					{"name": "budget_range",      "type": "select", "label": "Estimated Budget",
					 "choices": [("<50K", "< KES 50 K"), ("50K-200K", "KES 50 K–200 K"), (">200K", "KES 200 K+")]},
					{"name": "authority",         "type": "select", "label": "Decision Maker?",
					 "choices": [("YES", "Yes, I am the DM"), ("PARTIAL", "Part of buying committee"), ("NO", "Need to reach DM")]},
					{"name": "need_description",  "type": "textarea", "label": "Describe the business need", "rows": 3, "required": True},
					{"name": "timeline",          "type": "select", "label": "Purchase Timeline",
					 "choices": [
						 ("IMMEDIATE", "Immediate (< 1 month)"), ("QUARTER", "This quarter"),
						 ("HALF_YEAR", "6 months"), ("FUTURE", "No specific timeline"),
					 ]},
					{"name": "score",             "type": "select", "label": "Lead Score",
					 "choices": [("HOT", "Hot — ready to buy"), ("WARM", "Warm — interested"), ("COLD", "Cold — nurture")]},
				],
			),
			WizardStep(
				id="next_action",
				title="Next Action",
				icon="fa-arrow-right",
				estimated_minutes=1,
				fields=[
					{"name": "next_action",      "type": "select",   "label": "Next Action", "required": True,
					 "choices": [
						 ("DEMO", "Schedule Demo"), ("PROPOSAL", "Send Proposal"),
						 ("FOLLOW_UP", "Follow Up Call"), ("NURTURE", "Add to Nurture Sequence"),
						 ("CLOSE", "Close as Lost"),
					 ]},
					{"name": "next_action_date", "type": "date",     "label": "Follow-up Date", "required": True},
					{"name": "assigned_to_id",   "type": "select",   "label": "Assign To"},
					{"name": "notes",            "type": "textarea", "label": "Notes", "rows": 3},
				],
			),
		],
		submit_label="Save Qualified Lead",
		success_message="Lead qualified and follow-up action scheduled.",
	))
	return 1


# ---------------------------------------------------------------------------
# Operations — inventory
# ---------------------------------------------------------------------------

def _register_inventory_workflows() -> int:
	register_workflow("operations.inventory", WorkflowWizard(
		id="stock_adjustment",
		title="Stock Count & Adjustment",
		description="Record physical stock count results and adjust system quantities.",
		icon="fa-boxes",
		steps=[
			WizardStep(
				id="setup",
				title="Count Setup",
				icon="fa-clipboard",
				estimated_minutes=2,
				fields=[
					{"name": "warehouse_id",    "type": "select", "label": "Warehouse",         "required": True},
					{"name": "count_date",      "type": "date",   "label": "Count Date",         "required": True},
					{"name": "count_reason",    "type": "select", "label": "Reason for Count",
					 "choices": [
						 ("PERIODIC", "Periodic Stock Take"), ("SPOT_CHECK", "Spot Check"),
						 ("DISCREPANCY", "Discrepancy Investigation"), ("ANNUAL", "Annual Audit"),
					 ]},
					{"name": "counted_by",      "type": "text",   "label": "Counted By",        "required": True},
					{"name": "supervisor_id",   "type": "select", "label": "Authorising Supervisor", "required": True},
				],
			),
			WizardStep(
				id="count_results",
				title="Count Results",
				icon="fa-calculator",
				estimated_minutes=10,
				fields=[
					{"name": "product_id",         "type": "select",   "label": "Product",                    "required": True},
					{"name": "unit_of_measure",    "type": "select",   "label": "Unit of Measure",
					 "choices": [("EA", "Each"), ("KG", "Kilograms"), ("L", "Litres"), ("M", "Metres"), ("BOX", "Box"), ("PKT", "Packet")]},
					{"name": "system_quantity",    "type": "number",   "label": "System Quantity (read-only)"},
					{"name": "physical_quantity",  "type": "number",   "label": "Physical Count Quantity",    "required": True, "min": 0},
					{"name": "variance_reason",    "type": "textarea", "label": "Variance Explanation (if any)", "rows": 2},
				],
			),
			WizardStep(
				id="approval",
				title="Approve Adjustment",
				icon="fa-thumbs-up",
				estimated_minutes=1,
				fields=[
					{"name": "approve_adjustment", "type": "checkbox", "label": "I approve this stock adjustment and confirm the count figures are correct.", "required": True},
					{"name": "supervisor_notes",   "type": "textarea", "label": "Supervisor Notes", "rows": 2},
				],
			),
		],
		submit_label="Process Stock Adjustment",
		success_message="Stock adjustment processed and inventory updated.",
	))
	return 1


# ---------------------------------------------------------------------------
# Clubs — facility booking
# ---------------------------------------------------------------------------

def _register_clubs_workflows() -> int:
	_time_choices = [(f"{h:02d}:00", f"{h:02d}:00") for h in range(6, 23)]

	register_workflow("clubs.facility", WorkflowWizard(
		id="facility_booking",
		title="Book a Club Facility",
		description="Reserve a court, pool, gym, or function room.",
		icon="fa-calendar-plus-o",
		steps=[
			WizardStep(
				id="select_facility",
				title="Select Facility",
				icon="fa-building",
				estimated_minutes=3,
				fields=[
					{"name": "facility_id",    "type": "select", "label": "Facility",          "required": True},
					{"name": "booking_date",   "type": "date",   "label": "Date",               "required": True},
					{"name": "start_time",     "type": "select", "label": "Start Time",         "required": True,  "choices": _time_choices},
					{"name": "end_time",       "type": "select", "label": "End Time",           "required": True,  "choices": _time_choices[1:]},
					{"name": "guest_count",    "type": "number", "label": "Number of Guests",
					 "help": "Guests beyond your membership allowance will be charged.", "min": 0},
				],
			),
			WizardStep(
				id="confirm",
				title="Confirm Booking",
				icon="fa-check",
				estimated_minutes=1,
				fields=[
					{"name": "purpose",          "type": "text",     "label": "Purpose / Activity"},
					{"name": "special_requests", "type": "textarea", "label": "Special Requests", "rows": 2},
					{"name": "confirm_policy",   "type": "checkbox", "label": "I agree to the facility usage policy and cancellation terms.", "required": True},
				],
			),
		],
		submit_label="Confirm Booking",
		success_message="Facility booked. Confirmation sent to your registered email.",
	))
	return 1


__all__ = ["register_all_capability_workflows"]
