"""BaseGenerator ABC for pgappforge code generators."""
from __future__ import annotations
import shutil
from abc import ABC, abstractmethod
from pathlib import Path


class BaseGenerator(ABC):
	"""Extend this to create a code generator.

	Implement render() to return a dict mapping relative output paths to file content.
	Call write() to atomically commit files to disk (disk-space checked, path-traversal safe).
	"""

	output_dir: Path

	@abstractmethod
	def render(self) -> dict[str, str]:
		"""Return {relative_path: content}. Must NOT write to disk."""

	def write(self) -> None:
		"""Atomically write all rendered files to output_dir."""
		files = self.render()
		self._write_files(files)

	def _write_files(self, files: dict[str, str]) -> None:
		"""Atomic write with disk-space check and SecurePathValidator protection."""
		self.output_dir.mkdir(parents=True, exist_ok=True)
		needed = sum(len(c.encode("utf-8")) for c in files.values()) * 2
		free = shutil.disk_usage(self.output_dir).free
		if free < needed + 50 * 1024 * 1024:
			raise OSError(
				f"Insufficient disk space: need {needed / 1e6:.1f} MB, "
				f"have {free / 1e6:.1f} MB free at {self.output_dir}"
			)
		from .file_operations import GenerationTransaction
		with GenerationTransaction(self.output_dir, type(self).__name__) as tx:
			tx.add_files(files)
