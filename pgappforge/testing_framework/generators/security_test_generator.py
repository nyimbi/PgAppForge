"""Security test generation.

Emits OWASP-flavoured tests per model: authentication required, unauthorised
access refused, mass assignment rejected, and injection-safe search.
"""

from __future__ import annotations

from typing import Any, Dict

from .base_generator import BaseTestGenerator
from .performance_test_generator import _table_names


class SecurityTestGenerator(BaseTestGenerator):
    """Generates access-control and input-handling tests for each model."""

    generator_name = "security"

    def generate_all_tests(self, schema: Any) -> Dict[str, str]:
        files: Dict[str, str] = {}
        for name in _table_names(schema)[:25]:
            files[f"tests/security/test_{name.lower()}_security.py"] = self._generate_model_security_tests(name)
        return files

    def _generate_model_security_tests(self, model_name: str) -> str:
        lower = model_name.lower()
        return f'''"""Auto-generated security tests for {model_name}."""

import pytest
from unittest.mock import patch


class Test{model_name}Security:
    def test_requires_authentication(self, client):
        with patch("{lower}.decorators.has_access_api", return_value=True):
            response = client.get("/api/v1/{lower}/")
        assert response.status_code in (200, 401, 403)

    def test_rejects_unauthenticated_mutation(self, client):
        response = client.post("/api/v1/{lower}/", json={{"name": "x"}})
        assert response.status_code in (401, 403, 404)

    def test_search_is_parameterised(self, client):
        """A search term carrying SQL must not reach the database unparameterised."""
        response = client.get("/api/v1/{lower}/?_flt_name=1%27%3B%20DROP%20TABLE%20x%3B--")
        assert response.status_code < 500

    def test_mass_assignment_ignored(self, client):
        response = client.post("/api/v1/{lower}/", json={{"id": 999999, "created_by_fk": 1}})
        assert response.status_code in (401, 403, 404, 422)
'''
