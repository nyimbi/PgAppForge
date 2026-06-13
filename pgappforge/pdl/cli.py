"""CLI command: ``flask forge gen pdl``

Register this with the ``gen`` group in
``pgappforge/cli/__init__.py``::

    from pgappforge.pdl.cli import gen_pdl
    gen.add_command(gen_pdl)
"""
from __future__ import annotations

import logging
from pathlib import Path

import click

log = logging.getLogger(__name__)


@click.command("pdl")
@click.argument("pdl_file", type=click.Path(exists=True, path_type=Path))
@click.option(
	"--output-dir", "-o",
	default="./generated",
	show_default=True,
	type=click.Path(path_type=Path),
	help="Root directory that receives generated files.",
)
@click.option(
	"--dry-run",
	is_flag=True,
	help="Print what would be generated without writing any files.",
)
@click.option(
	"--only",
	multiple=True,
	type=click.Choice(["model", "migration", "view", "api", "tests"]),
	help="Restrict generation to specific artifact types (repeatable).",
)
def gen_pdl(pdl_file: Path, output_dir: Path, dry_run: bool, only: tuple[str, ...]) -> None:
	"""Generate PgAppForge artifacts from a PDL YAML schema file.

	PDL_FILE is the path to the ``.pdl.yaml`` schema file.

	\b
	Minimal example (entity.pdl.yaml):

	    version: "1.0"
	    namespace: myapp.finance
	    entities:
	      - name: SupplierInvoice
	        table: fin_supplier_invoice
	        description: "AP supplier invoice"
	        fields:
	          - name: vendor_id
	            type: uuid
	            fk: "Vendor.id"
	            required: true
	          - name: amount_cents
	            type: money
	            required: true
	          - name: status
	            type: enum
	            choices: [PENDING, APPROVED, PAID, REJECTED]
	            default: PENDING

	\b
	Usage:
	    flask forge gen pdl invoice.pdl.yaml
	    flask forge gen pdl invoice.pdl.yaml -o ./src/generated
	    flask forge gen pdl invoice.pdl.yaml --only model --only migration --dry-run
	"""
	from pgappforge.pdl.schema import PDLSchema
	from pgappforge.pdl.generators import PDLCodeGenerator

	try:
		schema = PDLSchema.from_yaml(pdl_file)
	except Exception as exc:
		click.echo(f"PDL parse error: {exc}", err=True)
		raise SystemExit(1)

	gen = PDLCodeGenerator()

	click.echo(f"PDL: {pdl_file}")
	click.echo(f"  {len(schema.entities)} entit{'y' if len(schema.entities) == 1 else 'ies'} found")

	for entity in schema.entities:
		artifacts = list(only) if only else entity.generate
		click.echo(f"\n  Entity : {entity.name}  ->  {entity.table}")
		click.echo(f"  Artifacts: {', '.join(artifacts)}")

		if dry_run:
			for art in artifacts:
				click.echo(f"    -> {art}  (dry run)")
			continue

		try:
			results = gen.generate_entity(entity, schema)
		except Exception as exc:
			click.echo(f"Generation error ({entity.name}): {exc}", err=True)
			raise SystemExit(1)

		for artifact_name, code in results.items():
			out_file = output_dir / entity.name.lower() / artifact_name
			out_file.parent.mkdir(parents=True, exist_ok=True)
			out_file.write_text(code, encoding="utf-8")
			click.echo(f"    wrote {out_file}")

	if dry_run:
		click.echo("\n(dry run — pass --output-dir to write files)")
	else:
		click.echo(f"\nGenerated to {output_dir}/")


__all__ = ["gen_pdl"]
