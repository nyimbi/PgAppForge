"""
pgappforge/plugins/erp/platform/versioning/services.py

Git-backed versioning service for PgAppForge configuration files.

Tracks changes to:
  - custom_fields/*.yaml   (citizen-dev customisations)
  - workflows/*.yaml       (workflow definitions)
  - pgappforge.yaml        (environment config)
  - semantic.yaml files    (business metrics definitions)

Requires gitpython:  pip install gitpython
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Paths considered "configuration" for history/diff queries
_DEFAULT_CONFIG_PATHS: list[str] = [
	"custom_fields/",
	"workflows/",
	"pgappforge.yaml",
	"pgappforge/plugins/fintech/sacco/semantic.yaml",
]


class VersioningService:
	"""Git-backed versioning for PgAppForge configuration files.

	All methods are non-fatal: when git is unavailable (no repo, GitPython
	not installed, bare repo, etc.) they return empty/None rather than
	raising so callers never need to guard.

	Example::

		svc = VersioningService("/path/to/project")
		history = svc.get_config_history(limit=20)
		diff = svc.get_file_diff("custom_fields/ledger.yaml", sha_from="abc123")
	"""

	def __init__(self, repo_path: str | Path = ".") -> None:
		self.repo_path = Path(repo_path).resolve()
		self._repo: Any = None  # git.Repo, lazy

	# ------------------------------------------------------------------ #
	# Internal                                                             #
	# ------------------------------------------------------------------ #

	def _get_repo(self) -> Any:
		"""Lazy-load the git.Repo.  Returns None if unavailable."""
		if self._repo is not None:
			return self._repo
		try:
			import git  # type: ignore[import]
			self._repo = git.Repo(self.repo_path, search_parent_directories=True)
		except ImportError:
			log.info(
				"VersioningService: GitPython not installed. "
				"Run `pip install gitpython` to enable git versioning."
			)
		except Exception as exc:
			log.debug("VersioningService: git repo not found at %s — %s", self.repo_path, exc)
		return self._repo

	# ------------------------------------------------------------------ #
	# Public API                                                           #
	# ------------------------------------------------------------------ #

	def get_config_history(
		self,
		paths: list[str] | None = None,
		limit: int = 50,
	) -> list[dict[str, Any]]:
		"""Return recent commits that touched configuration files.

		Args:
			paths: File/directory paths to filter by.  Defaults to the standard
			       config paths (custom_fields/, workflows/, pgappforge.yaml, …).
			limit: Maximum number of commits to inspect.  Commits that touch
			       *only* non-config paths are excluded from the returned list.

		Returns:
			List of commit dicts, newest first::

			    {
			        "sha":          str,   # full 40-char SHA
			        "short_sha":    str,   # 8-char abbreviation
			        "message":      str,   # first 100 chars of commit message
			        "author":       str,   # "Name <email>"
			        "author_email": str,
			        "date":         str,   # ISO-8601
			        "changed_files":list[str],  # config files touched
			        "file_count":   int,
			    }
		"""
		repo = self._get_repo()
		if repo is None:
			return []

		watch_paths = paths if paths is not None else _DEFAULT_CONFIG_PATHS

		commits: list[dict[str, Any]] = []
		try:
			for commit in repo.iter_commits(paths=watch_paths, max_count=limit):
				changed: list[str] = list(commit.stats.files.keys())
				config_files = [
					f for f in changed
					if any(f.startswith(p.rstrip("/")) for p in watch_paths)
				]
				if not config_files:
					continue
				commits.append(
					{
						"sha": commit.hexsha,
						"short_sha": commit.hexsha[:8],
						"message": commit.message.strip()[:100],
						"author": str(commit.author),
						"author_email": commit.author.email,
						"date": datetime.fromtimestamp(commit.committed_date).isoformat(),
						"changed_files": config_files,
						"file_count": len(config_files),
					}
				)
		except Exception as exc:
			log.debug("get_config_history error: %s", exc)

		return commits

	def get_file_diff(
		self,
		file_path: str,
		sha_from: str,
		sha_to: str = "HEAD",
	) -> str:
		"""Unified diff of *file_path* between two commits.

		Args:
			file_path: Repo-relative path to the file.
			sha_from:  Base commit SHA (older side of the diff).
			sha_to:    Head commit SHA (newer side).  Defaults to ``"HEAD"``.

		Returns:
			Unified diff string, or a short error/info message if unavailable.
		"""
		repo = self._get_repo()
		if repo is None:
			return "Git not available"

		try:
			commit_from = repo.commit(sha_from)
			commit_to = repo.commit(sha_to)
			diffs = commit_from.diff(commit_to, paths=[file_path], create_patch=True)

			if not diffs:
				return "No changes"

			parts: list[str] = []
			for d in diffs:
				raw = d.diff
				parts.append(
					raw.decode("utf-8", errors="replace")
					if isinstance(raw, bytes)
					else str(raw)
				)
			return "\n".join(parts) or "No changes"
		except Exception as exc:
			log.debug("get_file_diff %s [%s..%s] error: %s", file_path, sha_from, sha_to, exc)
			return f"Error: {exc}"

	def get_file_at_commit(self, file_path: str, sha: str) -> str | None:
		"""Return file contents as they existed at *sha*.

		Args:
			file_path: Repo-relative path.
			sha:       Commit SHA.

		Returns:
			File contents as a string, or ``None`` if unavailable/missing.
		"""
		repo = self._get_repo()
		if repo is None:
			return None

		try:
			commit = repo.commit(sha)
			blob = commit.tree[file_path]
			return blob.data_stream.read().decode("utf-8", errors="replace")
		except Exception as exc:
			log.debug("get_file_at_commit %s@%s error: %s", file_path, sha, exc)
			return None

	def revert_file_to_commit(self, file_path: str, sha: str) -> bool:
		"""Restore *file_path* to its state at *sha* and create a revert commit.

		This modifies the working tree and creates a new git commit.  It does
		*not* amend history.

		Args:
			file_path: Repo-relative path.
			sha:       Target commit SHA.

		Returns:
			``True`` on success, ``False`` on any failure.
		"""
		repo = self._get_repo()
		if repo is None:
			return False

		try:
			content = self.get_file_at_commit(file_path, sha)
			if content is None:
				log.error("revert_file_to_commit: %s@%s — file not found in commit", file_path, sha)
				return False

			full_path = self.repo_path / file_path
			full_path.parent.mkdir(parents=True, exist_ok=True)
			full_path.write_text(content, encoding="utf-8")

			repo.index.add([file_path])
			repo.index.commit(f"revert: restore {file_path} to {sha[:8]}")

			log.info("Reverted %s to commit %s", file_path, sha[:8])
			return True
		except Exception as exc:
			log.error("revert_file_to_commit %s@%s failed: %s", file_path, sha, exc)
			return False

	def current_version(self) -> dict[str, Any]:
		"""Return current HEAD info.

		Returns::

		    {
		        "sha":         str,        # 8-char short SHA or "unknown"
		        "branch":      str,        # active branch name
		        "is_dirty":    bool,       # uncommitted changes present
		        "dirty_files": list[str],  # paths with uncommitted changes
		    }
		"""
		repo = self._get_repo()
		if repo is None:
			return {"sha": "unknown", "branch": "unknown", "is_dirty": False, "dirty_files": []}

		try:
			dirty_files = [item.a_path for item in repo.index.diff(None)]
			return {
				"sha": repo.head.commit.hexsha[:8],
				"branch": repo.active_branch.name,
				"is_dirty": repo.is_dirty(),
				"dirty_files": dirty_files,
			}
		except Exception as exc:
			return {
				"sha": "unknown",
				"branch": "unknown",
				"is_dirty": False,
				"dirty_files": [],
				"error": str(exc),
			}

	def list_config_files(self, paths: list[str] | None = None) -> list[str]:
		"""Return all tracked config files matching *paths*.

		Args:
			paths: Prefixes to filter by.  Defaults to ``_DEFAULT_CONFIG_PATHS``.

		Returns:
			Sorted list of repo-relative file paths.
		"""
		repo = self._get_repo()
		if repo is None:
			return []

		watch_paths = paths if paths is not None else _DEFAULT_CONFIG_PATHS
		try:
			all_files = [
				blob.path
				for blob in repo.head.commit.tree.traverse()
				if blob.type == "blob"
			]
			return sorted(
				f for f in all_files
				if any(f.startswith(p.rstrip("/")) for p in watch_paths)
			)
		except Exception as exc:
			log.debug("list_config_files error: %s", exc)
			return []


__all__ = ["VersioningService"]
