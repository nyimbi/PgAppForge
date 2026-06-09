from __future__ import annotations

from flask import render_template
from pgappforge import ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.hcm.skills.models import (
	EmployeeSkill,
	Skill,
	SkillCategory,
	SkillDomain,
)

__all__ = [
	"SkillDomainView",
	"SkillView",
	"EmployeeSkillView",
	"SkillsDashboardView",
]


class SkillDomainView(ModelView):
	datamodel = SQLAInterface(SkillDomain)
	list_columns = ["code", "name", "description"]
	add_exclude_columns = ["id", "created_on", "changed_on", "categories"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "categories"]
	search_columns = ["code", "name"]


class SkillView(ModelView):
	datamodel = SQLAInterface(Skill)
	list_columns = ["code", "name", "category", "is_technical"]
	add_exclude_columns = ["id", "created_on", "changed_on", "employee_skills", "job_requirements"]
	edit_exclude_columns = ["id", "created_on", "changed_on", "employee_skills", "job_requirements"]
	search_columns = ["code", "name"]


class EmployeeSkillView(ModelView):
	datamodel = SQLAInterface(EmployeeSkill)
	list_columns = ["employee_id", "skill", "proficiency_level", "verified_at", "endorsed_by"]
	add_exclude_columns = ["id", "created_on", "changed_on"]
	edit_exclude_columns = ["id", "created_on", "changed_on"]
	search_columns = ["employee_id"]


class SkillsDashboardView(BaseERPView):
	route_base = "/hcm/skills"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.hcm.skills.models import (
				EmployeeSkill,
				Skill,
				SkillDomain,
			)
			sess = self._session()
			domain_count = self._count(SkillDomain, session=sess)
			skill_count = self._count(Skill, session=sess)
			employee_skill_count = self._count(EmployeeSkill, session=sess)
		except Exception:
			domain_count = skill_count = employee_skill_count = 0
		kpi_html = self.kpi_cards([
			{"label": "Skill Domains", "value": domain_count, "icon": "fa-sitemap", "color": "#1a56db"},
			{"label": "Total Skills", "value": skill_count, "icon": "fa-star", "color": "#0e9f6e"},
			{"label": "Employee Skills", "value": employee_skill_count, "icon": "fa-user-check", "color": "#f59e0b"},
		])
		return render_template(
			"appbuilder/hcm_skills/skills_explorer.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)
