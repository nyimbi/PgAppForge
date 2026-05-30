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
