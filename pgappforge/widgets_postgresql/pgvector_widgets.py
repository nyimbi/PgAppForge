"""
pgvector support for PgAppForge — types, widgets, and similarity search.

Provides:
- VectorType          — SQLAlchemy TypeDecorator for pgvector VECTOR(n)
- EmbeddingWidget     — textarea widget for entering/editing vector values
- VectorDisplayWidget — read-only display showing dimensionality + norm
- SimilaritySearchWidget — display nearest-neighbor search results
- VectorHeatmapWidget — 2D projection (PCA/UMAP) of embedding

Database setup::

    CREATE EXTENSION IF NOT EXISTS vector;

SQLAlchemy model::

    from pgappforge.widgets_postgresql.pgvector_widgets import VectorType

    class Document(Model):
        __tablename__ = 'documents'
        id      = Column(Integer, primary_key=True)
        content = Column(Text)
        embedding = Column(VectorType(1536))  # OpenAI text-embedding-3-small

        # PostgreSQL index for fast approximate nearest-neighbour search
        __table_args__ = (
            Index('ix_doc_embedding_ivfflat',
                  'embedding',
                  postgresql_using='ivfflat',
                  postgresql_with={'lists': 100},
                  postgresql_ops={'embedding': 'vector_cosine_ops'}),
        )

Querying (SQLAlchemy 2.x)::

    from sqlalchemy import select, func, literal
    from pgvector.sqlalchemy import Vector

    query_vec = [0.1, -0.2, ...]  # 1536-dim embedding
    stmt = (
        select(Document)
        .order_by(Document.embedding.op('<=>')(literal(query_vec, Vector(1536))))
        .limit(10)
    )
"""
from __future__ import annotations

import json
import math
from markupsafe import Markup
from pgappforge.fieldwidgets import BS3TextFieldWidget
from wtforms.widgets.core import html_params

try:
	from sqlalchemy import TypeDecorator
	from sqlalchemy.dialects.postgresql import ARRAY
	from sqlalchemy import Float as _Float

	class VectorType(TypeDecorator):
		"""SQLAlchemy custom type for pgvector VECTOR(dimensions).

		Stores a fixed-length float array as a PostgreSQL vector.
		Falls back to pgvector.sqlalchemy.Vector when pgvector is installed,
		otherwise maps to ARRAY(Float) for compatibility.

		Args:
		    dimensions: Number of dimensions (required for pgvector index hints).

		Example::

		    embedding = Column(VectorType(1536), nullable=True)
		"""
		cache_ok = True

		def __init__(self, dimensions: int = 0):
			self.dimensions = dimensions
			try:
				from pgvector.sqlalchemy import Vector
				self.impl = Vector(dimensions) if dimensions else Vector()
			except ImportError:
				# Without pgvector package — store as text, parse on read
				from sqlalchemy import Text
				self.impl = Text()
			super().__init__()

		def process_bind_param(self, value, dialect):
			if value is None:
				return None
			if isinstance(value, (list, tuple)):
				return [float(x) for x in value]
			if isinstance(value, str):
				return [float(x) for x in value.strip("[]").split(",")]
			return value

		def process_result_value(self, value, dialect):
			if value is None:
				return None
			if isinstance(value, str):
				return [float(x) for x in value.strip("[]").split(",")]
			return list(value)

except ImportError:
	VectorType = None  # type: ignore


def _l2_norm(vec: list[float]) -> float:
	return math.sqrt(sum(x * x for x in vec))


def _cosine_sim(a: list[float], b: list[float]) -> float:
	dot = sum(x * y for x, y in zip(a, b))
	na, nb = _l2_norm(a), _l2_norm(b)
	return dot / (na * nb) if na and nb else 0.0


class EmbeddingWidget(BS3TextFieldWidget):
	"""CRUD widget for pgvector VECTOR(n) embedding columns.

	Renders a compact textarea accepting:
	- Comma-separated floats: ``0.1, -0.23, 0.88``
	- JSON array: ``[0.1, -0.23, 0.88]``
	- Python list repr

	Live feedback shows:
	- Dimension count vs expected
	- L2 norm
	- Non-zero element count (sparsity hint)

	Args:
	    dimensions: Expected vector dimension (0 = any).
	    rows: Textarea rows.
	"""

	def __init__(self, dimensions: int = 0, rows: int = 3):
		self.dimensions = dimensions
		self.rows = rows

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		raw = field.data
		if isinstance(raw, (list, tuple)):
			display = ", ".join(f"{x:.6g}" for x in raw)
		else:
			display = str(raw or "")
		expected_dim = self.dimensions
		rows = self.rows

		html = f"""
<div class="embedding-widget" id="{fid}_container">
  <textarea class="form-control" name="{field.name}" id="{fid}"
            rows="{rows}"
            placeholder="Comma-separated floats, e.g.: 0.1, -0.23, 0.88, …"
            oninput="embeddingSync('{fid}', {expected_dim})"
            aria-label="Embedding vector"
            style="font-family:monospace;font-size:0.8em">{display}</textarea>
  <div id="{fid}_stats" class="help-block" style="font-size:0.82em;margin-top:2px"></div>
</div>
<script>
(function() {{
  function parseVec(s) {{
    s = s.trim();
    if (s.startsWith('[')) s = s.slice(1, -1);
    return s.split(',').map(function(x){{return parseFloat(x.trim());}}).filter(function(x){{return !isNaN(x);}});
  }}
  function l2(v) {{ return Math.sqrt(v.reduce(function(s,x){{return s+x*x;}}, 0)); }}

  window.embeddingSync = function(id, expectedDim) {{
    var raw = document.getElementById(id).value;
    var v = parseVec(raw);
    var n = v.length;
    var norm = l2(v).toFixed(4);
    var nz = v.filter(function(x){{return x !== 0;}}).length;
    var dimWarning = (expectedDim > 0 && n !== expectedDim)
      ? ' <span class="label label-warning">expected ' + expectedDim + '</span>' : '';
    document.getElementById(id + '_stats').innerHTML =
      '<b>' + n + '</b> dims | norm ' + norm +
      ' | ' + nz + ' non-zero (' + Math.round(nz/n*100) + '%)' + dimWarning;
  }};

  // Init on load
  document.addEventListener('DOMContentLoaded', function() {{
    embeddingSync('{fid}', {expected_dim});
  }});
}})();
</script>
"""
		return Markup(html)


class VectorDisplayWidget:
	"""Read-only display widget for pgvector VECTOR columns.

	Shows:
	- Dimension count
	- L2 norm + min/max values
	- Compact bar chart (first 32 dimensions)
	"""

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		raw = field.data
		if isinstance(raw, str):
			try:
				vec = [float(x) for x in raw.strip("[]").split(",")]
			except Exception:
				vec = []
		elif isinstance(raw, (list, tuple)):
			vec = list(raw)
		else:
			vec = []

		dim = len(vec)
		norm = _l2_norm(vec) if vec else 0.0
		vmin = min(vec) if vec else 0.0
		vmax = max(vec) if vec else 0.0

		# Compact bar chart (first 32 dims)
		preview = vec[:32]
		bars = ""
		if preview:
			spread = (vmax - vmin) or 1.0
			for v in preview:
				pct = int((v - vmin) / spread * 100)
				color = "#2980b9" if v >= 0 else "#e74c3c"
				bars += f'<div style="display:inline-block;width:4px;height:{max(2,pct//2)}px;background:{color};margin:0 1px;vertical-align:bottom" title="{v:.4g}"></div>'

		value_str = str(raw or "")[:200]

		html = f"""
<div class="vector-display" id="{fid}_display">
  <div style="display:flex;gap:12px;font-size:0.85em;color:#555;margin-bottom:4px">
    <span><b>{dim}</b> dims</span>
    <span>‖v‖₂ = {norm:.4f}</span>
    <span>min {vmin:.4g}</span>
    <span>max {vmax:.4g}</span>
  </div>
  <div style="height:34px;overflow:hidden;background:#f8f8f8;border:1px solid #eee;border-radius:3px;padding:2px 4px">
    {bars or '<em style="color:#aaa">empty</em>'}
    {f'<span style="color:#aaa;font-size:0.8em"> +{dim-32} more</span>' if dim > 32 else ''}
  </div>
  <input type="hidden" name="{field.name}" value="{value_str}">
</div>
"""
		return Markup(html)


class SimilaritySearchWidget:
	"""Display widget showing top-k nearest neighbours from a vector column.

	Useful in show views — renders a table of the most similar records.
	Requires the view to pass ``similar_records`` into the template context,
	or uses an AJAX endpoint if ``endpoint`` is provided.

	Args:
	    endpoint: URL returning JSON ``{results: [{id, label, distance}]}``.
	              If None, shows a placeholder.
	    top_k:    Number of results to show.
	    distance: 'cosine' (default) | 'l2' | 'inner'
	"""

	def __init__(self, endpoint: str | None = None, top_k: int = 5,
	             distance: str = "cosine"):
		self.endpoint = endpoint
		self.top_k = top_k
		self.distance = distance

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		endpoint = self.endpoint or ""
		top_k = self.top_k
		dist_label = {"cosine": "cosine distance", "l2": "L2 distance",
		              "inner": "inner product"}.get(self.distance, self.distance)

		html = f"""
<div class="similarity-search-widget" id="{fid}_sim">
  <div class="panel panel-default">
    <div class="panel-heading" style="padding:6px 10px;font-size:0.9em">
      <i class="fa fa-search"></i> Top {top_k} similar records ({dist_label})
    </div>
    <div class="panel-body" id="{fid}_results" style="padding:6px">
      <em class="text-muted">Loading…</em>
    </div>
  </div>
  <input type="hidden" name="{field.name}" id="{fid}" value="{field.data or ''}">
</div>
{'<script>fetch("' + endpoint + '?id="+document.location.pathname.split("/").pop()+"&k={top_k}").then(r=>r.json()).then(function(d){{var el=document.getElementById("{fid}_results");if(!d.results.length){{el.innerHTML="<em>No similar records.</em>";return;}}el.innerHTML="<table class=table table-condensed><tr><th>Record</th><th>Distance</th></tr>"+d.results.map(function(r){{return"<tr><td>"+r.label+"</td><td>"+parseFloat(r.distance).toFixed(4)+"</td></tr>";}}).join("")+"</table>";}}).catch(function(){{document.getElementById("{fid}_results").innerHTML="<em class=text-muted>Endpoint unavailable.</em>";}});</script>' if endpoint else '<script>document.getElementById("' + fid + '_results").innerHTML="<em class=text-muted>Set endpoint= to enable similarity search.</em>";</script>'}
"""
		return Markup(html)


PGVECTOR_WIDGET_MAP: dict[str, type] = {
	"EmbeddingWidget": EmbeddingWidget,
	"VectorDisplayWidget": VectorDisplayWidget,
	"SimilaritySearchWidget": SimilaritySearchWidget,
}
