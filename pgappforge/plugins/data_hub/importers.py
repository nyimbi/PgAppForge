"""File format importers for the Data Hub."""
from __future__ import annotations
import csv
import io
import json
from typing import Iterator


def iter_csv(file_content: bytes, encoding: str = "utf-8-sig") -> Iterator[dict]:
	"""Yield rows from CSV content as dicts."""
	text = file_content.decode(encoding, errors="replace")
	reader = csv.DictReader(io.StringIO(text))
	yield from reader


def iter_ndjson(file_content: bytes) -> Iterator[dict]:
	"""Yield rows from NDJSON (newline-delimited JSON)."""
	for line in file_content.decode("utf-8", errors="replace").splitlines():
		line = line.strip()
		if line:
			try:
				yield json.loads(line)
			except json.JSONDecodeError:
				pass


def iter_json(file_content: bytes) -> Iterator[dict]:
	"""Yield rows from JSON array file."""
	data = json.loads(file_content.decode("utf-8", errors="replace"))
	if isinstance(data, list):
		yield from data
	elif isinstance(data, dict):
		yield data


def iter_excel(file_content: bytes) -> Iterator[dict]:
	"""Yield rows from Excel file (.xlsx/.xls)."""
	try:
		import openpyxl
		wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
		ws = wb.active
		headers = None
		for row in ws.iter_rows(values_only=True):
			if headers is None:
				headers = [str(h or "").strip() for h in row]
				continue
			yield dict(zip(headers, [str(v) if v is not None else "" for v in row]))
	except ImportError:
		raise RuntimeError("Install openpyxl to import Excel files: pip install openpyxl")


def iter_parquet(file_content: bytes) -> Iterator[dict]:
	"""Yield rows from Parquet file."""
	try:
		import pyarrow.parquet as pq
		import pyarrow as pa
		table = pq.read_table(io.BytesIO(file_content))
		for batch in table.to_batches(max_chunksize=500):
			cols = {col: batch.column(i).to_pylist()
				for i, col in enumerate(table.schema.names)}
			for i in range(batch.num_rows):
				yield {k: v[i] for k, v in cols.items()}
	except ImportError:
		raise RuntimeError("Install pyarrow to import Parquet files: pip install pyarrow")


def get_importer(file_format: str):
	return {
		"csv": iter_csv,
		"json": iter_json,
		"ndjson": iter_ndjson,
		"xlsx": iter_excel,
		"xls": iter_excel,
		"parquet": iter_parquet,
	}.get(file_format.lower())
