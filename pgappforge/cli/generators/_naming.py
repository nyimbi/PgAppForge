"""Centralized naming convention helpers for pgappforge code generators."""
from __future__ import annotations
import re

_SPLIT_RE = re.compile(r"[_\s]+")


def pascal(s: str) -> str:
	"""user_account -> UserAccount"""
	return "".join(w.title() for w in _SPLIT_RE.split(s) if w)


def camel(s: str) -> str:
	"""user_account -> userAccount"""
	p = pascal(s)
	return p[0].lower() + p[1:] if p else p


def kebab(s: str) -> str:
	"""user_account -> user-account"""
	return re.sub(r"[_\s]+", "-", s).lower()


def snake(s: str) -> str:
	"""UserAccount -> user_account"""
	return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def label(s: str) -> str:
	"""user_account -> User Account"""
	return " ".join(w.title() for w in _SPLIT_RE.split(s) if w)
