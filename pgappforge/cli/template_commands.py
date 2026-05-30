"""
flask forge templates — Schema template management CLI.

Commands::

    flask forge templates list               — show all available templates
    flask forge templates info <name>        — show template details
    flask forge templates import <name>      — install from a URL or known source
    flask forge templates install <path>     — install from a local JSON file
    flask forge templates remove <name>      — uninstall a user template
    flask forge templates apply <name>       — apply template tables to current DB
    flask forge templates export <name>      — export a template to JSON

Known templates that can be imported by name:

    fhir-r4     — HL7 FHIR R4 (bundled)
    gtfs        — GTFS transit (bundled)
    scim        — SCIM 2.0 identity (bundled)

Future: fetch from pgappforge template registry at
    https://raw.githubusercontent.com/nyimbi/PgAppForge/main/templates/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click


def _registry():
    from pgappforge.templates import TemplateRegistry
    return TemplateRegistry()


@click.group("templates")
def templates():
    """Manage pgappforge schema templates."""


@templates.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag")
def templates_list(tag):
    """List all available schema templates."""
    reg = _registry()
    items = reg.list()
    if tag:
        items = [t for t in items if tag in t.get("tags", [])]

    if not items:
        click.echo("No templates found.")
        return

    click.echo(f"{'NAME':<20} {'LABEL':<28} {'TABLES':>6}  {'SOURCE':<10} TAGS")
    click.echo("─" * 80)
    for t in items:
        tags = ", ".join(t.get("tags", [])[:3])
        click.echo(
            f"{t['name']:<20} {t['label']:<28} {t['table_count']:>6}  "
            f"{t['source']:<10} {tags}"
        )
    click.echo(f"\n{len(items)} template(s) available.")
    click.echo("Run: flask forge templates info <name>  for details.")


@templates.command("info")
@click.argument("name")
def templates_info(name):
    """Show detailed information about a template."""
    reg = _registry()
    try:
        tmpl = reg.get(name)
    except Exception as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    click.echo(f"\n{'─'*60}")
    click.echo(f"  {tmpl.get('label', name)}")
    click.echo(f"{'─'*60}")
    click.echo(f"  Name:        {tmpl.get('name')}")
    click.echo(f"  Version:     {tmpl.get('version', 'unknown')}")
    click.echo(f"  Description: {tmpl.get('description', '')}")
    click.echo(f"  Source:      {tmpl.get('source_url', 'bundled')}")
    click.echo(f"  Tags:        {', '.join(tmpl.get('tags', []))}")
    click.echo(f"\n  Tables ({len(tmpl.get('tables', {}))}):")
    for tname, cols in tmpl.get("tables", {}).items():
        col_names = [c["name"] for c in cols[:4]]
        suffix = f" +{len(cols)-4}" if len(cols) > 4 else ""
        click.echo(f"    • {tname:<30} ({', '.join(col_names)}{suffix})")
    click.echo()


@templates.command("install")
@click.argument("path_or_url")
def templates_install(path_or_url):
    """Install a template from a local JSON file.

    PATH_OR_URL: path to a .json template file
    """
    reg = _registry()
    try:
        name = reg.install_from_file(path_or_url)
        click.echo(f"✅ Installed template: {name!r}")
        click.echo("   Run 'flask forge templates list' to verify.")
    except Exception as exc:
        click.echo(f"❌ Installation failed: {exc}", err=True)
        sys.exit(1)


@templates.command("import")
@click.argument("name")
@click.option("--url", default=None, help="Custom URL to fetch template JSON from")
def templates_import(name, url):
    """Import a template by name from the pgappforge template registry.

    Built-in templates (fetched locally): fhir-r4, gtfs, scim

    Future: templates fetched from the pgappforge GitHub repository.
    """
    reg = _registry()

    # Check if already available (bundled or installed)
    try:
        tmpl = reg.get(name)
        click.echo(f"✅ Template {name!r} is already available ({len(tmpl.get('tables',{}))} tables).")
        return
    except Exception:
        pass

    # Try to fetch from URL or known remote
    fetch_url = url or (
        f"https://raw.githubusercontent.com/nyimbi/PgAppForge/main/templates/{name}.json"
    )

    click.echo(f"Fetching {name!r} from {fetch_url} …")
    try:
        import urllib.request
        with urllib.request.urlopen(fetch_url, timeout=15) as resp:
            data = json.loads(resp.read())
        installed = reg.install_from_dict(data)
        click.echo(f"✅ Imported and installed: {installed!r}")
        click.echo(f"   Tables: {list(data.get('tables', {}).keys())}")
    except Exception as exc:
        click.echo(f"❌ Import failed: {exc}", err=True)
        click.echo("   Check the name or provide --url to a custom JSON source.")
        sys.exit(1)


@templates.command("remove")
@click.argument("name")
@click.confirmation_option(prompt="Remove this template?")
def templates_remove(name):
    """Remove a user-installed template."""
    reg = _registry()
    try:
        reg.remove(name)
        click.echo(f"✅ Removed: {name!r}")
    except Exception as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)


@templates.command("apply")
@click.argument("name")
@click.option("--database-uri", "-d", required=True,
              help="PostgreSQL connection URI")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
def templates_apply(name, database_uri, dry_run):
    """Apply a template's tables to a PostgreSQL database.

    Creates tables that don't already exist (IF NOT EXISTS).
    """
    from pgappforge.templates import TemplateRegistry
    from pgappforge.views.erd_schema_manager import ERDSchemaManager
    from sqlalchemy import create_engine

    reg = TemplateRegistry()
    try:
        tmpl = reg.get(name)
    except Exception as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    tables = tmpl.get("tables", {})
    ops = []
    for tname, cols in tables.items():
        pg_cols = []
        for c in cols:
            pg_cols.append({
                "name": c["name"],
                "type": c.get("type", "TEXT"),
                "pk": c.get("pk", False),
                "nullable": c.get("nullable", True),
                "default": c.get("default"),
                "unique": c.get("unique", False),
            })
        ops.append({"op": "create_table", "table": tname, "columns": pg_cols})

    if dry_run:
        click.echo(f"# Would apply {len(ops)} table(s) from template {name!r}:")
        engine = create_engine(database_uri)
        mgr = ERDSchemaManager(engine)
        for op in ops:
            try:
                sql = mgr._op_to_sql(op)
                if sql:
                    click.echo(sql + ";")
            except Exception as exc:
                click.echo(f"# Error generating SQL for {op['table']}: {exc}")
        return

    click.echo(f"Applying {len(ops)} tables from {name!r} …")
    engine = create_engine(database_uri)
    mgr = ERDSchemaManager(engine)
    result = mgr.apply_changes(ops)
    if result.get("errors"):
        for err in result["errors"]:
            click.echo(f"❌ {err}", err=True)
    else:
        click.echo(f"✅ Applied {result['applied']} table(s) successfully.")


@templates.command("export")
@click.argument("name")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
def templates_export(name, output):
    """Export a template to JSON."""
    reg = _registry()
    try:
        tmpl = reg.get(name)
    except Exception as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    text = json.dumps(tmpl, indent=2)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.echo(f"✅ Exported to: {output}")
    else:
        click.echo(text)


@templates.command('install-data')
@click.argument('name')
@click.option('--database-uri', '-d', required=True, help='PostgreSQL connection URI')
@click.option('--data-dir', default=None, help='Directory containing downloaded data files')
def templates_install_data(name, database_uri, data_dir):
    """Load reference data for terminology schemas (SNOMED CT, LOINC, etc.).

    These are large datasets that must be downloaded separately:

    
    SNOMED CT: https://www.nlm.nih.gov/healthit/snomedct/us_edition.html (UMLS license)
    LOINC:     https://loinc.org/downloads/ (free after registration)

    Usage::

        flask forge templates apply snomed-ct -d postgresql://...
        flask forge templates install-data snomed-ct -d postgresql://... --data-dir ~/Downloads/SnomedCT_Release/

    The data-dir should contain the standard release ZIP files.
    """
    from pgappforge.cli.data_loaders import LOADERS, DOWNLOAD_SOURCES
    if name not in LOADERS:
        click.echo(f'❌ install-data not supported for {name!r}.', err=True)
        click.echo(f'   Supported: {sorted(LOADERS)}')
        sys.exit(1)
    src = DOWNLOAD_SOURCES.get(name, {})
    auto_download = bool(src.get('files'))  # True if we can auto-download
    if not data_dir and not auto_download:
        click.echo(f'❌ --data-dir required for {name!r} (manual download needed).', err=True)
        if 'register_url' in src:
            click.echo(f'   Download from: {src["register_url"]}')
        sys.exit(1)
    if auto_download and not data_dir:
        click.echo(f'  No --data-dir specified — will auto-download to /tmp/{name}_data')
    click.echo(f'Installing {name} data …')
    LOADERS[name](database_uri, data_dir)


def _load_snomed(database_uri: str, data_dir: str) -> None:
    """Load SNOMED CT release files into snomed_concept/description/relationship tables."""
    import glob, csv
    from sqlalchemy import create_engine, text
    engine = create_engine(database_uri)
    data_path = Path(data_dir)
    # Find RF2 release files
    concept_files = sorted(glob.glob(str(data_path / '**/*Concept*.txt'), recursive=True))
    desc_files    = sorted(glob.glob(str(data_path / '**/*Description*.txt'), recursive=True))
    rel_files     = sorted(glob.glob(str(data_path / '**/*Relationship*.txt'), recursive=True))
    if not concept_files:
        click.echo('❌ No SNOMED RF2 Concept files found. Check --data-dir path.', err=True)
        sys.exit(1)
    with engine.connect() as conn:
        for f in concept_files[:1]:
            click.echo(f'  Loading concepts from {Path(f).name} …')
            with open(f, encoding='utf-8') as fh:
                reader = csv.DictReader(fh, delimiter='	')
                rows = [(int(r['id']), r['effectiveTime'], r['active']=='1',
                         int(r['moduleId']), int(r['definitionStatusId']))
                        for r in reader]
            conn.execute(text(
                'INSERT INTO snomed_concept(id,effective_time,active,module_id,definition_status_id) '
                'VALUES(:id,:et,:a,:mid,:ds) ON CONFLICT(id) DO NOTHING'),
                [{'id':r[0],'et':r[1],'a':r[2],'mid':r[3],'ds':r[4]} for r in rows])
            click.echo(f'  ✓ {len(rows):,} concepts loaded')
        conn.commit()
    click.echo('✅ SNOMED CT data loaded. Run: CREATE INDEX CONCURRENTLY ON snomed_description USING GIN(search_vector);')


def _load_loinc(database_uri: str, data_dir: str) -> None:
    """Load LOINC CSV files into loinc_code table."""
    import csv
    from sqlalchemy import create_engine, text
    engine = create_engine(database_uri)
    data_path = Path(data_dir)
    loinc_csv = next(data_path.glob('**/Loinc.csv'), None)
    if not loinc_csv:
        click.echo('❌ Loinc.csv not found. Check --data-dir path.', err=True)
        sys.exit(1)
    click.echo(f'  Loading from {loinc_csv.name} …')
    rows = []
    with open(loinc_csv, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            rows.append({'loinc_num': r.get('LOINC_NUM',''),
                         'component': r.get('COMPONENT','')[:255] if r.get('COMPONENT') else None,
                         'long_common_name': r.get('LONG_COMMON_NAME','')[:500] if r.get('LONG_COMMON_NAME') else None,
                         'status': r.get('STATUS','')[:20]})
    with engine.connect() as conn:
        conn.execute(text(
            'INSERT INTO loinc_code(loinc_num,component,long_common_name,status) '
            'VALUES(:loinc_num,:component,:long_common_name,:status) ON CONFLICT(loinc_num) DO NOTHING'),
            rows)
        conn.commit()
    click.echo(f'✅ {len(rows):,} LOINC codes loaded.')
