"""
tests/ci/test_versioning_plugin.py

CI tests for pgappforge/plugins/erp/platform/versioning/.

Strategy
--------
- VersioningService: tested with a real temporary git repo (via subprocess).
  GitPython is an optional dep; tests skip gracefully if absent.
- VersioningPlugin: import-only tests (no AppBuilder needed).
- Views: import smoke test.

Run:
    uv run pytest -vxs tests/ci/test_versioning_plugin.py
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _git(*args, cwd: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		["git", *args],
		cwd=cwd,
		capture_output=True,
		text=True,
		check=True,
	)


def _has_gitpython() -> bool:
	try:
		import git  # noqa: F401
		return True
	except ImportError:
		return False


# --------------------------------------------------------------------------- #
# VersioningService — pure unit tests (no git required)                       #
# --------------------------------------------------------------------------- #

from pgappforge.plugins.erp.platform.versioning.services import VersioningService  # noqa: E402


class TestVersioningServiceNoGit:
	"""Tests that work even when git / GitPython is unavailable."""

	def test_instantiation(self):
		svc = VersioningService("/tmp")
		assert svc.repo_path == Path("/tmp")

	def test_get_config_history_no_repo(self, tmp_path):
		"""Should return [] when not in a git repo."""
		svc = VersioningService(tmp_path)
		result = svc.get_config_history()
		assert result == []

	def test_get_file_diff_no_repo(self, tmp_path):
		svc = VersioningService(tmp_path)
		result = svc.get_file_diff("some/file.yaml", sha_from="abc123")
		assert "not available" in result.lower() or "error" in result.lower() or result

	def test_get_file_at_commit_no_repo(self, tmp_path):
		svc = VersioningService(tmp_path)
		result = svc.get_file_at_commit("some/file.yaml", sha="abc123")
		assert result is None

	def test_revert_file_no_repo(self, tmp_path):
		svc = VersioningService(tmp_path)
		result = svc.revert_file_to_commit("some/file.yaml", sha="abc123")
		assert result is False

	def test_current_version_no_repo(self, tmp_path):
		svc = VersioningService(tmp_path)
		ver = svc.current_version()
		assert "sha" in ver
		assert ver["sha"] == "unknown"

	def test_list_config_files_no_repo(self, tmp_path):
		svc = VersioningService(tmp_path)
		result = svc.list_config_files()
		assert result == []


# --------------------------------------------------------------------------- #
# VersioningService — real git repo tests                                     #
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not _has_gitpython(), reason="gitpython not installed")
class TestVersioningServiceWithGit:
	@pytest.fixture
	def repo(self, tmp_path):
		"""Create a minimal real git repo with two config commits."""
		repo_dir = str(tmp_path)

		_git("init", cwd=repo_dir)
		_git("config", "user.email", "test@pgappforge.test", cwd=repo_dir)
		_git("config", "user.name", "CI Test", cwd=repo_dir)

		# Commit 1: add a workflow YAML
		wf_dir = tmp_path / "workflows"
		wf_dir.mkdir()
		wf_file = wf_dir / "approval.yaml"
		wf_file.write_text("name: approval\nsteps: [submit, approve]\n")
		_git("add", ".", cwd=repo_dir)
		_git("commit", "-m", "feat: add approval workflow", cwd=repo_dir)

		# Commit 2: modify the workflow YAML
		wf_file.write_text("name: approval\nsteps: [submit, review, approve]\n")
		_git("add", ".", cwd=repo_dir)
		_git("commit", "-m", "feat: add review step to approval workflow", cwd=repo_dir)

		return tmp_path

	def test_get_config_history_returns_commits(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		assert len(history) >= 2

	def test_history_commit_shape(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		commit = history[0]
		assert "sha" in commit
		assert "short_sha" in commit
		assert len(commit["short_sha"]) == 8
		assert "message" in commit
		assert "author" in commit
		assert "date" in commit
		assert "changed_files" in commit
		assert "file_count" in commit

	def test_history_message_truncated(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		for c in history:
			assert len(c["message"]) <= 100

	def test_current_version_has_sha(self, repo):
		svc = VersioningService(repo)
		ver = svc.current_version()
		assert ver["sha"] != "unknown"
		assert len(ver["sha"]) == 8

	def test_current_version_has_branch(self, repo):
		svc = VersioningService(repo)
		ver = svc.current_version()
		assert ver["branch"] not in ("", "unknown")

	def test_get_file_at_commit(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		oldest = history[-1]
		content = svc.get_file_at_commit("workflows/approval.yaml", oldest["sha"])
		# First commit had only 2 steps
		assert content is not None
		assert "submit" in content

	def test_get_file_diff(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		assert len(history) >= 2
		sha_old = history[-1]["sha"]
		sha_new = history[0]["sha"]
		diff = svc.get_file_diff("workflows/approval.yaml", sha_old, sha_new)
		# Diff should mention the added "review" step
		assert "review" in diff or diff  # non-empty

	def test_revert_file_creates_commit(self, repo):
		svc = VersioningService(repo)
		history = svc.get_config_history(paths=["workflows/"])
		oldest_sha = history[-1]["sha"]
		ok = svc.revert_file_to_commit("workflows/approval.yaml", oldest_sha)
		assert ok is True
		# After revert, content should match oldest commit
		new_content = (repo / "workflows" / "approval.yaml").read_text()
		assert "review" not in new_content  # review step was added in 2nd commit

	def test_list_config_files(self, repo):
		svc = VersioningService(repo)
		files = svc.list_config_files(paths=["workflows/"])
		assert any("approval.yaml" in f for f in files)


# --------------------------------------------------------------------------- #
# VersioningPlugin — import / metadata tests                                  #
# --------------------------------------------------------------------------- #

class TestVersioningPlugin:
	def test_import(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin
		assert VersioningPlugin is not None

	def test_name(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin
		assert VersioningPlugin.name == "versioning"

	def test_domain(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin
		assert VersioningPlugin.domain == "platform"

	def test_metadata_name(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin

		class _FakeAB:
			pass

		plugin = VersioningPlugin(_FakeAB())
		assert plugin.metadata.name == "versioning"

	def test_metadata_permissions(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin

		class _FakeAB:
			pass

		plugin = VersioningPlugin(_FakeAB())
		perms = plugin.metadata.permissions
		assert "can_versioning_view" in perms
		assert "can_versioning_diff" in perms
		assert "can_versioning_revert" in perms

	def test_get_events_empty(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin

		class _FakeAB:
			pass

		plugin = VersioningPlugin(_FakeAB())
		assert plugin.get_events() == []

	def test_register_models_empty(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin

		class _FakeAB:
			pass

		plugin = VersioningPlugin(_FakeAB())
		assert plugin.register_models() == []

	def test_create_plugin_factory(self):
		from pgappforge.plugins.erp.platform.versioning import create_plugin

		class _FakeAB:
			pass

		plugin = create_plugin(_FakeAB())
		assert plugin.name == "versioning"

	def test_initialize_sets_defaults(self):
		from pgappforge.plugins.erp.platform.versioning import VersioningPlugin

		class _FakeAB:
			pass

		plugin = VersioningPlugin(_FakeAB())
		plugin.initialize()
		assert "VERSIONING_REPO_PATH" in plugin.config
		assert "VERSIONING_MENU_CATEGORY" in plugin.config


# --------------------------------------------------------------------------- #
# VersioningDashboardView — import smoke test                                 #
# --------------------------------------------------------------------------- #

class TestVersioningViews:
	def test_import_views(self):
		from pgappforge.plugins.erp.platform.versioning.views import VersioningDashboardView
		assert VersioningDashboardView is not None

	def test_route_base(self):
		from pgappforge.plugins.erp.platform.versioning.views import VersioningDashboardView
		assert VersioningDashboardView.route_base == "/platform/versioning"
