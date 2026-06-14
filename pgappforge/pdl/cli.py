"""CLI commands for the PDL subsystem.

Register with the ``gen`` / ``forge`` groups in
``pgappforge/cli/__init__.py``::

    from pgappforge.pdl.cli import gen_pdl, designer_cmd
    gen.add_command(gen_pdl)
    forge.add_command(designer_cmd)
"""
from __future__ import annotations

import logging
import subprocess
import webbrowser
from pathlib import Path

import click

log = logging.getLogger(__name__)


@click.command("pdl")
@click.argument("pdl_file", type=click.Path(exists=True, path_type=Path))
@click.option(
	"--output-dir", "-o",
	default="./generated", show_default=True,
	type=click.Path(path_type=Path),
	help="Root directory for generated files.",
)
@click.option("--dry-run", is_flag=True, help="Print what would be generated without writing files.")
@click.option(
	"--only", multiple=True,
	type=click.Choice(["model", "migration", "view", "api", "tests"]),
	help="Restrict to specific artifact types (repeatable).",
)
@click.option(
	"--apply-migrations", is_flag=True, default=False,
	help="Run 'uv run flask db upgrade' after writing migration files.",
)
@click.option("--with-docker", is_flag=True, default=False, help="Write Dockerfile + docker-compose.yml.")
@click.option("--with-k8s",    is_flag=True, default=False, help="Write Kubernetes manifests to k8s/.")
@click.option("--with-ci",     is_flag=True, default=False, help="Write .github/workflows/ci.yml.")
def gen_pdl(
	pdl_file: Path,
	output_dir: Path,
	dry_run: bool,
	only: tuple[str, ...],
	apply_migrations: bool,
	with_docker: bool,
	with_k8s: bool,
	with_ci: bool,
) -> None:
	"""Generate PgAppForge artifacts from a PDL YAML schema file.

	PDL_FILE is the path to the ``.pdl.yaml`` schema file.

	\b
	Examples:
	    flask forge gen pdl invoice.pdl.yaml
	    flask forge gen pdl schema.yaml -o ./src --apply-migrations
	    flask forge gen pdl schema.yaml --with-docker --with-k8s --with-ci
	    flask forge gen pdl schema.yaml --only model --only migration --dry-run
	"""
	from pgappforge.pdl.schema import PDLSchema
	from pgappforge.pdl.generators import PDLCodeGenerator

	try:
		schema = PDLSchema.from_yaml(pdl_file)
	except Exception as exc:
		click.echo(f"PDL parse error: {exc}", err=True)
		raise SystemExit(1)

	gen = PDLCodeGenerator()
	click.echo(f"PDL  : {pdl_file}")
	click.echo(f"Space: {len(schema.entities)} entit{'y' if len(schema.entities) == 1 else 'ies'}")

	migration_files: list[Path] = []

	# ── Per-entity artifacts ─────────────────────────────────────────────
	for entity in schema.entities:
		artifacts = list(only) if only else entity.generate
		click.echo(f"\n  {entity.name}  →  {entity.table}  [{', '.join(artifacts)}]")

		if dry_run:
			for art in artifacts:
				click.echo(f"    → {art}  (dry run)")
			continue

		try:
			results = gen.generate_entity(entity, schema)
		except Exception as exc:
			click.echo(f"  ✗ {entity.name}: {exc}", err=True)
			raise SystemExit(1)

		for artifact_name, code in results.items():
			out_file = output_dir / entity.name.lower() / artifact_name
			out_file.parent.mkdir(parents=True, exist_ok=True)
			out_file.write_text(code, encoding="utf-8")
			click.echo(f"    ✓ {out_file}")
			if "migration" in artifact_name:
				migration_files.append(out_file)

	# ── Schema-level files ────────────────────────────────────────────────
	if not dry_run and (with_docker or with_k8s or with_ci):
		click.echo("\n  Schema-level files:")
		schema_files: dict[str, str] = {}
		if with_docker or with_ci:
			schema_files.update(gen.generate_schema_files(schema))
		if with_k8s:
			schema_files.update(gen.generate_k8s(schema))

		for fname, content in schema_files.items():
			skip = (
				(not with_docker and fname in ("Dockerfile", "docker-compose.yml"))
				or (not with_ci and fname == ".github/workflows/ci.yml")
				or (not with_k8s and fname.startswith("k8s/"))
			)
			if skip:
				continue
			out_file = output_dir / fname
			out_file.parent.mkdir(parents=True, exist_ok=True)
			out_file.write_text(content, encoding="utf-8")
			click.echo(f"    ✓ {out_file}")

	if dry_run:
		click.echo("\n  (dry run — no files written)")
		return

	click.echo(f"\nGenerated → {output_dir}/")

	# ── Auto-apply migrations ─────────────────────────────────────────────
	if apply_migrations:
		if not migration_files:
			click.echo("  No migration files generated — skipping flask db upgrade")
		else:
			click.echo(f"\n  Applying {len(migration_files)} migration(s)…")
			result = subprocess.run(
				["uv", "run", "flask", "db", "upgrade"],
				capture_output=True, text=True,
			)
			if result.returncode == 0:
				click.echo("  ✓ flask db upgrade succeeded")
			else:
				click.echo(f"  ✗ flask db upgrade failed (exit {result.returncode})", err=True)
				if result.stderr:
					click.echo(f"    {result.stderr.strip()}", err=True)


@click.command("designer")
@click.option("--port", default=8080, show_default=True, help="App server port.")
@click.option("--open", "open_browser", is_flag=True, default=False, help="Open in default browser.")
def designer_cmd(port: int, open_browser: bool) -> None:
	"""Open the PDL Visual Entity Designer.

	The designer runs as part of the main Flask application.
	Start the server with ``flask run --port PORT`` first.

	\b
	Example:
	    flask run --port 8080 &
	    flask forge designer --open
	"""
	url = f"http://localhost:{port}/pdl-designer/"
	click.echo(f"\n  PDL Entity Designer")
	click.echo(f"  URL  : {url}")
	click.echo(f"  Docs : Import 500+ capability models, draw FK relationships,")
	click.echo(f"         generate models / migrations / REST API / tests / K8s.")
	if open_browser:
		webbrowser.open(url)
		click.echo(f"\n  Opened {url}")
	else:
		click.echo(f"\n  Tip: pass --open to launch in browser automatically.")


__all__ = ["gen_pdl", "designer_cmd"]
