"""CLI help and training commands for Flask-AppBuilder.

Registered under the 'fab' group:
  flask fab help topics
  flask fab help search QUERY
  flask fab help topic TOPIC_NAME
  flask fab training list
  flask fab training start MODULE
"""
from __future__ import annotations

import textwrap

import click

from flask_appbuilder.help.views import TOPICS, TRAINING_MODULES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERM_WIDTH = 88


def _hr(char: str = "─") -> str:
	return char * _TERM_WIDTH


def _header(text: str) -> None:
	click.echo(click.style(_hr("═"), fg="cyan"))
	click.echo(click.style(f"  {text}", fg="cyan", bold=True))
	click.echo(click.style(_hr("═"), fg="cyan"))


def _section(text: str) -> None:
	click.echo("")
	click.echo(click.style(text, fg="yellow", bold=True))
	click.echo(click.style(_hr("─"), fg="yellow"))


def _wrap(text: str, indent: int = 2) -> str:
	"""Wrap a block of text, preserving blank lines between paragraphs."""
	prefix = " " * indent
	lines = text.splitlines()
	out: list[str] = []
	for line in lines:
		if line.strip() == "":
			out.append("")
		else:
			wrapped = textwrap.fill(line, width=_TERM_WIDTH - indent,
									initial_indent=prefix,
									subsequent_indent=prefix)
			out.append(wrapped)
	return "\n".join(out)


def _match_topic(name: str) -> tuple[str, dict] | None:
	"""Return (slug, topic) for an exact or prefix match on slug, else None."""
	name = name.lower().strip().replace(" ", "-")
	# Exact match first
	if name in TOPICS:
		return name, TOPICS[name]
	# Prefix match
	for slug, topic in TOPICS.items():
		if slug.startswith(name):
			return slug, topic
	return None


def _match_module(name: str) -> dict | None:
	"""Return a training module dict for an exact or prefix slug match."""
	name = name.lower().strip().replace(" ", "-")
	for mod in TRAINING_MODULES:
		if mod["slug"] == name or mod["slug"].startswith(name):
			return mod
	return None


# ---------------------------------------------------------------------------
# 'help' command group
# ---------------------------------------------------------------------------

@click.group("help", invoke_without_command=True)
@click.pass_context
def help_group(ctx: click.Context) -> None:
	"""Flask-AppBuilder help system.

	Sub-commands: topics, search, topic
	"""
	if ctx.invoked_subcommand is None:
		click.echo(ctx.get_help())


@help_group.command("topics")
def help_topics() -> None:
	"""List all available help topics."""
	_header("Flask-AppBuilder Help Topics")
	for slug, topic in TOPICS.items():
		click.echo(
			f"  {click.style(slug, fg='green', bold=True):<35}"
			f"  {topic['title']}"
		)
	click.echo("")
	click.echo(
		click.style(
			"  Use:  flask fab help topic <TOPIC_NAME>  to read a topic.",
			fg="white",
			dim=True,
		)
	)
	click.echo("")


@help_group.command("search")
@click.argument("query")
def help_search(query: str) -> None:
	"""Search help topics by keyword.

	\b
	Examples:
	  flask fab help search crud
	  flask fab help search "oauth ldap"
	"""
	q = query.lower()
	matches: list[tuple[str, dict]] = []
	for slug, topic in TOPICS.items():
		haystack = (
			topic["title"].lower()
			+ " "
			+ topic["keywords"].lower()
			+ " "
			+ topic["content"].lower()
		)
		if q in haystack:
			matches.append((slug, topic))

	_header(f'Search results for "{query}"')
	if not matches:
		click.echo(click.style(f"  No topics found for '{query}'.", fg="red"))
		click.echo("")
		return

	for slug, topic in matches:
		click.echo(
			f"  {click.style(slug, fg='green', bold=True):<35}  {topic['title']}"
		)
	click.echo("")
	click.echo(
		click.style(
			f"  {len(matches)} result(s). "
			"Use:  flask fab help topic <TOPIC_NAME>  to read.",
			fg="white",
			dim=True,
		)
	)
	click.echo("")


@help_group.command("topic")
@click.argument("topic_name")
def help_topic(topic_name: str) -> None:
	"""Display a specific help topic.

	TOPIC_NAME is the topic slug (prefix matching supported).

	\b
	Examples:
	  flask fab help topic getting-started
	  flask fab help topic crud
	  flask fab help topic api
	"""
	result = _match_topic(topic_name)
	if result is None:
		click.echo(
			click.style(
				f"  Topic '{topic_name}' not found. "
				"Run 'flask fab help topics' to list available topics.",
				fg="red",
			)
		)
		raise SystemExit(1)

	slug, topic = result
	_header(topic["title"])
	click.echo("")
	# Print content preserving its preformatted structure
	for line in topic["content"].splitlines():
		if line.startswith("  ") or line.startswith("\t"):
			# Code / indented block — emit verbatim in a dim style
			click.echo(click.style("  " + line, fg="white", dim=True))
		elif line and line == line.upper() and len(line) < 60:
			# Section heading heuristic (all-caps short line)
			click.echo(click.style(f"\n  {line}", fg="yellow", bold=True))
		else:
			click.echo(f"  {line}")
	click.echo("")
	click.echo(click.style(_hr("─"), fg="cyan", dim=True))
	click.echo(
		click.style(
			"  Keywords: " + topic["keywords"],
			fg="white",
			dim=True,
		)
	)
	click.echo("")


# ---------------------------------------------------------------------------
# 'training' command group
# ---------------------------------------------------------------------------

@click.group("training", invoke_without_command=True)
@click.pass_context
def training_group(ctx: click.Context) -> None:
	"""Interactive training modules for Flask-AppBuilder.

	Sub-commands: list, start
	"""
	if ctx.invoked_subcommand is None:
		click.echo(ctx.get_help())


@training_group.command("list")
def training_list() -> None:
	"""List available training modules."""
	_header("Flask-AppBuilder Training Modules")
	for mod in TRAINING_MODULES:
		steps = len(mod["steps"])
		click.echo(
			f"  {click.style(mod['slug'], fg='green', bold=True):<30}"
			f"  {steps:>2} steps  —  {mod['title']}"
		)
		click.echo(
			click.style(
				f"  {'':30}            {mod['description']}",
				fg="white",
				dim=True,
			)
		)
		click.echo("")
	click.echo(
		click.style(
			"  Use:  flask fab training start <MODULE>  to begin.",
			fg="white",
			dim=True,
		)
	)
	click.echo("")


@training_group.command("start")
@click.argument("module")
@click.option(
	"--step",
	default=1,
	show_default=True,
	help="Start at a specific step number (1-based).",
)
@click.option(
	"--all",
	"show_all",
	is_flag=True,
	default=False,
	help="Print all steps without pausing.",
)
def training_start(module: str, step: int, show_all: bool) -> None:
	"""Start an interactive training sequence.

	MODULE is the module slug (prefix matching supported).

	\b
	Examples:
	  flask fab training start getting-started
	  flask fab training start rest-api --step 2
	  flask fab training start first-crud --all
	"""
	mod = _match_module(module)
	if mod is None:
		click.echo(
			click.style(
				f"  Module '{module}' not found. "
				"Run 'flask fab training list' to see available modules.",
				fg="red",
			)
		)
		raise SystemExit(1)

	steps = mod["steps"]
	total = len(steps)

	if not 1 <= step <= total:
		click.echo(
			click.style(
				f"  Step {step} is out of range — module has {total} steps.",
				fg="red",
			)
		)
		raise SystemExit(1)

	_header(f"Training: {mod['title']}")
	click.echo(f"  {mod['description']}")
	click.echo(f"  {total} steps total — starting at step {step}.\n")

	for idx, s in enumerate(steps[step - 1:], start=step):
		_section(f"Step {idx}/{total}: {s['title']}")
		# Render step content with syntax-like colouring
		for line in s["content"].splitlines():
			stripped = line.strip()
			if stripped.startswith("#"):
				click.echo(click.style("  " + line, fg="bright_black"))
			elif stripped == "":
				click.echo("")
			else:
				click.echo(click.style("  " + line, fg="white"))
		click.echo("")

		if not show_all and idx < total:
			try:
				click.pause(
					info=click.style(
						f"  Press any key for step {idx + 1}  (Ctrl-C to quit)…",
						fg="cyan",
					)
				)
			except (KeyboardInterrupt, EOFError):
				click.echo("\n  Training interrupted.")
				return

	click.echo(click.style(_hr("═"), fg="green"))
	click.echo(click.style(f"  Module '{mod['title']}' complete!", fg="green", bold=True))
	click.echo(click.style(_hr("═"), fg="green"))
	click.echo("")
	click.echo(
		click.style(
			"  Next:  flask fab training list   to explore more modules.",
			fg="white",
			dim=True,
		)
	)
	click.echo("")
