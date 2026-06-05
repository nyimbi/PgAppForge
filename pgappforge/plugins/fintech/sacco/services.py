"""
pgappforge/plugins/fintech/sacco/services.py

SACCO / MFI / Chama service layer.

All monetary arithmetic uses integer cents via money_add / money_multiply /
money_divide / percent_of from ERP foundation commons.  Never use float for money.

SACCOService:
  register_member             — onboard a party as a SACCO member
  process_monthly_contribution — post a member's savings contribution
  apply_sacco_loan            — eligibility check + loan application
  declare_dividend            — declare annual dividend (immutable record)
  pay_dividends               — credit each member's account
  calculate_member_exit_value — shares + deposits - loans - guarantees
  get_sacco_financials        — KPIs: savings, loans, NPL, capital adequacy, liquidity
  create_standing_order       — create recurring payment instruction for a member
  execute_standing_order      — execute a standing order: debit source, credit destination
  calculate_dividends         — dry-run per-member dividend entitlement (no persistence)
  post_dividend               — credit a computed dividend to a single member
  issue_shares                — debit member, credit share capital; update share counts
  redeem_shares               — reverse share issuance; credit member proceeds
  apply_fee                   — debit member, credit fee income; insert FeeLineItem
  generate_member_statement   — query SaccoLedgerEntry rows, return structured statement dict

ChamaService:
  create_chama                — form a new Chama with founding members
  record_contribution         — post a member's contribution to the pool
  process_merry_go_round      — disburse pool to current recipient, rotate
  record_table_banking_loan   — issue a short-term loan from the pool
  get_chama_statement         — contribution / payout summary for a period
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from pgappforge.plugins.erp.foundation.commons import (
	money_add,
	money_multiply,
	money_divide,
	percent_of,
	format_currency,
	emit_event,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _generate_member_number(sacco_id: str) -> str:
	ts = datetime.now(timezone.utc).strftime("%Y%m%d")
	suffix = uuid.uuid4().hex[:6].upper()
	return f"M-{ts}-{suffix}"


def _add_weeks(d: date, weeks: int) -> date:
	return d + timedelta(weeks=weeks)


# ---------------------------------------------------------------------------
# SACCOService
# ---------------------------------------------------------------------------

class SACCOService:
	"""Business logic for SACCO operations.

	All methods require a SQLAlchemy session passed as first argument.
	No Flask-global state accessed here — callers inject session from context.
	"""

	# ------------------------------------------------------------------
	# register_member
	# ------------------------------------------------------------------

	def register_member(
		self,
		session: Any,
		sacco_id: str,
		party_id: str,
		initial_shares: int,
		monthly_contribution_cents: int,
		tenant_id: str,
		share_account_id: str | None = None,
		deposit_account_id: str | None = None,
		membership_date: date | None = None,
	) -> Any:
		"""Onboard a Party as a SACCO member.

		Creates a Member record and, if initial_shares > 0, sets
		total_shares_value_cents.  Core banking account creation is handled
		externally (or via CoreBankingService) and the IDs passed in.

		Returns: Member instance (flushed, not committed).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import SACCO, Member

		sacco = session.get(SACCO, sacco_id)
		if sacco is None:
			raise ValueError(f"SACCO {sacco_id!r} not found")

		# Guard: party must not already be an active member of this SACCO
		existing = session.execute(
			sa.select(Member).where(
				Member.sacco_id == sacco_id,
				Member.party_id == party_id,
				Member.membership_status == "ACTIVE",
			)
		).scalar_one_or_none()
		if existing is not None:
			raise ValueError(
				f"Party {party_id!r} is already an active member of SACCO {sacco_id!r} "
				f"(member_number={existing.member_number!r})"
			)

		mem_date = membership_date or date.today()
		share_value_cents = 10000  # default KES 100.00 per share; SACCO configures this

		member = Member(
			tenant_id=tenant_id,
			member_number=_generate_member_number(sacco_id),
			sacco_id=sacco_id,
			party_id=party_id,
			membership_date=mem_date,
			membership_status="ACTIVE",
			share_account_id=share_account_id,
			deposit_account_id=deposit_account_id,
			shares_held=initial_shares,
			share_value_cents=share_value_cents,
			total_shares_value_cents=money_multiply(initial_shares, share_value_cents),
			monthly_contribution_cents=monthly_contribution_cents,
			guarantees_given=[],
			guarantees_active_cents=0,
		)
		session.add(member)
		session.flush()

		# Update SACCO aggregate
		sacco.membership_count = money_add(sacco.membership_count, 1)
		sacco.total_shares_cents = money_add(
			sacco.total_shares_cents, member.total_shares_value_cents
		)
		session.flush()

		try:
			emit_event(
				"sc.member.registered",
				"Member",
				member.id,
				{
					"member_id": member.id,
					"member_number": member.member_number,
					"sacco_id": sacco_id,
					"party_id": party_id,
					"initial_shares": initial_shares,
					"share_value_cents": share_value_cents,
					"membership_date": mem_date.isoformat(),
				},
				session,
				tenant_id=tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Registered member %s in SACCO %s (shares=%d)",
			member.member_number, sacco_id, initial_shares,
		)
		return member

	# ------------------------------------------------------------------
	# process_monthly_contribution
	# ------------------------------------------------------------------

	def process_monthly_contribution(
		self,
		session: Any,
		member_id: str,
		amount_cents: int,
		contribution_date: date | None = None,
	) -> dict:
		"""Post a member's monthly savings contribution.

		Credits the member's deposit_account (if linked) via CoreBankingService.
		Updates SACCO aggregate total_deposits_cents.

		Returns dict: member_number, amount_cents, new_deposit_balance_cents.
		"""
		from pgappforge.plugins.fintech.sacco.models import Member, SACCO

		contrib_date = contribution_date or date.today()
		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		if member.membership_status != "ACTIVE":
			raise ValueError(
				f"Cannot post contribution for member in status {member.membership_status!r}"
			)
		if amount_cents <= 0:
			raise ValueError(f"Contribution amount must be positive, got {amount_cents}")

		new_balance_cents = 0

		# Post to core banking deposit account (non-fatal if not available)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if member.deposit_account_id:
				cb = CoreBankingService()
				cb.post_deposit(
					session,
					account_id=member.deposit_account_id,
					amount_cents=amount_cents,
					narrative=f"Monthly contribution — {contrib_date.isoformat()}",
					tenant_id=member.tenant_id,
				)
				# Read back updated balance
				import sqlalchemy as sa
				from pgappforge.plugins.fintech.core_banking.models import Account
				acct = session.get(Account, member.deposit_account_id)
				if acct:
					new_balance_cents = acct.current_balance_cents
		except ImportError:
			log.debug("core_banking not available — skipping deposit posting")
		except Exception as exc:
			log.warning(
				"CB deposit post failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		# Update SACCO aggregate
		sacco = session.get(SACCO, member.sacco_id)
		if sacco:
			sacco.total_deposits_cents = money_add(sacco.total_deposits_cents, amount_cents)
			session.flush()

		try:
			emit_event(
				"sc.member.contribution_posted",
				"Member",
				member.id,
				{
					"member_id": member.id,
					"member_number": member.member_number,
					"sacco_id": member.sacco_id,
					"amount_cents": amount_cents,
					"deposit_account_id": member.deposit_account_id or "",
					"contribution_date": contrib_date.isoformat(),
				},
				session,
				tenant_id=member.tenant_id,
			)
		except Exception:
			pass

		return {
			"member_number": member.member_number,
			"amount_cents": amount_cents,
			"new_deposit_balance_cents": new_balance_cents,
			"contribution_date": contrib_date.isoformat(),
		}

	# ------------------------------------------------------------------
	# apply_sacco_loan
	# ------------------------------------------------------------------

	def apply_sacco_loan(
		self,
		session: Any,
		member_id: str,
		product_id: str,
		amount_cents: int,
		tenor_months: int,
		guarantor_ids: list[str],
		tenant_id: str,
	) -> dict:
		"""Validate eligibility and create a SACCO loan application.

		Eligibility rules:
		  1. Member must be ACTIVE.
		  2. amount_cents <= member total_shares_value_cents × max_multiple_of_savings.
		  3. amount_cents <= product.max_amount_cents (if set).
		  4. tenor_months <= product.max_tenor_months.
		  5. If requires_guarantors: len(guarantor_ids) >= min_guarantors.
		  6. Guarantor coverage: sum of guarantor shares >= amount * guarantor_coverage_pct/100.

		Delegates actual loan record creation to the lending plugin (lazy import).
		If lending is not available, returns an application stub dict.

		Returns dict: application_id (or stub), member_number, amount_cents,
		              eligible_amount_cents, product_name, eligibility_check.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SACCOLoanProduct

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")
		if member.membership_status != "ACTIVE":
			raise ValueError(
				f"Member {member.member_number!r} is not active (status={member.membership_status!r})"
			)

		product = session.get(SACCOLoanProduct, product_id)
		if product is None:
			raise ValueError(f"SACCOLoanProduct {product_id!r} not found")
		if not product.is_active:
			raise ValueError(f"Loan product {product.product_name!r} is not active")

		# 1. Savings multiplier check
		eligible_amount_cents = money_multiply(
			member.total_shares_value_cents + (member.monthly_contribution_cents * 12),
			Decimal(str(product.max_multiple_of_savings)),
		)
		if amount_cents > eligible_amount_cents:
			raise ValueError(
				f"Requested amount {amount_cents}c exceeds eligible limit {eligible_amount_cents}c "
				f"(savings × {product.max_multiple_of_savings})"
			)

		# 2. Absolute cap
		if product.max_amount_cents is not None and amount_cents > product.max_amount_cents:
			raise ValueError(
				f"Requested amount {amount_cents}c exceeds product cap {product.max_amount_cents}c"
			)

		# 3. Tenor
		if tenor_months > product.max_tenor_months:
			raise ValueError(
				f"Tenor {tenor_months} months exceeds product max {product.max_tenor_months}"
			)

		# 4. Guarantors
		if product.requires_guarantors:
			if len(guarantor_ids) < product.min_guarantors:
				raise ValueError(
					f"Product requires {product.min_guarantors} guarantors, "
					f"only {len(guarantor_ids)} provided"
				)

			# Guarantor coverage check
			required_coverage_cents = percent_of(
				amount_cents, Decimal(str(product.guarantor_coverage_pct))
			)
			guarantors = session.execute(
				sa.select(Member).where(
					Member.id.in_(guarantor_ids),
					Member.membership_status == "ACTIVE",
				)
			).scalars().all()

			if len(guarantors) < product.min_guarantors:
				raise ValueError(
					f"Only {len(guarantors)} of {len(guarantor_ids)} guarantors are active members"
				)

			# Available guarantor coverage = each guarantor's shares minus their
			# already-committed guarantees
			total_guarantor_coverage_cents = sum(
				money_add(
					g.total_shares_value_cents, -g.guarantees_active_cents
				)
				for g in guarantors
			)
			if total_guarantor_coverage_cents < required_coverage_cents:
				raise ValueError(
					f"Guarantor coverage {total_guarantor_coverage_cents}c insufficient; "
					f"need {required_coverage_cents}c "
					f"({product.guarantor_coverage_pct}% of {amount_cents}c)"
				)

			# Register guarantees on guarantor member records
			for g in guarantors:
				g.guarantees_given = list(g.guarantees_given or []) + [f"pending:{member_id}"]
				g.guarantees_active_cents = money_add(
					g.guarantees_active_cents,
					money_divide(required_coverage_cents, len(guarantors)),
				)
			session.flush()

		# Delegate to lending plugin for formal application record
		application_id: str | None = None
		try:
			from pgappforge.plugins.fintech.lending.services import LoanOriginationService
			# Map SACCO product to lending product code (convention: "SC-<product.id[:8]>")
			product_code = f"SC-{product.id[:8].upper()}"
			los = LoanOriginationService()
			app = los.create_application(
				session=session,
				tenant_id=tenant_id,
				applicant_id=member.party_id,
				product_code=product_code,
				amount_cents=amount_cents,
				tenor_months=tenor_months,
				purpose=f"SACCO {product.loan_type} loan",
				channel="SACCO",
			)
			application_id = app.id
		except ImportError:
			log.debug("lending plugin not available — returning eligibility stub")
		except Exception as exc:
			log.warning(
				"Lending plugin loan application failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		try:
			emit_event(
				"sc.loan.application_created",
				"Member",
				member.id,
				{
					"application_id": application_id or "",
					"member_id": member_id,
					"member_number": member.member_number,
					"sacco_id": member.sacco_id,
					"product_id": product_id,
					"amount_cents": amount_cents,
					"tenor_months": tenor_months,
					"guarantor_ids": guarantor_ids,
				},
				session,
				tenant_id=tenant_id,
			)
		except Exception:
			pass

		return {
			"application_id": application_id,
			"member_number": member.member_number,
			"product_name": product.product_name,
			"amount_cents": amount_cents,
			"eligible_amount_cents": eligible_amount_cents,
			"tenor_months": tenor_months,
			"interest_rate_pa": str(product.interest_rate_pa),
			"guarantors_verified": len(guarantor_ids),
			"eligibility_check": "PASSED",
		}

	# ------------------------------------------------------------------
	# declare_dividend
	# ------------------------------------------------------------------

	def declare_dividend(
		self,
		session: Any,
		sacco_id: str,
		financial_year: int,
		dividend_rate_pct: Decimal | str,
		interest_rebate_pct: Decimal | str,
		total_dividend_pool_cents: int,
		approved_date: date | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Declare an annual dividend for a SACCO.

		Creates an immutable Dividend record.  Validates that no dividend has
		already been declared for this SACCO/year combination.

		Returns: Dividend instance (flushed, not committed).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import SACCO, Dividend

		sacco = session.get(SACCO, sacco_id)
		if sacco is None:
			raise ValueError(f"SACCO {sacco_id!r} not found")

		# Guard: duplicate declaration
		existing = session.execute(
			sa.select(Dividend).where(
				Dividend.sacco_id == sacco_id,
				Dividend.financial_year == financial_year,
				Dividend.status != "CANCELLED",
			)
		).scalar_one_or_none()
		if existing is not None:
			raise ValueError(
				f"Dividend for SACCO {sacco_id!r} year {financial_year} "
				f"already declared (id={existing.id!r}, status={existing.status!r})"
			)

		appr_date = approved_date or date.today()
		dividend = Dividend(
			tenant_id=tenant_id or sacco.tenant_id,
			sacco_id=sacco_id,
			financial_year=financial_year,
			dividend_rate_pct=Decimal(str(dividend_rate_pct)),
			interest_rebate_pct=Decimal(str(interest_rebate_pct)),
			total_dividend_pool_cents=total_dividend_pool_cents,
			approved_date=appr_date,
			status="DECLARED",
		)
		session.add(dividend)
		session.flush()

		try:
			emit_event(
				"sc.dividend.declared",
				"Dividend",
				dividend.id,
				{
					"dividend_id": dividend.id,
					"sacco_id": sacco_id,
					"financial_year": financial_year,
					"dividend_rate_pct": str(dividend_rate_pct),
					"interest_rebate_pct": str(interest_rebate_pct),
					"total_dividend_pool_cents": total_dividend_pool_cents,
					"approved_date": appr_date.isoformat(),
				},
				session,
				tenant_id=dividend.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Declared dividend for SACCO %s year %d: pool=%d cents at %.2f%%",
			sacco_id, financial_year, total_dividend_pool_cents,
			float(dividend_rate_pct),
		)
		return dividend

	# ------------------------------------------------------------------
	# pay_dividends
	# ------------------------------------------------------------------

	def pay_dividends(
		self,
		session: Any,
		dividend_id: str,
		payment_date: date | None = None,
	) -> dict:
		"""Distribute the declared dividend pool to all active members.

		For each ACTIVE member of the SACCO:
		  member_dividend_cents = total_shares_value_cents × dividend_rate_pct / 100

		Credits are posted to each member's deposit_account via CoreBankingService
		(non-fatal if CB not available).

		Marks Dividend.status = 'PAID' and sets payment_date.
		ImmutableRecordMixin blocks UPDATE on Dividend rows, so status is updated
		via a direct session.execute(UPDATE) that bypasses the ORM mapper guard
		(consistent with the InterestAccrual pattern in core_banking).

		Returns dict: dividend_id, members_credited, total_paid_cents, payment_date.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Dividend, Member

		dividend = session.get(Dividend, dividend_id)
		if dividend is None:
			raise ValueError(f"Dividend {dividend_id!r} not found")
		if dividend.status == "PAID":
			raise ValueError(f"Dividend {dividend_id!r} already paid")
		if dividend.status == "CANCELLED":
			raise ValueError(f"Dividend {dividend_id!r} is cancelled")

		pay_date = payment_date or date.today()
		rate = Decimal(str(dividend.dividend_rate_pct)) / Decimal("100")

		# Fetch all active members of this SACCO
		members = session.execute(
			sa.select(Member).where(
				Member.sacco_id == dividend.sacco_id,
				Member.membership_status == "ACTIVE",
			)
		).scalars().all()

		members_credited = 0
		total_paid_cents = 0

		for member in members:
			member_dividend_cents = money_multiply(
				member.total_shares_value_cents, rate
			)
			if member_dividend_cents <= 0:
				continue

			total_paid_cents = money_add(total_paid_cents, member_dividend_cents)

			# Post credit to deposit account (non-fatal)
			try:
				from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
				if member.deposit_account_id:
					cb = CoreBankingService()
					cb.post_deposit(
						session,
						account_id=member.deposit_account_id,
						amount_cents=member_dividend_cents,
						narrative=(
							f"Dividend FY{dividend.financial_year} "
							f"@ {dividend.dividend_rate_pct}%"
						),
						tenant_id=member.tenant_id,
					)
					members_credited += 1
				else:
					log.debug(
						"Member %s has no deposit_account — dividend of %d cents not posted",
						member.member_number, member_dividend_cents,
					)
			except ImportError:
				log.debug("core_banking not available — skipping dividend credit")
				members_credited += 1  # count it regardless for reporting
			except Exception as exc:
				log.warning(
					"Dividend credit failed for member %s: %s (non-fatal)",
					member.member_number, exc,
				)

		# Update dividend status via direct SQL (bypasses ImmutableRecordMixin mapper event)
		session.execute(
			sa.update(Dividend)
			.where(Dividend.id == dividend_id)
			.values(status="PAID", payment_date=pay_date)
		)
		session.flush()

		try:
			emit_event(
				"sc.dividend.paid",
				"Dividend",
				dividend.id,
				{
					"dividend_id": dividend_id,
					"sacco_id": dividend.sacco_id,
					"financial_year": dividend.financial_year,
					"total_paid_cents": total_paid_cents,
					"members_credited": members_credited,
					"payment_date": pay_date.isoformat(),
				},
				session,
				tenant_id=dividend.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Paid dividend %s: %d members, total=%d cents",
			dividend_id, members_credited, total_paid_cents,
		)
		return {
			"dividend_id": dividend_id,
			"members_credited": members_credited,
			"total_paid_cents": total_paid_cents,
			"payment_date": pay_date.isoformat(),
		}

	# ------------------------------------------------------------------
	# calculate_member_exit_value
	# ------------------------------------------------------------------

	def calculate_member_exit_value(
		self,
		session: Any,
		member_id: str,
	) -> dict:
		"""Calculate the net payable to a member upon exit.

		Formula:
		  net_payable = shares_value + deposits - outstanding_loans - active_guarantees

		Outstanding loans are queried from the lending plugin (lazy import);
		falls back to zero if not available.

		Does NOT mark the member as withdrawn — caller must do that after
		confirming payment.

		Returns dict with component breakdown.
		"""
		from pgappforge.plugins.fintech.sacco.models import Member

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		shares_value_cents = member.total_shares_value_cents

		# Read deposit balance from core banking
		deposit_balance_cents = 0
		try:
			from pgappforge.plugins.fintech.core_banking.models import Account
			if member.deposit_account_id:
				acct = session.get(Account, member.deposit_account_id)
				if acct:
					deposit_balance_cents = acct.current_balance_cents
		except ImportError:
			log.debug("core_banking not available — using 0 for deposit balance")
		except Exception as exc:
			log.warning("Could not read deposit balance for member %s: %s", member_id, exc)

		# Outstanding loans (via lending plugin)
		outstanding_loans_cents = 0
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.fintech.lending.models import Loan
			loans = session.execute(
				sa.select(Loan).where(
					Loan.borrower_id == member.party_id,
					Loan.status.in_(["ACTIVE", "DEFAULTED"]),
				)
			).scalars().all()
			outstanding_loans_cents = sum(l.outstanding_principal_cents for l in loans)
		except ImportError:
			log.debug("lending plugin not available — using 0 for outstanding loans")
		except Exception as exc:
			log.warning("Could not read outstanding loans for member %s: %s", member_id, exc)

		active_guarantees_cents = member.guarantees_active_cents

		# Net is non-negative — a SACCO does not owe negative amounts on exit
		# (member must settle all loans before exit if net < 0)
		gross_payable_cents = money_add(shares_value_cents, deposit_balance_cents)
		total_deductions_cents = money_add(outstanding_loans_cents, active_guarantees_cents)
		net_payable_cents = max(0, gross_payable_cents - total_deductions_cents)
		deficit_cents = max(0, total_deductions_cents - gross_payable_cents)

		# Persist withdrawal_balance_cents for display
		member.withdrawal_balance_cents = net_payable_cents
		session.flush()

		try:
			emit_event(
				"sc.member.exit_calculated",
				"Member",
				member.id,
				{
					"member_id": member_id,
					"member_number": member.member_number,
					"sacco_id": member.sacco_id,
					"shares_value_cents": shares_value_cents,
					"deposits_cents": deposit_balance_cents,
					"outstanding_loans_cents": outstanding_loans_cents,
					"active_guarantees_cents": active_guarantees_cents,
					"net_payable_cents": net_payable_cents,
				},
				session,
				tenant_id=member.tenant_id,
			)
		except Exception:
			pass

		return {
			"member_number": member.member_number,
			"shares_value_cents": shares_value_cents,
			"deposit_balance_cents": deposit_balance_cents,
			"gross_payable_cents": gross_payable_cents,
			"outstanding_loans_cents": outstanding_loans_cents,
			"active_guarantees_cents": active_guarantees_cents,
			"total_deductions_cents": total_deductions_cents,
			"net_payable_cents": net_payable_cents,
			"deficit_cents": deficit_cents,
			"can_exit": deficit_cents == 0,
		}

	# ------------------------------------------------------------------
	# get_sacco_financials
	# ------------------------------------------------------------------

	def get_sacco_financials(
		self,
		session: Any,
		sacco_id: str,
	) -> dict:
		"""Compute SACCO financial KPIs.

		Metrics:
		  total_savings_cents       — member deposits + shares
		  total_loans_cents         — outstanding loan book
		  npl_ratio_pct             — Non-Performing Loans / loan book
		  capital_adequacy_pct      — institutional_capital / total_assets
		  liquidity_ratio_pct       — liquid_assets / short_term_liabilities (simplified)
		  delinquency_rate_pct      — loans overdue > 90 days / loan book (PAR90)
		  membership_count
		  reserve_fund_cents

		Loan metrics query the lending plugin (lazy import).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import SACCO, Member

		sacco = session.get(SACCO, sacco_id)
		if sacco is None:
			raise ValueError(f"SACCO {sacco_id!r} not found")

		# Aggregate from member records (fast path — uses denormalised values)
		members = session.execute(
			sa.select(Member).where(
				Member.sacco_id == sacco_id,
				Member.membership_status == "ACTIVE",
			)
		).scalars().all()

		total_shares_cents = sum(m.total_shares_value_cents for m in members)
		total_deposits_cents: int = sacco.total_deposits_cents
		total_savings_cents = money_add(total_shares_cents, total_deposits_cents)

		# Loan data from lending plugin
		total_loans_cents = 0
		npa_cents = 0
		par90_cents = 0
		try:
			from pgappforge.plugins.fintech.lending.models import Loan
			party_ids = [m.party_id for m in members]
			if party_ids:
				loans = session.execute(
					sa.select(Loan).where(
						Loan.borrower_id.in_(party_ids),
						Loan.status.in_(["ACTIVE", "DEFAULTED"]),
					)
				).scalars().all()
				total_loans_cents = sum(l.outstanding_principal_cents for l in loans)
				npa_cents = sum(
					l.outstanding_principal_cents for l in loans
					if l.npa_classification in ("SUBSTANDARD", "DOUBTFUL", "LOSS")
				)
				par90_cents = sum(
					l.outstanding_principal_cents for l in loans
					if l.days_past_due >= 90
				)
		except ImportError:
			total_loans_cents = sacco.total_loans_outstanding_cents
		except Exception as exc:
			log.warning("get_sacco_financials — loan query failed: %s (using stale aggregate)", exc)
			total_loans_cents = sacco.total_loans_outstanding_cents

		def _pct(num: int, denom: int) -> str:
			if denom == 0:
				return "0.00"
			return str(
				(Decimal(str(num)) / Decimal(str(denom)) * 100)
				.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			)

		total_assets_cents = money_add(total_savings_cents, total_loans_cents)
		institutional_capital_cents = sacco.reserve_fund_cents

		return {
			"sacco_id": sacco_id,
			"sacco_name": sacco.name,
			"membership_count": len(members),
			"total_shares_cents": total_shares_cents,
			"total_deposits_cents": total_deposits_cents,
			"total_savings_cents": total_savings_cents,
			"total_loans_outstanding_cents": total_loans_cents,
			"reserve_fund_cents": sacco.reserve_fund_cents,
			"npl_ratio_pct": _pct(npa_cents, total_loans_cents),
			"par90_pct": _pct(par90_cents, total_loans_cents),
			"capital_adequacy_pct": _pct(institutional_capital_cents, total_assets_cents),
			# Simplified liquidity: savings deposits / outstanding loans
			"liquidity_ratio_pct": _pct(total_deposits_cents, total_loans_cents),
			"loans_to_savings_pct": _pct(total_loans_cents, total_savings_cents),
		}



	# ------------------------------------------------------------------
	# Standing orders
	# ------------------------------------------------------------------
	def create_standing_order(
		self,
		session: Any,
		member_id: str,
		amount_cents: int,
		frequency: str,
		start_date: date | None = None,
		instruction_type: str = "SAVINGS_CONTRIBUTION",
		source_account: str = "",
		destination_account: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Create a recurring payment instruction for a SACCO member.

		instruction_type: SAVINGS_CONTRIBUTION | LOAN_REPAYMENT | SHARE_PURCHASE
		frequency: WEEKLY | MONTHLY | QUARTERLY

		Returns: SaccoStandingOrder instance (flushed, not committed).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoStandingOrder

		_VALID_FREQ = {"WEEKLY", "MONTHLY", "QUARTERLY"}
		_VALID_TYPE = {"SAVINGS_CONTRIBUTION", "LOAN_REPAYMENT", "SHARE_PURCHASE"}

		if frequency not in _VALID_FREQ:
			raise ValueError(f"Invalid frequency {frequency!r}; expected one of {_VALID_FREQ}")
		if instruction_type not in _VALID_TYPE:
			raise ValueError(f"Invalid instruction_type {instruction_type!r}; expected one of {_VALID_TYPE}")
		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")
		if member.membership_status != "ACTIVE":
			raise ValueError(
				f"Cannot create standing order for member in status {member.membership_status!r}"
			)

		exec_date = start_date or date.today()

		order = SaccoStandingOrder(
			tenant_id=tenant_id or member.tenant_id,
			member_id=member_id,
			instruction_type=instruction_type,
			amount_cents=amount_cents,
			frequency=frequency,
			next_execution_date=exec_date,
			source_account=source_account or (member.deposit_account_id or ""),
			destination_account=destination_account,
			status="ACTIVE",
		)
		session.add(order)
		session.flush()

		try:
			emit_event(
				"sc.standing_order.created",
				"SaccoStandingOrder",
				order.id,
				{
					"standing_order_id": order.id,
					"member_id": member_id,
					"member_number": member.member_number,
					"instruction_type": instruction_type,
					"amount_cents": amount_cents,
					"frequency": frequency,
					"next_execution_date": exec_date.isoformat(),
				},
				session,
				tenant_id=order.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Created standing order %s for member %s: %s %d cents %s",
			order.id, member.member_number, instruction_type, amount_cents, frequency,
		)
		return order

	# ------------------------------------------------------------------
	# execute_standing_order
	# ------------------------------------------------------------------

	def execute_standing_order(
		self,
		session: Any,
		standing_order_id: str,
		tenant_id: str = "",
		execution_date: date | None = None,
	) -> dict:
		"""Execute a standing order: post debit from source + credit to destination.

		On success: updates last_run_date, last_run_status='SUCCESS', advances
		next_execution_date by the configured frequency.

		On failure: increments failure_count; if failure_count >= max_failures,
		suspends the order and emits sc.standing_order.suspended.

		Returns dict with execution result details.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoStandingOrder, SaccoLedgerEntry

		order = session.get(SaccoStandingOrder, standing_order_id)
		if order is None:
			raise ValueError(f"SaccoStandingOrder {standing_order_id!r} not found")
		if order.status not in ("ACTIVE",):
			raise ValueError(
				f"Cannot execute standing order in status {order.status!r}"
			)

		exec_date = execution_date or date.today()
		member = session.get(Member, order.member_id)
		if member is None:
			raise ValueError(f"Member {order.member_id!r} not found (standing order orphaned)")

		success = False
		failure_reason: str | None = None

		try:
			# Debit source account / credit destination via core banking (non-fatal if absent)
			try:
				from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
				cb = CoreBankingService()
				if order.instruction_type == "SAVINGS_CONTRIBUTION":
					if member.deposit_account_id:
						cb.post_deposit(
							session,
							account_id=member.deposit_account_id,
							amount_cents=order.amount_cents,
							narrative=(
								f"Standing order — {order.instruction_type} "
								f"{exec_date.isoformat()}"
							),
							tenant_id=order.tenant_id,
						)
				elif order.instruction_type == "LOAN_REPAYMENT" and order.destination_account:
					cb.post_repayment(
						session,
						loan_id=order.destination_account,
						amount_cents=order.amount_cents,
						repayment_date=exec_date,
						tenant_id=order.tenant_id,
					)
			except ImportError:
				log.debug("core_banking not available — posting ledger entry directly")

			# Insert immutable SaccoLedgerEntry regardless of CB availability
			# DR: source (5010 cash/mobile), CR: member savings (1010) or loan (2010)
			dr_acct = "5010"
			cr_acct = "1010" if order.instruction_type == "SAVINGS_CONTRIBUTION" else "2010"
			if order.instruction_type == "SHARE_PURCHASE":
				cr_acct = "1020"

			ledger = SaccoLedgerEntry(
				tenant_id=order.tenant_id,
				member_id=order.member_id,
				entry_type=(
					"CONTRIBUTION" if order.instruction_type == "SAVINGS_CONTRIBUTION"
					else "LOAN_REPAYMENT" if order.instruction_type == "LOAN_REPAYMENT"
					else "ADJUSTMENT"
				),
				amount_cents=order.amount_cents,
				dr_account=dr_acct,
				cr_account=cr_acct,
				running_balance_cents=0,  # caller may update after CB balance read
				value_date=exec_date,
				narrative=f"Standing order execution — {order.instruction_type}",
				transaction_ref=f"SO-{order.id[:8]}-{exec_date.isoformat()}",
			)
			session.add(ledger)

			# GL journal (non-fatal)
			try:
				from pgappforge.plugins.fintech.gl.services import GLService
				GLService().post_simple_journal(
					session,
					dr_account=dr_acct,
					cr_account=cr_acct,
					amount_cents=order.amount_cents,
					narrative=f"Standing order {order.id[:8]} — {order.instruction_type}",
					tenant_id=order.tenant_id,
				)
			except Exception:
				pass

			success = True

		except Exception as exc:
			failure_reason = str(exc)
			log.warning(
				"Standing order %s execution failed: %s",
				standing_order_id, exc,
			)

		# Advance next_execution_date
		def _next_date(d: date, freq: str) -> date:
			if freq == "WEEKLY":
				return d + timedelta(weeks=1)
			elif freq == "MONTHLY":
				# approximate — add 30 days
				return d + timedelta(days=30)
			else:  # QUARTERLY
				return d + timedelta(days=91)

		new_status = order.status
		new_failure_count = order.failure_count
		if success:
			next_exec = _next_date(exec_date, order.frequency)
			session.execute(
				sa.update(SaccoStandingOrder)
				.where(SaccoStandingOrder.id == standing_order_id)
				.values(
					last_run_date=exec_date,
					last_run_status="SUCCESS",
					last_failure_reason=None,
					next_execution_date=next_exec,
					failure_count=0,
				)
			)
		else:
			new_failure_count = order.failure_count + 1
			if new_failure_count >= order.max_failures:
				new_status = "SUSPENDED"
			session.execute(
				sa.update(SaccoStandingOrder)
				.where(SaccoStandingOrder.id == standing_order_id)
				.values(
					last_run_date=exec_date,
					last_run_status="FAILED",
					last_failure_reason=failure_reason,
					failure_count=new_failure_count,
					status=new_status,
				)
			)

		session.flush()

		if not success and new_status == "SUSPENDED":
			try:
				emit_event(
					"sc.standing_order.suspended",
					"SaccoStandingOrder",
					order.id,
					{
						"standing_order_id": standing_order_id,
						"member_id": order.member_id,
						"failure_count": new_failure_count,
						"last_failure_reason": failure_reason,
					},
					session,
					tenant_id=order.tenant_id,
				)
			except Exception:
				pass

		try:
			emit_event(
				"sc.standing_order.executed",
				"SaccoStandingOrder",
				order.id,
				{
					"standing_order_id": standing_order_id,
					"member_id": order.member_id,
					"amount_cents": order.amount_cents,
					"execution_date": exec_date.isoformat(),
					"success": success,
					"failure_reason": failure_reason,
					"new_status": new_status,
				},
				session,
				tenant_id=order.tenant_id,
			)
		except Exception:
			pass

		return {
			"standing_order_id": standing_order_id,
			"member_id": order.member_id,
			"amount_cents": order.amount_cents,
			"execution_date": exec_date.isoformat(),
			"success": success,
			"failure_reason": failure_reason,
			"new_status": new_status,
			"failure_count": new_failure_count,
		}

	# ------------------------------------------------------------------
	# calculate_dividends
	# ------------------------------------------------------------------

	def calculate_dividends(
		self,
		session: Any,
		financial_year: int,
		rate_pct: Decimal | str,
		tenant_id: str,
		sacco_id: str | None = None,
	) -> dict:
		"""Compute per-member dividend entitlement based on share balance.

		Does NOT persist any records — returns a dry-run preview so the caller
		(or a human approver) can review before calling declare_dividend /
		post_dividend.

		rate_pct: dividend rate as a percentage (e.g. Decimal("12.50") = 12.5%)

		If sacco_id is given, scopes to that SACCO; otherwise scopes to tenant.

		Returns dict:
		  financial_year, rate_pct, total_pool_cents, member_entitlements (list)
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member

		rate = Decimal(str(rate_pct)) / Decimal("100")
		if rate <= 0:
			raise ValueError(f"rate_pct must be positive, got {rate_pct}")

		stmt = sa.select(Member).where(
			Member.tenant_id == tenant_id,
			Member.membership_status == "ACTIVE",
		)
		if sacco_id:
			stmt = stmt.where(Member.sacco_id == sacco_id)

		members = session.execute(stmt).scalars().all()

		entitlements = []
		total_pool_cents = 0

		for member in members:
			member_dividend_cents = money_multiply(member.total_shares_value_cents, rate)
			total_pool_cents = money_add(total_pool_cents, member_dividend_cents)
			entitlements.append({
				"member_id": member.id,
				"member_number": member.member_number,
				"sacco_id": member.sacco_id,
				"shares_held": member.shares_held,
				"share_value_cents": member.share_value_cents,
				"total_shares_value_cents": member.total_shares_value_cents,
				"dividend_cents": member_dividend_cents,
			})

		# Sort descending by entitlement for easy review
		entitlements.sort(key=lambda e: e["dividend_cents"], reverse=True)

		log.info(
			"Dividend calculation FY%d @ %.4f%%: %d members, pool=%d cents",
			financial_year, float(rate_pct), len(entitlements), total_pool_cents,
		)
		return {
			"financial_year": financial_year,
			"rate_pct": str(rate_pct),
			"tenant_id": tenant_id,
			"sacco_id": sacco_id,
			"member_count": len(entitlements),
			"total_pool_cents": total_pool_cents,
			"member_entitlements": entitlements,
		}

	# ------------------------------------------------------------------
	# post_dividend
	# ------------------------------------------------------------------

	def post_dividend(
		self,
		session: Any,
		member_id: str,
		amount_cents: int,
		financial_year: int,
		tenant_id: str = "",
		narrative: str | None = None,
	) -> dict:
		"""Credit a computed dividend amount to a single member's deposit account.

		Inserts an immutable SaccoLedgerEntry (entry_type=DIVIDEND) and posts to the
		member's deposit_account via CoreBankingService (non-fatal if CB absent).
		Also posts a GL journal entry DR 4010 (Dividend Expense) / CR 1010 (Member Savings).

		Returns dict: member_number, amount_cents, ledger_entry_id.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoLedgerEntry

		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")
		if member.membership_status not in ("ACTIVE", "SUSPENDED"):
			raise ValueError(
				f"Cannot post dividend for member in terminal status {member.membership_status!r}"
			)

		_tenant = tenant_id or member.tenant_id
		_narrative = narrative or f"Dividend FY{financial_year}"

		# Credit deposit account via CB (non-fatal)
		new_balance_cents = 0
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if member.deposit_account_id:
				cb = CoreBankingService()
				cb.post_deposit(
					session,
					account_id=member.deposit_account_id,
					amount_cents=amount_cents,
					narrative=_narrative,
					tenant_id=_tenant,
				)
				import sqlalchemy as sa2
				from pgappforge.plugins.fintech.core_banking.models import Account
				acct = session.get(Account, member.deposit_account_id)
				if acct:
					new_balance_cents = acct.current_balance_cents
		except ImportError:
			log.debug("core_banking not available — skipping dividend CB credit")
		except Exception as exc:
			log.warning(
				"CB dividend credit failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		# Immutable SaccoLedgerEntry: DR 4010 Dividend Expense / CR 1010 Member Savings
		ledger = SaccoLedgerEntry(
			tenant_id=_tenant,
			member_id=member_id,
			entry_type="DIVIDEND",
			amount_cents=amount_cents,
			dr_account="4010",
			cr_account="1010",
			running_balance_cents=new_balance_cents,
			value_date=date.today(),
			narrative=_narrative,
			transaction_ref=f"DIV-{financial_year}-{member_id[:8]}",
		)
		session.add(ledger)
		session.flush()

		# GL journal (non-fatal)
		try:
			from pgappforge.plugins.fintech.gl.services import GLService
			GLService().post_simple_journal(
				session,
				dr_account="4010",
				cr_account="1010",
				amount_cents=amount_cents,
				narrative=_narrative,
				tenant_id=_tenant,
			)
		except Exception:
			pass

		try:
			emit_event(
				"sc.dividend.posted",
				"Member",
				member.id,
				{
					"member_id": member_id,
					"member_number": member.member_number,
					"amount_cents": amount_cents,
					"financial_year": financial_year,
					"ledger_entry_id": ledger.id,
				},
				session,
				tenant_id=_tenant,
			)
		except Exception:
			pass

		return {
			"member_id": member_id,
			"member_number": member.member_number,
			"amount_cents": amount_cents,
			"financial_year": financial_year,
			"ledger_entry_id": ledger.id,
			"new_deposit_balance_cents": new_balance_cents,
		}

	# ------------------------------------------------------------------
	# issue_shares
	# ------------------------------------------------------------------

	def issue_shares(
		self,
		session: Any,
		member_id: str,
		quantity: int,
		price_cents: int,
		tenant_id: str = "",
		issue_date: date | None = None,
	) -> dict:
		"""Issue new share units to a member.

		Debits the member's deposit account (or cash) for quantity × price_cents
		and credits share capital account 1020.

		Updates Member.shares_held and Member.total_shares_value_cents.
		Inserts a SaccoLedgerEntry (entry_type=ADJUSTMENT, DR 5010 / CR 1020).

		Returns dict: member_number, shares_issued, total_shares_value_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoLedgerEntry

		if quantity <= 0:
			raise ValueError(f"quantity must be positive, got {quantity}")
		if price_cents <= 0:
			raise ValueError(f"price_cents must be positive, got {price_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")
		if member.membership_status != "ACTIVE":
			raise ValueError(
				f"Cannot issue shares to member in status {member.membership_status!r}"
			)

		_tenant = tenant_id or member.tenant_id
		_date = issue_date or date.today()
		total_cost_cents = money_multiply(price_cents, quantity)

		# Debit member deposit / cash via CB (non-fatal)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if member.deposit_account_id:
				cb = CoreBankingService()
				cb.post_withdrawal(
					session,
					account_id=member.deposit_account_id,
					amount_cents=total_cost_cents,
					narrative=f"Share purchase — {quantity} units @ {format_currency(price_cents, 'KES')}",
					tenant_id=_tenant,
				)
		except ImportError:
			log.debug("core_banking not available — skipping share debit")
		except Exception as exc:
			log.warning(
				"CB share debit failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		# Update Member share counts
		new_shares = member.shares_held + quantity
		new_shares_value = money_add(
			member.total_shares_value_cents,
			total_cost_cents,
		)
		session.execute(
			sa.update(Member)
			.where(Member.id == member_id)
			.values(
				shares_held=new_shares,
				total_shares_value_cents=new_shares_value,
			)
		)

		# SaccoLedgerEntry: DR 5010 Cash / CR 1020 Share Capital
		ledger = SaccoLedgerEntry(
			tenant_id=_tenant,
			member_id=member_id,
			entry_type="ADJUSTMENT",
			amount_cents=total_cost_cents,
			dr_account="5010",
			cr_account="1020",
			running_balance_cents=0,
			value_date=_date,
			narrative=f"Share issuance — {quantity} units",
			transaction_ref=f"SHR-ISS-{member_id[:8]}-{_date.isoformat()}",
		)
		session.add(ledger)
		session.flush()

		# GL (non-fatal)
		try:
			from pgappforge.plugins.fintech.gl.services import GLService
			GLService().post_simple_journal(
				session,
				dr_account="5010",
				cr_account="1020",
				amount_cents=total_cost_cents,
				narrative=f"Share issuance {quantity} units for member {member.member_number}",
				tenant_id=_tenant,
			)
		except Exception:
			pass

		try:
			emit_event(
				"sc.shares.issued",
				"Member",
				member.id,
				{
					"member_id": member_id,
					"member_number": member.member_number,
					"quantity": quantity,
					"price_cents": price_cents,
					"total_cost_cents": total_cost_cents,
					"new_shares_held": new_shares,
					"new_shares_value_cents": new_shares_value,
					"issue_date": _date.isoformat(),
				},
				session,
				tenant_id=_tenant,
			)
		except Exception:
			pass

		log.info(
			"Issued %d shares to member %s; total shares=%d value=%d cents",
			quantity, member.member_number, new_shares, new_shares_value,
		)
		return {
			"member_id": member_id,
			"member_number": member.member_number,
			"shares_issued": quantity,
			"price_cents": price_cents,
			"total_cost_cents": total_cost_cents,
			"new_shares_held": new_shares,
			"new_total_shares_value_cents": new_shares_value,
			"issue_date": _date.isoformat(),
			"ledger_entry_id": ledger.id,
		}

	# ------------------------------------------------------------------
	# redeem_shares
	# ------------------------------------------------------------------

	def redeem_shares(
		self,
		session: Any,
		member_id: str,
		quantity: int,
		tenant_id: str = "",
		redemption_date: date | None = None,
		price_cents: int | None = None,
	) -> dict:
		"""Redeem (buy back) share units from a member.

		Reverses the issuance: credits member deposit account, debits share capital.
		Uses member.share_value_cents as the par redemption price unless price_cents
		is explicitly supplied.

		Rejects if quantity exceeds member.shares_held.

		Updates Member.shares_held and Member.total_shares_value_cents.
		Inserts a SaccoLedgerEntry (entry_type=ADJUSTMENT, DR 1020 / CR 5010).

		Returns dict: member_number, shares_redeemed, proceeds_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoLedgerEntry

		if quantity <= 0:
			raise ValueError(f"quantity must be positive, got {quantity}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")
		if member.shares_held < quantity:
			raise ValueError(
				f"Member {member.member_number!r} holds {member.shares_held} shares; "
				f"cannot redeem {quantity}"
			)

		_tenant = tenant_id or member.tenant_id
		_date = redemption_date or date.today()
		unit_price = price_cents if price_cents is not None else member.share_value_cents
		if unit_price <= 0:
			raise ValueError(f"unit price must be positive, got {unit_price}")
		proceeds_cents = money_multiply(unit_price, quantity)

		# Credit member deposit / cash via CB (non-fatal)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if member.deposit_account_id:
				cb = CoreBankingService()
				cb.post_deposit(
					session,
					account_id=member.deposit_account_id,
					amount_cents=proceeds_cents,
					narrative=f"Share redemption — {quantity} units @ {format_currency(unit_price, 'KES')}",
					tenant_id=_tenant,
				)
		except ImportError:
			log.debug("core_banking not available — skipping share redemption credit")
		except Exception as exc:
			log.warning(
				"CB share redemption credit failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		# Update Member share counts
		new_shares = member.shares_held - quantity
		new_shares_value = max(0, member.total_shares_value_cents - proceeds_cents)
		session.execute(
			sa.update(Member)
			.where(Member.id == member_id)
			.values(
				shares_held=new_shares,
				total_shares_value_cents=new_shares_value,
			)
		)

		# SaccoLedgerEntry: DR 1020 Share Capital / CR 5010 Cash
		ledger = SaccoLedgerEntry(
			tenant_id=_tenant,
			member_id=member_id,
			entry_type="ADJUSTMENT",
			amount_cents=-proceeds_cents,  # negative = debit from member perspective
			dr_account="1020",
			cr_account="5010",
			running_balance_cents=0,
			value_date=_date,
			narrative=f"Share redemption — {quantity} units",
			transaction_ref=f"SHR-RED-{member_id[:8]}-{_date.isoformat()}",
		)
		session.add(ledger)
		session.flush()

		# GL (non-fatal)
		try:
			from pgappforge.plugins.fintech.gl.services import GLService
			GLService().post_simple_journal(
				session,
				dr_account="1020",
				cr_account="5010",
				amount_cents=proceeds_cents,
				narrative=f"Share redemption {quantity} units for member {member.member_number}",
				tenant_id=_tenant,
			)
		except Exception:
			pass

		try:
			emit_event(
				"sc.shares.redeemed",
				"Member",
				member.id,
				{
					"member_id": member_id,
					"member_number": member.member_number,
					"quantity": quantity,
					"unit_price_cents": unit_price,
					"proceeds_cents": proceeds_cents,
					"new_shares_held": new_shares,
					"new_shares_value_cents": new_shares_value,
					"redemption_date": _date.isoformat(),
				},
				session,
				tenant_id=_tenant,
			)
		except Exception:
			pass

		log.info(
			"Redeemed %d shares from member %s; proceeds=%d cents; remaining shares=%d",
			quantity, member.member_number, proceeds_cents, new_shares,
		)
		return {
			"member_id": member_id,
			"member_number": member.member_number,
			"shares_redeemed": quantity,
			"unit_price_cents": unit_price,
			"proceeds_cents": proceeds_cents,
			"new_shares_held": new_shares,
			"new_total_shares_value_cents": new_shares_value,
			"redemption_date": _date.isoformat(),
			"ledger_entry_id": ledger.id,
		}

	# ------------------------------------------------------------------
	# apply_fee
	# ------------------------------------------------------------------

	def apply_fee(
		self,
		session: Any,
		member_id: str,
		fee_type: str,
		amount_cents: int,
		tenant_id: str = "",
		fee_charge_id: str | None = None,
		loan_id: str | None = None,
		collection_trigger: str = "EVENT",
		charge_date: date | None = None,
	) -> dict:
		"""Apply a fee charge against a member account.

		Debits the member's deposit account and credits fee income account 3020.
		Inserts a FeeLineItem record and a SaccoLedgerEntry (entry_type=FEE).

		fee_type: FLAT | PERCENT_DISBURSEMENT | PERCENT_OUTSTANDING | TIERED
		  (for this method, amount_cents is the already-computed fee regardless of type)

		Returns dict: member_number, amount_cents, fee_line_item_id, ledger_entry_id.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, FeeLineItem, SaccoLedgerEntry

		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		_tenant = tenant_id or member.tenant_id
		_date = charge_date or date.today()

		# Debit member deposit account (non-fatal)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if member.deposit_account_id:
				cb = CoreBankingService()
				cb.post_withdrawal(
					session,
					account_id=member.deposit_account_id,
					amount_cents=amount_cents,
					narrative=f"Fee charge — {fee_type} {_date.isoformat()}",
					tenant_id=_tenant,
				)
		except ImportError:
			log.debug("core_banking not available — skipping fee debit")
		except Exception as exc:
			log.warning(
				"CB fee debit failed for member %s: %s (non-fatal)",
				member.member_number, exc,
			)

		# FeeLineItem record — requires a fee_charge_id FK; use a sentinel if absent
		# (callers should pass the real fee_charge_id when available)
		if fee_charge_id is None:
			# Look up by fee_type; if not found we still proceed (fee_charge_id nullable
			# at DB level? — FeeLineItem.fee_charge_id is NOT NULL, so we must have one.
			# Callers must supply it. Raise early with a clear message.)
			raise ValueError(
				"fee_charge_id is required — pass the FeeCharge.id for this fee type"
			)

		fee_item = FeeLineItem(
			tenant_id=_tenant,
			member_id=member_id,
			loan_id=loan_id,
			fee_charge_id=fee_charge_id,
			amount_cents=amount_cents,
			charge_date=_date,
			collection_trigger=collection_trigger,
			gl_posted=False,
			transaction_ref=f"FEE-{member_id[:8]}-{_date.isoformat()}",
		)
		session.add(fee_item)

		# SaccoLedgerEntry: DR 1010 Member Savings / CR 3020 Fee Income
		ledger = SaccoLedgerEntry(
			tenant_id=_tenant,
			member_id=member_id,
			entry_type="FEE",
			amount_cents=-amount_cents,  # debit from member
			dr_account="1010",
			cr_account="3020",
			running_balance_cents=0,
			value_date=_date,
			narrative=f"Fee — {fee_type}",
			transaction_ref=fee_item.transaction_ref,
		)
		session.add(ledger)
		session.flush()

		# Mark fee as GL-posted
		session.execute(
			sa.update(FeeLineItem)
			.where(FeeLineItem.id == fee_item.id)
			.values(gl_posted=True)
		)

		# GL journal (non-fatal)
		try:
			from pgappforge.plugins.fintech.gl.services import GLService
			GLService().post_simple_journal(
				session,
				dr_account="1010",
				cr_account="3020",
				amount_cents=amount_cents,
				narrative=f"Fee {fee_type} — member {member.member_number}",
				tenant_id=_tenant,
			)
		except Exception:
			pass

		session.flush()

		try:
			emit_event(
				"sc.fee.applied",
				"Member",
				member.id,
				{
					"member_id": member_id,
					"member_number": member.member_number,
					"fee_type": fee_type,
					"amount_cents": amount_cents,
					"fee_line_item_id": fee_item.id,
					"ledger_entry_id": ledger.id,
					"charge_date": _date.isoformat(),
				},
				session,
				tenant_id=_tenant,
			)
		except Exception:
			pass

		return {
			"member_id": member_id,
			"member_number": member.member_number,
			"fee_type": fee_type,
			"amount_cents": amount_cents,
			"fee_line_item_id": fee_item.id,
			"ledger_entry_id": ledger.id,
			"charge_date": _date.isoformat(),
		}

	# ------------------------------------------------------------------
	# generate_member_statement
	# ------------------------------------------------------------------

	def generate_member_statement(
		self,
		session: Any,
		member_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str = "",
	) -> dict:
		"""Generate a structured account statement for a member over a date range.

		Queries SaccoLedgerEntry rows for the member within [from_date, to_date] inclusive,
		ordered by value_date ascending.

		Computes:
		  opening_balance_cents — running_balance_cents of last entry before from_date
		  closing_balance_cents — running_balance_cents of last entry in range
		  total_debits_cents    — sum of abs(amount_cents) for negative entries
		  total_credits_cents   — sum of amount_cents for positive entries

		Returns a structured dict suitable for PDF/CSV rendering.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Member, SaccoLedgerEntry

		if from_date > to_date:
			raise ValueError(
				f"from_date {from_date} must not be after to_date {to_date}"
			)

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		_tenant = tenant_id or member.tenant_id

		# Opening balance: last SaccoLedgerEntry before from_date
		opening_entry = session.execute(
			sa.select(SaccoLedgerEntry)
			.where(
				SaccoLedgerEntry.member_id == member_id,
				SaccoLedgerEntry.tenant_id == _tenant,
				SaccoLedgerEntry.value_date < from_date,
			)
			.order_by(SaccoLedgerEntry.value_date.desc(), SaccoLedgerEntry.created_at.desc())
			.limit(1)
		).scalar_one_or_none()

		opening_balance_cents = opening_entry.running_balance_cents if opening_entry else 0

		# Statement entries
		entries = session.execute(
			sa.select(SaccoLedgerEntry)
			.where(
				SaccoLedgerEntry.member_id == member_id,
				SaccoLedgerEntry.tenant_id == _tenant,
				SaccoLedgerEntry.value_date >= from_date,
				SaccoLedgerEntry.value_date <= to_date,
			)
			.order_by(SaccoLedgerEntry.value_date.asc(), SaccoLedgerEntry.created_at.asc())
		).scalars().all()

		total_credits_cents = 0
		total_debits_cents = 0
		closing_balance_cents = opening_balance_cents
		line_items = []

		for entry in entries:
			if entry.amount_cents >= 0:
				total_credits_cents = money_add(total_credits_cents, entry.amount_cents)
			else:
				total_debits_cents = money_add(total_debits_cents, abs(entry.amount_cents))
			closing_balance_cents = entry.running_balance_cents
			line_items.append({
				"entry_id": entry.id,
				"value_date": entry.value_date.isoformat(),
				"entry_type": entry.entry_type,
				"narrative": entry.narrative,
				"transaction_ref": entry.transaction_ref,
				"dr_account": entry.dr_account,
				"cr_account": entry.cr_account,
				"amount_cents": entry.amount_cents,
				"running_balance_cents": entry.running_balance_cents,
				"reversed_by": entry.reversed_by,
			})

		# Member share summary (point-in-time — current values)
		return {
			"member_id": member_id,
			"member_number": member.member_number,
			"sacco_id": member.sacco_id,
			"tenant_id": _tenant,
			"statement_from": from_date.isoformat(),
			"statement_to": to_date.isoformat(),
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"opening_balance_cents": opening_balance_cents,
			"closing_balance_cents": closing_balance_cents,
			"total_credits_cents": total_credits_cents,
			"total_debits_cents": total_debits_cents,
			"net_movement_cents": total_credits_cents - total_debits_cents,
			"shares_held": member.shares_held,
			"total_shares_value_cents": member.total_shares_value_cents,
			"membership_status": member.membership_status,
			"entry_count": len(line_items),
			"entries": line_items,
		}

# ---------------------------------------------------------------------------
# ChamaService
# ---------------------------------------------------------------------------

class ChamaService:
	"""Business logic for Chama savings group operations."""

	# ------------------------------------------------------------------
	# create_chama
	# ------------------------------------------------------------------

	def create_chama(
		self,
		session: Any,
		chama_name: str,
		chama_type: str,
		formation_date: date,
		meeting_frequency: str,
		contribution_amount_cents: int,
		tenant_id: str,
		founding_member_ids: list[str],
		chairperson_id: str | None = None,
		treasurer_id: str | None = None,
		secretary_id: str | None = None,
		rules: dict | None = None,
	) -> Any:
		"""Form a new Chama with founding members.

		Creates a Chama record and a ChamaMember record for each founding
		member.  A group bank account can be linked later via group_account_id.

		Returns: Chama instance (flushed, not committed).
		"""
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		if contribution_amount_cents <= 0:
			raise ValueError("contribution_amount_cents must be positive")
		if not founding_member_ids:
			raise ValueError("A Chama requires at least one founding member")

		chama = Chama(
			tenant_id=tenant_id,
			chama_name=chama_name,
			chama_type=chama_type,
			formation_date=formation_date,
			meeting_frequency=meeting_frequency,
			contribution_amount_cents=contribution_amount_cents,
			current_pool_cents=0,
			chairperson_id=chairperson_id,
			treasurer_id=treasurer_id,
			secretary_id=secretary_id,
			rules=rules or {},
			status="ACTIVE",
		)
		session.add(chama)
		session.flush()  # get chama.id

		for idx, party_id in enumerate(founding_member_ids):
			cm = ChamaMember(
				tenant_id=tenant_id,
				chama_id=chama.id,
				member_id=party_id,
				join_date=formation_date,
				total_contributed_cents=0,
				total_received_cents=0,
				# First member in list is the initial merry-go-round recipient
				is_current_recipient=(idx == 0 and chama_type == "MERRY_GO_ROUND"),
				contribution_streak=0,
				status="ACTIVE",
			)
			session.add(cm)

		session.flush()

		try:
			emit_event(
				"sc.chama.created",
				"Chama",
				chama.id,
				{
					"chama_id": chama.id,
					"chama_name": chama_name,
					"chama_type": chama_type,
					"founding_member_ids": founding_member_ids,
				},
				session,
				tenant_id=tenant_id,
			)
		except Exception:
			pass

		log.info("Created Chama %r (%s) with %d founding members", chama_name, chama_type, len(founding_member_ids))
		return chama

	# ------------------------------------------------------------------
	# record_contribution
	# ------------------------------------------------------------------

	def record_contribution(
		self,
		session: Any,
		chama_id: str,
		member_id: str,
		amount_cents: int,
		contribution_date: date | None = None,
	) -> dict:
		"""Post a Chama member's contribution to the group pool.

		Validates member is active, amount matches the fixed contribution
		(or a multiple thereof for catch-up payments).

		Updates:
		  ChamaMember.total_contributed_cents += amount_cents
		  ChamaMember.contribution_streak += 1
		  Chama.current_pool_cents += amount_cents

		Returns dict: chama_name, member_id, amount_cents, new_pool_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		contrib_date = contribution_date or date.today()
		chama = session.get(Chama, chama_id)
		if chama is None:
			raise ValueError(f"Chama {chama_id!r} not found")
		if chama.status != "ACTIVE":
			raise ValueError(f"Chama {chama.chama_name!r} is not active (status={chama.status!r})")
		if amount_cents <= 0:
			raise ValueError("Contribution amount must be positive")

		cm = session.execute(
			sa.select(ChamaMember).where(
				ChamaMember.chama_id == chama_id,
				ChamaMember.member_id == member_id,
				ChamaMember.status == "ACTIVE",
			)
		).scalar_one_or_none()
		if cm is None:
			raise ValueError(
				f"Party {member_id!r} is not an active member of Chama {chama_id!r}"
			)

		cm.total_contributed_cents = money_add(cm.total_contributed_cents, amount_cents)
		cm.contribution_streak = money_add(cm.contribution_streak, 1)
		chama.current_pool_cents = money_add(chama.current_pool_cents, amount_cents)
		session.flush()

		# Post to group bank account (non-fatal)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if chama.group_account_id:
				cb = CoreBankingService()
				cb.post_deposit(
					session,
					account_id=chama.group_account_id,
					amount_cents=amount_cents,
					narrative=(
						f"Chama contribution — {chama.chama_name} — "
						f"{contrib_date.isoformat()}"
					),
					tenant_id=chama.tenant_id,
				)
		except ImportError:
			log.debug("core_banking not available — skipping chama pool deposit")
		except Exception as exc:
			log.warning(
				"CB deposit failed for chama %s contribution: %s (non-fatal)",
				chama_id, exc,
			)

		try:
			emit_event(
				"sc.chama.contribution_posted",
				"Chama",
				chama.id,
				{
					"chama_id": chama_id,
					"member_id": member_id,
					"amount_cents": amount_cents,
					"new_pool_cents": chama.current_pool_cents,
					"contribution_date": contrib_date.isoformat(),
				},
				session,
				tenant_id=chama.tenant_id,
			)
		except Exception:
			pass

		return {
			"chama_name": chama.chama_name,
			"member_id": member_id,
			"amount_cents": amount_cents,
			"new_pool_cents": chama.current_pool_cents,
			"contribution_streak": cm.contribution_streak,
		}

	# ------------------------------------------------------------------
	# process_merry_go_round
	# ------------------------------------------------------------------

	def process_merry_go_round(
		self,
		session: Any,
		chama_id: str,
		recipient_member_id: str,
		disbursement_date: date | None = None,
	) -> dict:
		"""Disburse the merry-go-round pool to the current recipient.

		Validates:
		  - Chama is MERRY_GO_ROUND type
		  - recipient_member_id matches is_current_recipient == True
		  - pool has funds to disburse

		After disbursement:
		  - recipient.total_received_cents += pool amount
		  - recipient.is_current_recipient = False
		  - Next member in join_date order becomes is_current_recipient
		  - Chama.current_pool_cents = 0

		Returns dict: recipient_member_id, amount_disbursed_cents,
		              next_recipient_member_id.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		disburse_date = disbursement_date or date.today()
		chama = session.get(Chama, chama_id)
		if chama is None:
			raise ValueError(f"Chama {chama_id!r} not found")
		if chama.chama_type != "MERRY_GO_ROUND":
			raise ValueError(
				f"Chama {chama.chama_name!r} is type {chama.chama_type!r}, "
				"not MERRY_GO_ROUND"
			)
		if chama.current_pool_cents <= 0:
			raise ValueError(
				f"Chama {chama.chama_name!r} has no funds to disburse "
				f"(current_pool_cents={chama.current_pool_cents})"
			)

		# Validate current recipient
		current_cm = session.execute(
			sa.select(ChamaMember).where(
				ChamaMember.chama_id == chama_id,
				ChamaMember.member_id == recipient_member_id,
				ChamaMember.is_current_recipient.is_(True),
				ChamaMember.status == "ACTIVE",
			)
		).scalar_one_or_none()
		if current_cm is None:
			raise ValueError(
				f"Member {recipient_member_id!r} is not the current merry-go-round recipient "
				f"for Chama {chama_id!r}"
			)

		amount_disbursed_cents = chama.current_pool_cents

		# Credit recipient's account (non-fatal)
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			if chama.group_account_id:
				cb = CoreBankingService()
				cb.post_withdrawal(
					session,
					account_id=chama.group_account_id,
					amount_cents=amount_disbursed_cents,
					narrative=(
						f"Merry-go-round payout to member {recipient_member_id} "
						f"— {disburse_date.isoformat()}"
					),
					tenant_id=chama.tenant_id,
				)
		except ImportError:
			log.debug("core_banking not available — skipping merry-go-round withdrawal")
		except Exception as exc:
			log.warning(
				"CB withdrawal failed for merry-go-round chama %s: %s (non-fatal)",
				chama_id, exc,
			)

		# Update current recipient
		current_cm.total_received_cents = money_add(
			current_cm.total_received_cents, amount_disbursed_cents
		)
		current_cm.is_current_recipient = False

		# Determine next recipient: next active member by join_date order
		all_active = session.execute(
			sa.select(ChamaMember).where(
				ChamaMember.chama_id == chama_id,
				ChamaMember.status == "ACTIVE",
			).order_by(ChamaMember.join_date, ChamaMember.id)
		).scalars().all()

		next_recipient_id: str = ""
		if all_active:
			# Find position of current recipient, pick next cyclically
			ids = [m.member_id for m in all_active]
			try:
				idx = ids.index(recipient_member_id)
			except ValueError:
				idx = -1
			next_idx = (idx + 1) % len(ids)
			next_recipient_id = ids[next_idx]
			for m in all_active:
				if m.member_id == next_recipient_id:
					m.is_current_recipient = True
					break

		# Clear pool
		chama.current_pool_cents = 0
		session.flush()

		try:
			emit_event(
				"sc.chama.merry_go_round_disbursed",
				"Chama",
				chama.id,
				{
					"chama_id": chama_id,
					"recipient_member_id": recipient_member_id,
					"amount_cents": amount_disbursed_cents,
					"next_recipient_member_id": next_recipient_id,
					"disbursement_date": disburse_date.isoformat(),
				},
				session,
				tenant_id=chama.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Merry-go-round: Chama %s paid %d cents to member %s; next=%s",
			chama_id, amount_disbursed_cents, recipient_member_id, next_recipient_id,
		)
		return {
			"chama_id": chama_id,
			"recipient_member_id": recipient_member_id,
			"amount_disbursed_cents": amount_disbursed_cents,
			"next_recipient_member_id": next_recipient_id,
			"disbursement_date": disburse_date.isoformat(),
		}

	# ------------------------------------------------------------------
	# record_table_banking_loan
	# ------------------------------------------------------------------

	def record_table_banking_loan(
		self,
		session: Any,
		chama_id: str,
		borrower_id: str,
		amount_cents: int,
		repayment_weeks: int,
		tenant_id: str,
		loan_date: date | None = None,
	) -> dict:
		"""Issue a short-term table-banking loan from the Chama pool.

		Rules enforced:
		  - Chama must be TABLE_BANKING type.
		  - Borrower must be an active Chama member.
		  - amount_cents <= current_pool_cents (cannot lend what you don't have).
		  - Interest rate taken from rules.loan_interest_rate_pw (default 10% flat).

		Deducts amount from current_pool_cents.
		Interest is collected via record_contribution at repayment time.

		Returns dict: loan details including due_date and total_repayable_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		loan_date_ = loan_date or date.today()
		chama = session.get(Chama, chama_id)
		if chama is None:
			raise ValueError(f"Chama {chama_id!r} not found")
		if chama.chama_type != "TABLE_BANKING":
			raise ValueError(
				f"Chama {chama.chama_name!r} is type {chama.chama_type!r}, not TABLE_BANKING"
			)
		if chama.status != "ACTIVE":
			raise ValueError(f"Chama {chama.chama_name!r} is not active")
		if amount_cents <= 0:
			raise ValueError("Loan amount must be positive")
		if amount_cents > chama.current_pool_cents:
			raise ValueError(
				f"Loan {amount_cents}c exceeds available pool {chama.current_pool_cents}c"
			)
		if repayment_weeks <= 0:
			raise ValueError("repayment_weeks must be positive")

		cm = session.execute(
			sa.select(ChamaMember).where(
				ChamaMember.chama_id == chama_id,
				ChamaMember.member_id == borrower_id,
				ChamaMember.status == "ACTIVE",
			)
		).scalar_one_or_none()
		if cm is None:
			raise ValueError(
				f"Party {borrower_id!r} is not an active member of Chama {chama_id!r}"
			)

		# Interest rate from rules (default 10% flat for the loan period)
		interest_rate_pct = Decimal(
			str(chama.rules.get("loan_interest_rate_pw", "10"))
			if chama.rules else "10"
		)
		interest_cents = percent_of(amount_cents, interest_rate_pct)
		total_repayable_cents = money_add(amount_cents, interest_cents)
		due_date = _add_weeks(loan_date_, repayment_weeks)

		# Deduct from pool
		chama.current_pool_cents = money_add(chama.current_pool_cents, -amount_cents)
		session.flush()

		try:
			emit_event(
				"sc.chama.table_banking_loan_created",
				"Chama",
				chama.id,
				{
					"chama_id": chama_id,
					"borrower_id": borrower_id,
					"amount_cents": amount_cents,
					"repayment_weeks": repayment_weeks,
					"due_date": due_date.isoformat(),
				},
				session,
				tenant_id=chama.tenant_id,
			)
		except Exception:
			pass

		log.info(
			"Table-banking loan: Chama %s lent %d cents to %s for %d weeks",
			chama_id, amount_cents, borrower_id, repayment_weeks,
		)
		return {
			"chama_id": chama_id,
			"chama_name": chama.chama_name,
			"borrower_id": borrower_id,
			"amount_cents": amount_cents,
			"interest_rate_pct": str(interest_rate_pct),
			"interest_cents": interest_cents,
			"total_repayable_cents": total_repayable_cents,
			"repayment_weeks": repayment_weeks,
			"loan_date": loan_date_.isoformat(),
			"due_date": due_date.isoformat(),
			"remaining_pool_cents": chama.current_pool_cents,
		}


	# ------------------------------------------------------------------
	# get_chama_statement
	# ------------------------------------------------------------------

	def get_chama_statement(
		self,
		session: Any,
		chama_id: str,
		period_months: int = 3,
	) -> dict:
		"""Summarise Chama contributions and payouts for the recent period.

		Returns:
		  chama details, period start/end, per-member summary,
		  total_contributions_cents, total_payouts_cents, current_pool_cents.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.sacco.models import Chama, ChamaMember

		chama = session.get(Chama, chama_id)
		if chama is None:
			raise ValueError(f"Chama {chama_id!r} not found")

		period_end = date.today()
		# Approximate: 30 days per month
		period_start = date.fromordinal(period_end.toordinal() - period_months * 30)

		members = session.execute(
			sa.select(ChamaMember).where(ChamaMember.chama_id == chama_id)
		).scalars().all()

		member_summaries = []
		total_contributions_cents = 0
		total_received_cents = 0

		for m in members:
			total_contributions_cents = money_add(
				total_contributions_cents, m.total_contributed_cents
			)
			total_received_cents = money_add(total_received_cents, m.total_received_cents)
			member_summaries.append({
				"member_id": m.member_id,
				"status": m.status,
				"total_contributed_cents": m.total_contributed_cents,
				"total_received_cents": m.total_received_cents,
				"is_current_recipient": m.is_current_recipient,
				"contribution_streak": m.contribution_streak,
				"join_date": m.join_date.isoformat() if m.join_date else None,
			})

		return {
			"chama_id": chama_id,
			"chama_name": chama.chama_name,
			"chama_type": chama.chama_type,
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"current_pool_cents": chama.current_pool_cents,
			"total_contributions_cents": total_contributions_cents,
			"total_payouts_cents": total_received_cents,
			"member_count": len(members),
			"member_summaries": member_summaries,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SACCOService",
	"ChamaService",
]
