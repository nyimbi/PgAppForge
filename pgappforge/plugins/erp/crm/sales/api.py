"""REST APIs for ERP models in this plugin."""
from __future__ import annotations

from pgappforge.api import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface

from .models import (
	SalesAccount,
	SalesContact,
	Lead,
	Opportunity,
	Activity,
	SalesTarget,
	SalesForecast,
)


class SalesAccountRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/sales_account'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(SalesAccount)
	list_columns = [
		'id',
		'tenant_id',
		'party_id',
		'account_number',
		'name',
		'account_type',
		'industry',
		'website',
		'phone',
		'email',
		'annual_revenue_cents',
		'employee_count',
		'parent_account_id',
		'owner_id',
		'health_score',
		'churn_risk_score',
		'lifetime_value_cents',
		'nps_score',
		'billing_address',
		'shipping_address',
		'description',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'party_id',
		'account_number',
		'name',
		'account_type',
		'industry',
		'website',
		'phone',
		'email',
		'annual_revenue_cents',
		'employee_count',
		'parent_account_id',
		'owner_id',
		'health_score',
		'churn_risk_score',
		'lifetime_value_cents',
		'nps_score',
		'billing_address',
		'shipping_address',
		'description',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'party_id',
		'account_number',
		'name',
		'account_type',
		'industry',
		'website',
		'phone',
		'email',
		'employee_count',
		'parent_account_id',
		'owner_id',
		'description',
	]


class SalesContactRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/sales_contact'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(SalesContact)
	list_columns = [
		'id',
		'tenant_id',
		'party_id',
		'account_id',
		'first_name',
		'last_name',
		'salutation',
		'title',
		'department',
		'email',
		'phone',
		'mobile',
		'linkedin_url',
		'seniority',
		'is_decision_maker',
		'is_influencer',
		'opted_out_email',
		'opted_out_phone',
		'owner_id',
		'last_activity_at',
		'engagement_score',
		'status',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'party_id',
		'account_id',
		'first_name',
		'last_name',
		'salutation',
		'title',
		'department',
		'email',
		'phone',
		'mobile',
		'linkedin_url',
		'seniority',
		'is_decision_maker',
		'is_influencer',
		'opted_out_email',
		'opted_out_phone',
		'owner_id',
		'last_activity_at',
		'engagement_score',
		'status',
	]
	edit_columns = add_columns
	search_columns = [
		'party_id',
		'account_id',
		'first_name',
		'last_name',
		'title',
		'department',
		'email',
		'phone',
		'opted_out_email',
		'opted_out_phone',
		'owner_id',
		'status',
	]


class LeadRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/lead'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(Lead)
	list_columns = [
		'id',
		'tenant_id',
		'first_name',
		'last_name',
		'company',
		'title',
		'email',
		'phone',
		'source',
		'campaign_id',
		'utm_source',
		'utm_medium',
		'utm_campaign',
		'score',
		'grade',
		'status',
		'assigned_to',
		'converted_at',
		'converted_account_id',
		'converted_contact_id',
		'converted_opportunity_id',
		'description',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'first_name',
		'last_name',
		'company',
		'title',
		'email',
		'phone',
		'source',
		'campaign_id',
		'utm_source',
		'utm_medium',
		'utm_campaign',
		'score',
		'grade',
		'status',
		'assigned_to',
		'converted_at',
		'converted_account_id',
		'converted_contact_id',
		'converted_opportunity_id',
		'description',
	]
	edit_columns = add_columns
	search_columns = [
		'first_name',
		'last_name',
		'title',
		'email',
		'phone',
		'source',
		'campaign_id',
		'utm_source',
		'utm_campaign',
		'status',
		'converted_account_id',
		'converted_contact_id',
	]


class OpportunityRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/opportunity'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(Opportunity)
	list_columns = [
		'id',
		'tenant_id',
		'account_id',
		'contact_id',
		'opportunity_name',
		'stage',
		'amount_cents',
		'currency_code',
		'probability',
		'forecast_category',
		'expected_close_date',
		'owner_id',
		'lead_source',
		'type',
		'reason_won',
		'reason_lost',
		'competitor',
		'closed_at',
		'einstein_score',
		'next_step',
		'description',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'account_id',
		'contact_id',
		'opportunity_name',
		'stage',
		'amount_cents',
		'currency_code',
		'probability',
		'forecast_category',
		'expected_close_date',
		'owner_id',
		'lead_source',
		'type',
		'reason_won',
		'reason_lost',
		'competitor',
		'closed_at',
		'einstein_score',
		'next_step',
		'description',
	]
	edit_columns = add_columns
	search_columns = [
		'account_id',
		'contact_id',
		'opportunity_name',
		'currency_code',
		'forecast_category',
		'owner_id',
		'lead_source',
		'type',
		'reason_won',
		'reason_lost',
		'description',
	]


class ActivityRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/activity'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(Activity)
	list_columns = [
		'id',
		'tenant_id',
		'activity_type',
		'subject',
		'description',
		'status',
		'direction',
		'outcome',
		'duration_minutes',
		'activity_date',
		'contact_id',
		'account_id',
		'opportunity_id',
		'owner_id',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'activity_type',
		'subject',
		'description',
		'status',
		'direction',
		'outcome',
		'duration_minutes',
		'activity_date',
		'contact_id',
		'account_id',
		'opportunity_id',
		'owner_id',
	]
	edit_columns = add_columns
	search_columns = [
		'activity_type',
		'subject',
		'description',
		'status',
		'direction',
		'outcome',
		'contact_id',
		'account_id',
		'owner_id',
	]


class SalesTargetRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/sales_target'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(SalesTarget)
	list_columns = [
		'id',
		'tenant_id',
		'owner_id',
		'period_id',
		'target_type',
		'product_id',
		'target_amount_cents',
		'achieved_amount_cents',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'owner_id',
		'period_id',
		'target_type',
		'product_id',
		'target_amount_cents',
		'achieved_amount_cents',
	]
	edit_columns = add_columns
	search_columns = [
		'owner_id',
		'period_id',
		'target_type',
	]


class SalesForecastRestApi(ModelRestApi):
	resource_name = 'erp/crm/sales/sales_forecast'
	openapi_spec_tag = 'CRM'
	swagger_ui_method_ui_order = "alpha"
	datamodel = SQLAInterface(SalesForecast)
	list_columns = [
		'id',
		'tenant_id',
		'period_id',
		'owner_id',
		'pipeline_cents',
		'best_case_cents',
		'commit_cents',
		'closed_cents',
		'ai_forecast_cents',
		'submitted_at',
		'created_at',
		'updated_at',
	]
	show_columns = list_columns
	add_columns = [
		'tenant_id',
		'period_id',
		'owner_id',
		'pipeline_cents',
		'best_case_cents',
		'commit_cents',
		'closed_cents',
		'ai_forecast_cents',
		'submitted_at',
	]
	edit_columns = add_columns
	search_columns = [
		'period_id',
		'owner_id',
	]
