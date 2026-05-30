"""
Data loaders for large reference datasets.

These loaders support automatic downloading from public sources where
no license is required, and provide clear instructions for licensed
datasets (SNOMED CT, LOINC).

Usage::

    flask forge templates install-data geonames -d postgresql://...
    flask forge templates install-data loinc -d postgresql://... --data-dir ~/Downloads/
    flask forge templates install-data snomed-ct -d postgresql://... --data-dir ~/Downloads/

Download URLs:
    GeoNames:   https://download.geonames.org/export/dump/ (CC-BY 4.0, no registration)
    LOINC:      https://loinc.org/downloads/ (free after registration)
    SNOMED CT:  https://www.nlm.nih.gov/healthit/snomedct/ (UMLS license required)
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from typing import Any

import click

# ─── Known download sources ────────────────────────────────────────────────────

DOWNLOAD_SOURCES: dict[str, dict] = {
	"geonames": {
		"license": "CC-BY 4.0 — free, no registration required",
		"files": {
			"allCountries.zip":         "https://download.geonames.org/export/dump/allCountries.zip",
			"alternateNamesV2.zip":     "https://download.geonames.org/export/dump/alternateNamesV2.zip",
			"countryInfo.txt":          "https://download.geonames.org/export/dump/countryInfo.txt",
			"admin1CodesASCII.txt":     "https://download.geonames.org/export/dump/admin1CodesASCII.txt",
			"admin2Codes.txt":          "https://download.geonames.org/export/dump/admin2Codes.txt",
			"featureCodes_en.txt":      "https://download.geonames.org/export/dump/featureCodes_en.txt",
			"timeZones.txt":            "https://download.geonames.org/export/dump/timeZones.txt",
			"allCountriesPostal.zip":   "https://download.geonames.org/export/dump/allCountries.zip",
		},
	},
	"loinc": {
		"license": "Free after registration",
		"register_url": "https://loinc.org/downloads/",
		"files": {},  # manual download required
	},
	"snomed-ct": {
		"license": "UMLS license (US) or national license",
		"register_url": "https://www.nlm.nih.gov/healthit/snomedct/us_edition.html",
		"files": {},  # manual download required
	},
}


def _download(url: str, dest: Path) -> None:
	"""Download a file with progress reporting."""
	import urllib.request
	dest.parent.mkdir(parents=True, exist_ok=True)
	click.echo(f"  ↓ {Path(url).name} → {dest.name}")
	req = urllib.request.Request(url, headers={"User-Agent": "pgappforge/0.90.0"})
	with urllib.request.urlopen(req, timeout=120) as resp:
		total = int(resp.headers.get("Content-Length", 0))
		done = 0
		with open(dest, "wb") as f:
			while True:
				chunk = resp.read(65536)
				if not chunk:
					break
				f.write(chunk)
				done += len(chunk)
				if total:
					pct = done * 100 // total
					print(f"    {pct}%  ({done // 1024 // 1024}MB / {total // 1024 // 1024}MB)\r",
					      end="", flush=True)
	print()
	click.echo(f"  ✓ {dest.name} ({done // 1024 // 1024}MB)")


def _unzip(src: Path, dest_dir: Path) -> list[Path]:
	"""Extract a zip archive and return list of extracted file paths."""
	click.echo(f"  Extracting {src.name} …")
	with zipfile.ZipFile(src) as zf:
		zf.extractall(dest_dir)
		return [dest_dir / name for name in zf.namelist()]


def _ensure_file(name: str, url: str, data_dir: Path) -> Path | None:
	"""Return path to file, downloading if needed."""
	dest = data_dir / name
	if not dest.exists():
		try:
			_download(url, dest)
		except Exception as exc:
			click.echo(f"  ⚠  Could not download {name}: {exc}", err=True)
			return None
	return dest


def load_geonames(database_uri: str, data_dir: str | None = None) -> None:
	"""Download and load GeoNames geographic database (CC-BY 4.0, free).

	Downloads ~1.5GB of data from geonames.org and loads into:
	  geonames_feature, geonames_country, geonames_admin1/2,
	  geonames_feature_code, geonames_timezone, geonames_postal_code
	"""
	from sqlalchemy import create_engine, text as sa_text
	engine = create_engine(database_uri)
	dp = Path(data_dir) if data_dir else Path("/tmp/geonames_cache")
	dp.mkdir(parents=True, exist_ok=True)

	src = DOWNLOAD_SOURCES["geonames"]
	click.echo(f"License: {src['license']}")

	with engine.connect() as conn:
		# ── Country info ──────────────────────────────────────────────────────
		f = _ensure_file("countryInfo.txt", src["files"]["countryInfo.txt"], dp)
		if f:
			rows, skipped = [], 0
			with open(f, encoding="utf-8") as fh:
				for line in fh:
					if line.startswith("#") or not line.strip():
						continue
					p = line.strip().split("\t")
					if len(p) < 17:
						skipped += 1
						continue
					rows.append({"a2": p[0], "a3": p[1], "an": p[2], "fips": p[3],
					             "name": p[4], "cap": p[5],
					             "area": float(p[6]) if p[6] else None,
					             "pop": int(p[7]) if p[7] else None,
					             "cont": p[8], "tld": p[9], "curr": p[10], "cname": p[11],
					             "phone": p[12], "fmt": p[13],
					             "langs": p[15], "gnid": int(p[16]) if p[16].strip() else None,
					             "neigh": p[17] if len(p) > 17 else ""})
			if rows:
				conn.execute(sa_text(
					"INSERT INTO geonames_country(iso_alpha2,iso_alpha3,iso_numeric,fips_code,"
					"country_name,capital,area_km2,population,continent,tld,currency_code,"
					"currency_name,phone_prefix,postal_code_format,languages,geonameid,neighbours)"
					"VALUES(:a2,:a3,:an,:fips,:name,:cap,:area,:pop,:cont,:tld,:curr,:cname,"
					":phone,:fmt,:langs,:gnid,:neigh) ON CONFLICT(iso_alpha2) DO NOTHING"), rows)
				conn.commit()
				click.echo(f"  ✓ {len(rows)} countries loaded")

		# ── Feature codes ─────────────────────────────────────────────────────
		f = _ensure_file("featureCodes_en.txt", src["files"]["featureCodes_en.txt"], dp)
		if f:
			rows = []
			with open(f, encoding="utf-8") as fh:
				for line in fh:
					p = line.strip().split("\t")
					if len(p) < 2 or p[0] == "null":
						continue
					fc = p[0]
					rows.append({"code": fc, "cls": fc[:1], "fco": fc[1:] if len(fc) > 1 else "",
					             "name": p[1], "desc": p[2] if len(p) > 2 else ""})
			if rows:
				conn.execute(sa_text(
					"INSERT INTO geonames_feature_code(code,feature_class,feature_code,name,description)"
					"VALUES(:code,:cls,:fco,:name,:desc) ON CONFLICT(code) DO NOTHING"), rows)
				conn.commit()
				click.echo(f"  ✓ {len(rows)} feature codes loaded")

		# ── Admin1 ────────────────────────────────────────────────────────────
		f = _ensure_file("admin1CodesASCII.txt", src["files"]["admin1CodesASCII.txt"], dp)
		if f:
			rows = []
			with open(f, encoding="utf-8") as fh:
				for line in fh:
					p = line.strip().split("\t")
					if len(p) < 4:
						continue
					rows.append({"code": p[0], "name": p[1], "asc": p[2],
					             "gnid": int(p[3]) if p[3] else None})
			if rows:
				conn.execute(sa_text(
					"INSERT INTO geonames_admin1(code,name,asciiname,geonameid)"
					"VALUES(:code,:name,:asc,:gnid) ON CONFLICT(code) DO NOTHING"), rows)
				conn.commit()
				click.echo(f"  ✓ {len(rows)} admin1 divisions loaded")

		# ── Main features (large — streamed in batches) ────────────────────────
		zip_f = _ensure_file("allCountries.zip", src["files"]["allCountries.zip"], dp)
		if zip_f:
			txt = dp / "allCountries.txt"
			if not txt.exists():
				_unzip(zip_f, dp)
			if txt.exists():
				click.echo("  Loading geographic features (this takes several minutes for full dataset) …")
				batch, total = [], 0
				with open(txt, encoding="utf-8") as fh:
					for line in fh:
						p = line.strip().split("\t")
						if len(p) < 19:
							continue
						batch.append({
							"gid": int(p[0]),  "nm": p[1][:200], "asc": p[2][:200],
							"lat": float(p[4]) if p[4] else None,
							"lng": float(p[5]) if p[5] else None,
							"fc": p[6][:1], "fco": p[7][:10], "cc": p[8][:2],
							"a1": p[10][:20], "a2": p[11][:80],
							"pop": int(p[14]) if p[14] else None,
							"elev": int(p[15]) if p[15] else None,
							"tz": p[17][:40], "mod": p[18][:10],
						})
						if len(batch) >= 5000:
							conn.execute(sa_text(
								"INSERT INTO geonames_feature(geonameid,name,asciiname,latitude,longitude,"
								"feature_class,feature_code,country_code,admin1_code,admin2_code,"
								"population,elevation,timezone,modification_date)"
								"VALUES(:gid,:nm,:asc,:lat,:lng,:fc,:fco,:cc,:a1,:a2,"
								":pop,:elev,:tz,:mod) ON CONFLICT(geonameid) DO NOTHING"), batch)
							total += len(batch)
							batch = []
							print(f"    {total:,} features\r", end="", flush=True)
				if batch:
					conn.execute(sa_text(
						"INSERT INTO geonames_feature(geonameid,name,asciiname,latitude,longitude,"
						"feature_class,feature_code,country_code,admin1_code,admin2_code,"
						"population,elevation,timezone,modification_date)"
						"VALUES(:gid,:nm,:asc,:lat,:lng,:fc,:fco,:cc,:a1,:a2,"
						":pop,:elev,:tz,:mod) ON CONFLICT(geonameid) DO NOTHING"), batch)
					total += len(batch)
				print()
				conn.commit()
				click.echo(f"  ✓ {total:,} features loaded")

				# Build PostGIS geometry column
				click.echo("  Building PostGIS point geometry …")
				conn.execute(sa_text(
					"UPDATE geonames_feature "
					"SET geo_point = ST_SetSRID(ST_MakePoint(longitude,latitude),4326)::geography "
					"WHERE latitude IS NOT NULL AND geo_point IS NULL"))
				conn.commit()
				click.echo("  ✓ PostGIS points built")

	click.echo("\n✅ GeoNames data loaded.")
	click.echo("Recommended indexes:")
	click.echo("  CREATE INDEX CONCURRENTLY ON geonames_feature USING GIST(geo_point);")
	click.echo("  CREATE INDEX CONCURRENTLY ON geonames_feature(country_code, feature_class);")
	click.echo("  CREATE INDEX CONCURRENTLY ON geonames_feature USING GIN(to_tsvector('simple',name));")


def load_loinc(database_uri: str, data_dir: str) -> None:
	"""Load LOINC codes. Requires free registration at loinc.org."""
	import csv
	from sqlalchemy import create_engine, text as sa_text
	engine = create_engine(database_uri)
	src = DOWNLOAD_SOURCES["loinc"]
	click.echo(f"  License: {src['license']}")
	click.echo(f"  Download from: {src['register_url']}")
	data_path = Path(data_dir)
	loinc_csv = next(data_path.glob("**/Loinc.csv"), None)
	if not loinc_csv:
		click.echo("❌ Loinc.csv not found. Download from loinc.org and extract here.", err=True)
		sys.exit(1)
	click.echo(f"  Loading from {loinc_csv.name} …")
	rows = []
	with open(loinc_csv, encoding="utf-8") as fh:
		for r in csv.DictReader(fh):
			rows.append({
				"loinc_num": r.get("LOINC_NUM", ""),
				"component": (r.get("COMPONENT") or "")[:255] or None,
				"long_common_name": (r.get("LONG_COMMON_NAME") or "")[:500] or None,
				"status": (r.get("STATUS") or "")[:20],
			})
	with engine.connect() as conn:
		conn.execute(sa_text(
			"INSERT INTO loinc_code(loinc_num,component,long_common_name,status) "
			"VALUES(:loinc_num,:component,:long_common_name,:status) "
			"ON CONFLICT(loinc_num) DO NOTHING"), rows)
		conn.commit()
	click.echo(f"✅ {len(rows):,} LOINC codes loaded.")


def load_snomed(database_uri: str, data_dir: str) -> None:
	"""Load SNOMED CT RF2 files. Requires UMLS/NLM license."""
	import csv, glob
	from sqlalchemy import create_engine, text as sa_text
	engine = create_engine(database_uri)
	src = DOWNLOAD_SOURCES["snomed-ct"]
	click.echo(f"  License: {src['license']}")
	click.echo(f"  Download from: {src['register_url']}")
	data_path = Path(data_dir)
	concept_files = sorted(glob.glob(str(data_path / "**/*Concept*.txt"), recursive=True))
	if not concept_files:
		click.echo(f"❌ No SNOMED RF2 Concept files found in {data_dir}", err=True)
		sys.exit(1)
	with engine.connect() as conn:
		for cf in concept_files[:1]:
			click.echo(f"  Loading concepts from {Path(cf).name} …")
			with open(cf, encoding="utf-8") as fh:
				rows = [{"id": int(r["id"]), "et": r["effectiveTime"], "a": r["active"] == "1",
				         "mid": int(r["moduleId"]), "ds": int(r["definitionStatusId"])}
				        for r in csv.DictReader(fh, delimiter="\t")]
			conn.execute(sa_text(
				"INSERT INTO snomed_concept(id,effective_time,active,module_id,definition_status_id) "
				"VALUES(:id,:et,:a,:mid,:ds) ON CONFLICT(id) DO NOTHING"), rows)
			conn.commit()
			click.echo(f"  ✓ {len(rows):,} concepts loaded")
	click.echo("✅ SNOMED CT loaded.")


# Registry of all supported data-load targets
LOADERS: dict[str, Any] = {
	"geonames": load_geonames,
	"loinc": load_loinc,
	"snomed-ct": load_snomed,
}
