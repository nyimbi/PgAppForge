"""
Canonical CDN script/link tags for map and visualization libraries.

All widget files import from here so version bumps happen in one place.
The ONCE variants use a guard variable to prevent duplicate loads when
multiple widgets appear on the same page.
"""
from __future__ import annotations

LEAFLET_VERSION = "1.9.4"

LEAFLET_CDN = f"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV/XN/WLEg=" crossorigin=""></script>
"""

# Load Leaflet.Draw on top of Leaflet
LEAFLET_DRAW_CDN = f"""
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" crossorigin="">
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js" crossorigin=""></script>
"""

H3_CDN = """
<script>
if (typeof h3 === 'undefined') {
  var _h3s = document.createElement('script');
  _h3s.src = 'https://unpkg.com/h3-js@4/dist/h3-js.umd.js';
  _h3s.onload = function() { document.dispatchEvent(new Event('h3loaded')); };
  document.head.appendChild(_h3s);
}
</script>
"""

EASYMDE_CDN = """
<link rel="stylesheet" href="https://unpkg.com/easymde@2/dist/easymde.min.css" crossorigin="">
<script src="https://unpkg.com/easymde@2/dist/easymde.min.js" crossorigin=""></script>
"""

MARKED_CDN = """
<script src="https://unpkg.com/marked@9/marked.min.js" crossorigin=""></script>
"""

DOMPURIFY_CDN = """
<script src="https://unpkg.com/dompurify@3/dist/purify.min.js" crossorigin=""></script>
"""

CYTOSCAPE_VERSION = "3.27.0"

CYTOSCAPE_CDN = f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/{CYTOSCAPE_VERSION}/cytoscape.min.js" crossorigin=""></script>
"""

# Cytoscape.js extension CDNs — used by the ERD Designer
# fcose: O(n log n) force-directed layout — replaces cose for >30 nodes
CYTOSCAPE_FCOSE_CDN = """
<script src="https://cdn.jsdelivr.net/npm/layout-base@2.0.1/layout-base.js" crossorigin=""></script>
<script src="https://cdn.jsdelivr.net/npm/cose-base@2.2.0/cose-base.js" crossorigin=""></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-fcose@2.2.0/cytoscape-fcose.js" crossorigin=""></script>
"""
# Dagre: hierarchical layout for deep tree schemas
CYTOSCAPE_DAGRE_CDN = """
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js" crossorigin=""></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js" crossorigin=""></script>
"""
# Edge handles: drag-from-node to create edges visually
CYTOSCAPE_EDGEHANDLES_CDN = """
<script src="https://cdn.jsdelivr.net/npm/cytoscape-edgehandles@4.0.1/cytoscape-edgehandles.js" crossorigin=""></script>
"""
# Navigator: minimap overview in corner
CYTOSCAPE_NAVIGATOR_CDN = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/cytoscape-navigator@2.0.1/cytoscape.js-navigator.css">
<script src="https://cdn.jsdelivr.net/npm/cytoscape-navigator@2.0.1/cytoscape.js-navigator.js" crossorigin=""></script>
"""

JSBARCODE_VERSION = "3.11.6"
JSBARCODE_CDN_URL = f"https://cdn.jsdelivr.net/npm/jsbarcode@{JSBARCODE_VERSION}/dist/JsBarcode.all.min.js"

QRCODE_VERSION = "1.5.3"
JSQR_VERSION = "1.4.0"
QRCODE_CDN_URL = f"https://cdnjs.cloudflare.com/ajax/libs/qrcode/{QRCODE_VERSION}/qrcode.min.js"
JSQR_CDN_URL = f"https://cdnjs.cloudflare.com/ajax/libs/jsqr/{JSQR_VERSION}/jsQR.min.js"
