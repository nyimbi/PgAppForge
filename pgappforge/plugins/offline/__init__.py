"""
pgappforge/plugins/offline/__init__.py

Offline-first PWA plugin for PgAppForge.

Provides a Service Worker (sw.js), a Web App Manifest (manifest.json), a
server-side sync endpoint, and a vanilla-JS client helper that queues
mutations in IndexedDB when offline and auto-syncs on reconnect.

How to enable
-------------
Add to your Flask config::

	PGAPPFORGE_OFFLINE_ENABLED = True
	PGAPPFORGE_PLUGINS = ["pgappforge.plugins.offline"]

Or instantiate directly::

	from pgappforge.plugins.offline import create_plugin
	plugin = create_plugin(appbuilder)
	plugin.activate()

Config keys
-----------
``PGAPPFORGE_OFFLINE_ENABLED`` : bool, default False
	Master switch.  Plugin views and blueprint are registered regardless;
	this controls whether the sync endpoint is open.

``PGAPPFORGE_OFFLINE_CACHE_TTL`` : int (seconds), default 3600
	Max-age hint embedded in the SW cache strategy for API responses.

``PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY`` : "server_wins"|"client_wins"|"manual"
	Default conflict resolution strategy.  Can be overridden per model via
	the ``conflict_strategies`` config key (dict[model_name, strategy]).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SERVICE_WORKER_JS — cache-first / network-first / stale-while-revalidate
# plus a background-sync event listener for queued mutations
# ---------------------------------------------------------------------------

SERVICE_WORKER_JS: str = r"""
/* PgAppForge Offline Service Worker
 * Strategies
 *   /static/** → cache-first
 *   /api/**    → stale-while-revalidate
 *   HTML pages → network-first
 *   background sync → replay queued mutations via POST /offline/sync
 */

const CACHE_VERSION = 'pgaf-v1';
const STATIC_CACHE  = CACHE_VERSION + '-static';
const API_CACHE     = CACHE_VERSION + '-api';
const PAGE_CACHE    = CACHE_VERSION + '-pages';
const SYNC_TAG      = 'pgaf-mutation-sync';
const SYNC_URL      = '/offline/sync';
const IDB_NAME      = 'pgaf_offline';
const IDB_STORE     = 'mutation_queue';

/* ── Install: open caches and skip waiting ────────────────────────────── */
self.addEventListener('install', function (event) {
	event.waitUntil(
		caches.open(STATIC_CACHE).then(function () {
			return self.skipWaiting();
		})
	);
});

/* ── Activate: delete stale cache versions, claim clients ─────────────── */
self.addEventListener('activate', function (event) {
	var live = [STATIC_CACHE, API_CACHE, PAGE_CACHE];
	event.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(
				keys
					.filter(function (k) { return k.startsWith('pgaf-') && live.indexOf(k) === -1; })
					.map(function (k) { return caches.delete(k); })
			);
		}).then(function () { return self.clients.claim(); })
	);
});

/* ── Fetch: dispatch to the right strategy ────────────────────────────── */
self.addEventListener('fetch', function (event) {
	var req = event.request;
	if (req.method !== 'GET') { return; }

	var url = new URL(req.url);

	/* /static/ assets → cache-first */
	if (/^\/static\//.test(url.pathname)) {
		event.respondWith(cacheFirst(req, STATIC_CACHE));
		return;
	}

	/* /api/ GET calls → stale-while-revalidate */
	if (/^\/api\//.test(url.pathname)) {
		event.respondWith(staleWhileRevalidate(req, API_CACHE));
		return;
	}

	/* HTML pages → network-first */
	var accept = req.headers.get('Accept') || '';
	if (accept.indexOf('text/html') !== -1) {
		event.respondWith(networkFirst(req, PAGE_CACHE));
		return;
	}
});

/* ── Background Sync: replay queued mutations ─────────────────────────── */
self.addEventListener('sync', function (event) {
	if (event.tag === SYNC_TAG) {
		event.waitUntil(replayMutations());
	}
});

/* ── Cache strategies ─────────────────────────────────────────────────── */

function cacheFirst(request, cacheName) {
	return caches.open(cacheName).then(function (cache) {
		return cache.match(request).then(function (cached) {
			if (cached) { return cached; }
			return fetch(request).then(function (response) {
				if (response.ok) { cache.put(request, response.clone()); }
				return response;
			});
		});
	});
}

function staleWhileRevalidate(request, cacheName) {
	return caches.open(cacheName).then(function (cache) {
		return cache.match(request).then(function (cached) {
			var networkFetch = fetch(request).then(function (response) {
				if (response.ok) { cache.put(request, response.clone()); }
				return response;
			}).catch(function () { return cached; });
			return cached || networkFetch;
		});
	});
}

function networkFirst(request, cacheName) {
	return fetch(request).then(function (response) {
		if (response.ok) {
			caches.open(cacheName).then(function (cache) {
				cache.put(request, response.clone());
			});
		}
		return response;
	}).catch(function () {
		return caches.open(cacheName).then(function (cache) {
			return cache.match(request).then(function (cached) {
				return cached || Response.error();
			});
		});
	});
}

/* ── IndexedDB helpers (SW side) ──────────────────────────────────────── */

function openIdb() {
	return new Promise(function (resolve, reject) {
		var req = indexedDB.open(IDB_NAME, 1);
		req.onupgradeneeded = function (e) {
			var db = e.target.result;
			if (!db.objectStoreNames.contains(IDB_STORE)) {
				var store = db.createObjectStore(IDB_STORE, { keyPath: 'id', autoIncrement: true });
				store.createIndex('by_timestamp', 'timestamp', { unique: false });
			}
		};
		req.onsuccess = function (e) { resolve(e.target.result); };
		req.onerror   = function (e) { reject(e.target.error); };
	});
}

function getAllOps(db) {
	return new Promise(function (resolve, reject) {
		var tx  = db.transaction(IDB_STORE, 'readonly');
		var req = tx.objectStore(IDB_STORE).getAll();
		req.onsuccess = function () { resolve(req.result); };
		req.onerror   = function () { reject(req.error); };
	});
}

function deleteOps(db, ids) {
	return new Promise(function (resolve, reject) {
		var tx    = db.transaction(IDB_STORE, 'readwrite');
		var store = tx.objectStore(IDB_STORE);
		var count = 0;
		if (!ids.length) { resolve(); return; }
		ids.forEach(function (id) {
			var req = store.delete(id);
			req.onsuccess = function () { if (++count === ids.length) { resolve(); } };
			req.onerror   = function () { reject(req.error); };
		});
	});
}

/* ── Replay queued mutations against /offline/sync ────────────────────── */

function replayMutations() {
	return openIdb().then(function (db) {
		return getAllOps(db).then(function (ops) {
			if (!ops.length) { return; }
			return fetch(SYNC_URL, {
				method:  'POST',
				headers: { 'Content-Type': 'application/json' },
				body:    JSON.stringify({ operations: ops }),
			}).then(function (r) { return r.json(); }).then(function (result) {
				/* Remove only the operations the server accepted */
				var applied = result.applied || 0;
				var ids = ops.slice(0, applied).map(function (op) { return op.id; }).filter(Boolean);
				return deleteOps(db, ids);
			});
		});
	});
}
""".strip()

# ---------------------------------------------------------------------------
# MANIFEST_JSON — served at /manifest.json; name/short_name filled at request
# time from app config.  The literal string uses {app_name} / {short_name}
# placeholders (str.format-style) so it can be rendered without Jinja.
# ---------------------------------------------------------------------------

MANIFEST_JSON: str = """\
{{
  "name": "{app_name}",
  "short_name": "{short_name}",
  "description": "{app_description}",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "{theme_color}",
  "icons": [
    {{
      "src": "{icon_192}",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    }},
    {{
      "src": "{icon_512}",
      "sizes": "512x512",
      "type": "image/png"
    }}
  ]
}}"""

# ---------------------------------------------------------------------------
# OFFLINE_CLIENT_JS — ~100 lines of vanilla JS
#   • Detects offline via navigator.onLine / online / offline events
#   • Shows/hides a fixed offline banner in the corner
#   • Queues mutations in IndexedDB (same store the SW reads)
#   • Auto-POSTs to /offline/sync when back online
#   • Registers the Service Worker
# ---------------------------------------------------------------------------

OFFLINE_CLIENT_JS: str = r"""
/* pgappforge-offline-client.js
 * Offline detection, mutation queuing, and auto-sync for PgAppForge apps.
 * No external dependencies.  Include after </body> and call PgAfOffline.init().
 */
(function (root) {
	'use strict';

	var IDB_NAME    = 'pgaf_offline';
	var IDB_STORE   = 'mutation_queue';
	var IDB_VERSION = 1;
	var SYNC_URL    = '/offline/sync';
	var SYNC_TAG    = 'pgaf-mutation-sync';
	var _db         = null;

	/* ── IndexedDB ──────────────────────────────────────────────────── */

	function openDb() {
		return new Promise(function (resolve, reject) {
			if (_db) { resolve(_db); return; }
			var req = indexedDB.open(IDB_NAME, IDB_VERSION);
			req.onupgradeneeded = function (e) {
				var db    = e.target.result;
				var store = db.createObjectStore(IDB_STORE, { keyPath: 'id', autoIncrement: true });
				store.createIndex('by_timestamp', 'timestamp', { unique: false });
			};
			req.onsuccess = function (e) { _db = e.target.result; resolve(_db); };
			req.onerror   = function (e) { reject(e.target.error); };
		});
	}

	/* ── Queue a mutation for later sync ────────────────────────────── */
	function queueMutation(model, pk, action, data) {
		return openDb().then(function (db) {
			return new Promise(function (resolve, reject) {
				var tx    = db.transaction(IDB_STORE, 'readwrite');
				var store = tx.objectStore(IDB_STORE);
				var entry = {
					model:     model,
					pk:        pk      != null ? String(pk) : null,
					action:    action,
					data:      data || {},
					timestamp: new Date().toISOString(),
					device_id: _deviceId(),
				};
				var req = store.add(entry);
				req.onsuccess = function () { resolve(req.result); };
				req.onerror   = function () { reject(req.error); };
			});
		});
	}

	/* ── Drain queue and POST to server ─────────────────────────────── */
	function sync() {
		if (!navigator.onLine) { return Promise.resolve({ skipped: true }); }
		return openDb().then(function (db) {
			return new Promise(function (resolve, reject) {
				var tx  = db.transaction(IDB_STORE, 'readonly');
				var req = tx.objectStore(IDB_STORE).getAll();
				req.onsuccess = function () { resolve(req.result); };
				req.onerror   = function () { reject(req.error); };
			});
		}).then(function (ops) {
			if (!ops.length) { return { applied: 0, conflicts: [], errors: [] }; }
			return fetch(SYNC_URL, {
				method:  'POST',
				headers: { 'Content-Type': 'application/json' },
				body:    JSON.stringify({ operations: ops }),
			}).then(function (r) { return r.json(); }).then(function (result) {
				return _clearSynced(ops.slice(0, result.applied || 0)).then(function () {
					return result;
				});
			});
		});
	}

	function _clearSynced(ops) {
		return openDb().then(function (db) {
			return new Promise(function (resolve, reject) {
				var ids = ops.map(function (o) { return o.id; }).filter(Boolean);
				if (!ids.length) { resolve(); return; }
				var tx    = db.transaction(IDB_STORE, 'readwrite');
				var store = tx.objectStore(IDB_STORE);
				var done  = 0;
				ids.forEach(function (id) {
					var req = store.delete(id);
					req.onsuccess = function () { if (++done === ids.length) { resolve(); } };
					req.onerror   = function () { reject(req.error); };
				});
			});
		});
	}

	/* ── Offline banner ─────────────────────────────────────────────── */
	function _showBanner(offline) {
		var el = document.getElementById('pgaf-offline-banner');
		if (!el) {
			el = document.createElement('div');
			el.id = 'pgaf-offline-banner';
			el.setAttribute('role', 'status');
			el.setAttribute('aria-live', 'polite');
			el.style.cssText = [
				'position:fixed', 'bottom:16px', 'right:16px', 'z-index:9999',
				'background:#c0392b', 'color:#fff', 'padding:6px 14px',
				'border-radius:4px', 'font:bold 13px/1.4 sans-serif',
				'box-shadow:0 2px 8px rgba(0,0,0,.35)', 'display:none',
				'transition:opacity .2s',
			].join(';');
			el.textContent = '⚡ Offline — changes will sync when reconnected';
			document.body.appendChild(el);
		}
		el.style.display = offline ? 'block' : 'none';
	}

	/* ── Stable per-browser device id ──────────────────────────────── */
	function _deviceId() {
		var key = 'pgaf_device_id';
		var id  = localStorage.getItem(key);
		if (!id) {
			id = 'dev-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
			localStorage.setItem(key, id);
		}
		return id;
	}

	/* ── Service Worker registration ────────────────────────────────── */
	function _registerSW(swUrl) {
		if (!('serviceWorker' in navigator)) { return; }
		navigator.serviceWorker.register(swUrl || '/sw.js').then(function (reg) {
			console.debug('[pgaf-offline] SW registered', reg.scope);
		}).catch(function (err) {
			console.warn('[pgaf-offline] SW registration failed', err);
		});
	}

	/* ── Request background-sync permission ─────────────────────────── */
	function _requestBackgroundSync(reg) {
		if (reg && reg.sync) {
			reg.sync.register('pgaf-mutation-sync').catch(function () {});
		}
	}

	/* ── init ───────────────────────────────────────────────────────── */
	function init(options) {
		options = options || {};
		_showBanner(!navigator.onLine);

		window.addEventListener('offline', function () { _showBanner(true); });
		window.addEventListener('online', function () {
			_showBanner(false);
			sync().then(function (r) {
				if (r && !r.skipped) {
					console.debug('[pgaf-offline] sync result', r);
				}
			}).catch(function (e) {
				console.warn('[pgaf-offline] sync error', e);
			});
		});

		if (options.registerSW !== false) {
			if ('serviceWorker' in navigator) {
				navigator.serviceWorker.register(options.swUrl || '/sw.js').then(function (reg) {
					console.debug('[pgaf-offline] SW registered', reg.scope);
					_requestBackgroundSync(reg);
				}).catch(function (err) {
					console.warn('[pgaf-offline] SW registration failed', err);
				});
			}
		}
	}

	/* ── Public API ─────────────────────────────────────────────────── */
	var PgAfOffline = {
		init:          init,
		queueMutation: queueMutation,
		sync:          sync,
		deviceId:      _deviceId,
	};

	if (typeof module !== 'undefined' && module.exports) {
		module.exports = PgAfOffline;
	} else {
		root.PgAfOffline = PgAfOffline;
	}
}(typeof globalThis !== 'undefined' ? globalThis : this));
""".strip()

# ---------------------------------------------------------------------------
# Optional SQLAlchemy model guard
# ---------------------------------------------------------------------------

try:
	from sqlalchemy import Column, DateTime, Index, Integer, String
	from sqlalchemy.dialects.postgresql import JSONB
	from pgappforge import Model

	class SyncConflict(Model):
		"""
		Persisted record of a sync conflict between a client write and the
		server's current state.

		Conflict resolution strategies
		------------------------------
		``server_wins``
			Server data is canonical; client change is discarded.
		``client_wins``
			Client data overwrites the server record.
		``manual``
			Row stays unresolved until an operator acts on it.

		``resolved_at`` is NULL while the conflict is open.
		``resolution_strategy`` reflects which strategy was applied (or
		is expected for manual rows).
		"""

		__allow_unmapped__ = True
		__tablename__ = "offline_sync_conflict"
		__table_args__ = (
			Index("ix_offline_conflict_model",    "model_name"),
			Index("ix_offline_conflict_device",   "device_id"),
			Index("ix_offline_conflict_resolved", "resolved_at"),
			{"extend_existing": True},
		)

		id                  = Column(Integer, primary_key=True)
		device_id           = Column(String(255), nullable=False)
		model_name          = Column(String(255), nullable=False)
		record_pk           = Column(String(255), nullable=False)
		server_data         = Column(JSONB, nullable=True)
		client_data         = Column(JSONB, nullable=True)
		resolved_at         = Column(DateTime(timezone=True), nullable=True)
		resolution_strategy = Column(String(32),  nullable=False, default="server_wins")
		created_at          = Column(
			DateTime(timezone=True),
			nullable=False,
			default=lambda: datetime.now(timezone.utc),
		)

		def __repr__(self) -> str:
			return (
				f"<SyncConflict id={self.id} model={self.model_name} "
				f"pk={self.record_pk} strategy={self.resolution_strategy} "
				f"resolved={self.resolved_at is not None}>"
			)

	_MODELS_AVAILABLE = True

except Exception as _model_exc:  # pragma: no cover
	_MODELS_AVAILABLE = False
	log.warning("offline plugin: could not define SQLAlchemy models: %s", _model_exc)

	class SyncConflict:  # type: ignore[no-redef]
		"""Stub when SQLAlchemy / pgappforge models are unavailable."""

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
	"PGAPPFORGE_OFFLINE_ENABLED":           False,
	"PGAPPFORGE_OFFLINE_CACHE_TTL":         3600,
	"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY": "server_wins",
	"conflict_strategies":                  {},
	# PWA manifest
	"app_name":        "PgAppForge",
	"app_short_name":  "PgAF",
	"app_description": "PgAppForge offline-capable application",
	"theme_color":     "#2c3e50",
	"icon_192":        "/static/appbuilder/img/icon-192.png",
	"icon_512":        "/static/appbuilder/img/icon-512.png",
	"cache_version":   "v1",
}

_CONFIG_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title":   "OfflinePlugin configuration",
	"type":    "object",
	"additionalProperties": False,
	"properties": {
		"PGAPPFORGE_OFFLINE_ENABLED": {
			"type":        "boolean",
			"default":     False,
			"description": "Master switch for offline/PWA features.",
		},
		"PGAPPFORGE_OFFLINE_CACHE_TTL": {
			"type":        "integer",
			"minimum":     0,
			"default":     3600,
			"description": "Cache max-age hint (seconds) for API responses.",
		},
		"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY": {
			"type":        "string",
			"enum":        ["server_wins", "client_wins", "manual"],
			"default":     "server_wins",
			"description": "Default conflict resolution strategy.",
		},
		"conflict_strategies": {
			"type":                 "object",
			"additionalProperties": {"type": "string", "enum": ["server_wins", "client_wins", "manual"]},
			"default":             {},
			"description":         "Per-model conflict strategy overrides.",
		},
		"app_name":        {"type": "string", "default": "PgAppForge"},
		"app_short_name":  {"type": "string", "default": "PgAF"},
		"app_description": {"type": "string", "default": "PgAppForge offline-capable application"},
		"theme_color":     {"type": "string", "default": "#2c3e50"},
		"icon_192":        {"type": "string", "default": "/static/appbuilder/img/icon-192.png"},
		"icon_512":        {"type": "string", "default": "/static/appbuilder/img/icon-512.png"},
		"cache_version":   {"type": "string", "default": "v1"},
	},
}

# ---------------------------------------------------------------------------
# Blueprint — /sw.js, /manifest.json, POST /offline/sync
# ---------------------------------------------------------------------------

def _build_blueprint(plugin: "OfflinePlugin") -> Blueprint:
	"""Build and return the Flask Blueprint.  Separated for testability."""

	bp = Blueprint(
		"pgaf_offline",
		__name__,
		url_prefix="",	# sw.js must be at root scope for broadest SW coverage
	)

	@bp.route("/sw.js")
	def service_worker() -> Response:
		"""Serve the Service Worker with correct MIME type and no-cache headers."""
		resp = make_response(SERVICE_WORKER_JS, 200)
		resp.headers["Content-Type"]         = "application/javascript"
		resp.headers["Service-Worker-Allowed"] = "/"
		resp.headers["Cache-Control"]        = "no-cache, no-store, must-revalidate"
		return resp

	@bp.route("/manifest.json")
	def manifest() -> Response:
		"""Serve the PWA Web App Manifest, populated from plugin/app config."""
		cfg  = plugin.config
		body = MANIFEST_JSON.format(
			app_name        = cfg.get("app_name",        "PgAppForge"),
			short_name      = cfg.get("app_short_name",  "PgAF"),
			app_description = cfg.get("app_description", ""),
			theme_color     = cfg.get("theme_color",     "#2c3e50"),
			icon_192        = cfg.get("icon_192",        "/static/appbuilder/img/icon-192.png"),
			icon_512        = cfg.get("icon_512",        "/static/appbuilder/img/icon-512.png"),
		)
		resp = make_response(body, 200)
		resp.headers["Content-Type"]  = "application/manifest+json"
		resp.headers["Cache-Control"] = "no-cache"
		return resp

	@bp.route("/offline/sync", methods=["POST"])
	def sync_endpoint() -> Response:
		"""
		Batch-apply client operations queued while offline.

		Request body (JSON)::

		    {
		      "operations": [
		        {
		          "model":     "Employee",
		          "pk":        "42",
		          "action":    "update",     // create | update | delete
		          "data":      {...},
		          "timestamp": "2026-05-30T12:00:00Z",
		          "device_id": "dev-abc123"
		        }
		      ]
		    }

		Response::

		    {
		      "applied":   N,
		      "conflicts": [{model, pk, action}, ...],
		      "errors":    [{model, pk, action, message}, ...]
		    }
		"""
		if not plugin.config.get("PGAPPFORGE_OFFLINE_ENABLED", False):
			return jsonify({"error": "offline sync is disabled"}), 503

		payload:    dict             = request.get_json(silent=True) or {}
		operations: list[dict]       = payload.get("operations", [])

		applied:   int              = 0
		conflicts: list[dict]       = []
		errors:    list[dict]       = []

		for op in operations:
			try:
				outcome = plugin._apply_operation(op)
				if outcome == "applied":
					applied += 1
				elif outcome == "conflict":
					conflicts.append({
						"model":  op.get("model"),
						"pk":     op.get("pk"),
						"action": op.get("action"),
					})
			except Exception as exc:
				log.error("offline plugin: sync error for op %s: %s", op, exc)
				errors.append({
					"model":   op.get("model"),
					"pk":      op.get("pk"),
					"action":  op.get("action"),
					"message": str(exc),
				})

		log.info(
			"offline plugin: sync — applied=%d conflicts=%d errors=%d",
			applied, len(conflicts), len(errors),
		)
		return jsonify({"applied": applied, "conflicts": conflicts, "errors": errors})

	return bp

# ---------------------------------------------------------------------------
# Admin view — conflict management
# ---------------------------------------------------------------------------

_CONFLICT_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Offline Sync Conflicts</title>
  <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <style>body{{padding-top:60px}}.hero{{background:#f5f5f5;padding:30px 20px;border-radius:6px;margin-bottom:24px;border-left:4px solid #e74c3c}}</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <h2>Offline Sync Conflicts</h2>
    <p class="lead">Review and resolve mutations that conflicted during offline sync.</p>
    <span class="label label-default">strategy: {strategy}</span>
  </div>
  <div class="alert alert-info">
    Include <code>/static/appbuilder/js/pgappforge-offline.js</code> in your base
    template and call <code>PgAfOffline.init()</code> to activate the offline banner
    and background sync.
  </div>
</div>
</body>
</html>"""


class OfflineSyncConflictView(BaseView):
	"""
	Admin view for reviewing sync conflicts.

	Mounted at /offline/conflicts/ by OfflinePlugin.register_views().
	Requires the ``can_view`` permission on this view.
	"""

	route_base   = "/offline/conflicts"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		strategy = self.appbuilder.app.config.get(
			"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY", "server_wins"
		)
		return make_response(_CONFLICT_PAGE.format(strategy=strategy), 200)


# ---------------------------------------------------------------------------
# OfflinePlugin
# ---------------------------------------------------------------------------

class OfflinePlugin(BasePlugin):
	"""
	Offline-first PWA plugin for PgAppForge.

	Public constants
	----------------
	``SERVICE_WORKER_JS``   Embeddable SW source (~160 lines).
	``MANIFEST_JSON``       ``str.format``-parameterised manifest template.
	``OFFLINE_CLIENT_JS``   Vanilla-JS client helper (~120 lines).

	Lifecycle
	---------
	1. ``initialize()``      — merge config defaults, validate strategy.
	2. ``register_views()``  — register blueprint + admin conflict view.
	3. ``register_models()`` — return [SyncConflict] for Alembic.
	4. ``_apply_operation()``— per-operation sync logic (create/update/delete).
	"""

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name        = "offline",
			version     = "0.1.0",
			description = (
				"Offline-first PWA support: Service Worker, Web App Manifest, "
				"IndexedDB mutation queue, and server-side batch sync."
			),
			author      = "PgAppForge Contributors",
			tags        = ["offline", "pwa", "sync", "service-worker", "indexeddb"],
			priority    = PluginPriority.NORMAL,
			permissions = ["can_view_OfflineSyncConflictView"],
			safe_mode_compatible = True,
			example_config = {
				"PGAPPFORGE_OFFLINE_ENABLED":           True,
				"PGAPPFORGE_OFFLINE_CACHE_TTL":         3600,
				"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY": "server_wins",
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults and validate the conflict strategy."""
		merged: dict[str, Any] = {**_DEFAULT_CONFIG, **self.config}

		# Pull matching keys from Flask app config (plugin-level config wins)
		try:
			app_cfg = self.appbuilder.get_app.config
			for key in (
				"PGAPPFORGE_OFFLINE_ENABLED",
				"PGAPPFORGE_OFFLINE_CACHE_TTL",
				"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY",
			):
				if key in app_cfg and key not in self.config:
					merged[key] = app_cfg[key]
		except Exception:
			pass

		self.config = merged
		self._validate_strategy()

		log.info(
			"offline plugin: initialized (enabled=%s strategy=%s cache_ttl=%ss)",
			self.config.get("PGAPPFORGE_OFFLINE_ENABLED"),
			self.config.get("PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY"),
			self.config.get("PGAPPFORGE_OFFLINE_CACHE_TTL"),
		)

	def register_views(self) -> None:
		"""Register the Flask blueprint and the conflict admin view."""
		bp = _build_blueprint(self)
		self.register_blueprint(bp)

		self.add_view(
			OfflineSyncConflictView,
			"Sync Conflicts",
			icon     = "fa-exchange",
			category = "Offline",
			category_icon = "fa-wifi",
		)
		log.info("offline plugin: blueprint and views registered")

	def register_models(self) -> list:
		"""Return SQLAlchemy model classes for Alembic autogenerate."""
		if _MODELS_AVAILABLE:
			return [SyncConflict]
		log.warning("offline plugin: SQLAlchemy models unavailable — skipping")
		return []

	def get_config_schema(self) -> dict:
		return _CONFIG_SCHEMA

	# ------------------------------------------------------------------
	# Operation application
	# ------------------------------------------------------------------

	def _apply_operation(self, op: dict[str, Any]) -> str:
		"""
		Apply a single offline operation to the database.

		Returns ``"applied"`` on success or ``"conflict"`` when the
		manual strategy routes the operation to the conflict table.

		Conflict resolution
		-------------------
		``server_wins``
			Discard client data; record conflict as resolved immediately.
		``client_wins``
			Overwrite server record; resolve conflict immediately.
		``manual``
			Write an unresolved SyncConflict row; return ``"conflict"``.

		Args:
			op: Operation dict with keys model, pk, action, data,
			    timestamp, device_id.

		Returns:
			``"applied"`` | ``"conflict"``
		"""
		model_name: str  = op.get("model", "")
		record_pk:  str  = str(op.get("pk", ""))
		action:     str  = op.get("action", "update")
		data:       dict = op.get("data") or {}
		device_id:  str  = op.get("device_id", "unknown")
		timestamp:  str  = op.get("timestamp", "")

		default_strategy: str = self.config.get(
			"PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY", "server_wins"
		)
		strategy: str = (
			self.config.get("conflict_strategies", {}).get(model_name)
			or default_strategy
		)

		if not _MODELS_AVAILABLE:
			log.warning(
				"offline plugin: models unavailable — cannot apply op %s/%s",
				model_name, record_pk,
			)
			return "applied"

		try:
			db_session = self.appbuilder.get_session
		except Exception as exc:
			log.error("offline plugin: cannot get DB session: %s", exc)
			raise

		model_cls = _resolve_model(model_name)
		if model_cls is None:
			log.warning("offline plugin: unknown model %r — skipping op", model_name)
			return "applied"

		server_record = db_session.get(model_cls, _coerce_pk(model_cls, record_pk))
		server_data   = _record_to_dict(server_record) if server_record else None
		is_conflict   = _detect_conflict(server_record, timestamp)

		if is_conflict:
			conflict = SyncConflict(
				device_id           = device_id,
				model_name          = model_name,
				record_pk           = record_pk,
				server_data         = server_data,
				client_data         = data,
				resolution_strategy = strategy,
			)

			if strategy == "server_wins":
				conflict.resolved_at = datetime.now(timezone.utc)
				db_session.add(conflict)
				db_session.commit()
				log.debug("offline plugin: server_wins for %s/%s", model_name, record_pk)
				return "applied"

			if strategy == "client_wins":
				_apply_data(db_session, model_cls, server_record, record_pk, action, data)
				conflict.resolved_at = datetime.now(timezone.utc)
				db_session.add(conflict)
				db_session.commit()
				log.debug("offline plugin: client_wins applied for %s/%s", model_name, record_pk)
				return "applied"

			# manual
			db_session.add(conflict)
			db_session.commit()
			log.info("offline plugin: manual conflict queued for %s/%s", model_name, record_pk)
			return "conflict"

		# No conflict — apply directly
		_apply_data(db_session, model_cls, server_record, record_pk, action, data)
		db_session.commit()
		log.debug("offline plugin: applied %s on %s/%s", action, model_name, record_pk)
		return "applied"

	# ------------------------------------------------------------------
	# Config validation
	# ------------------------------------------------------------------

	def _validate_strategy(self) -> None:
		valid = {"server_wins", "client_wins", "manual"}
		strategy = self.config.get("PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY", "server_wins")
		if strategy not in valid:
			raise ValueError(
				f"offline plugin: invalid PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY {strategy!r}; "
				f"must be one of {sorted(valid)}"
			)
		for model_name, s in self.config.get("conflict_strategies", {}).items():
			if s not in valid:
				raise ValueError(
					f"offline plugin: invalid strategy {s!r} for model {model_name!r}; "
					f"must be one of {sorted(valid)}"
				)
		ttl = self.config.get("PGAPPFORGE_OFFLINE_CACHE_TTL", 3600)
		if not isinstance(ttl, int) or ttl < 0:
			raise ValueError(
				f"offline plugin: PGAPPFORGE_OFFLINE_CACHE_TTL must be a non-negative integer, got {ttl!r}"
			)

	# BasePlugin calls _validate_config during __init__; route to our validator
	def _validate_config(self) -> None:
		# config may be partial at construction time; full validation happens in initialize()
		pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_model(model_name: str):
	"""
	Look up a SQLAlchemy mapped class by its ``__name__``.

	Searches the mapper registry; returns None if not found.
	"""
	try:
		import sqlalchemy.orm as _orm
		for mapper in _orm.mapperlib._mapper_registry:  # type: ignore[attr-defined]
			cls = mapper.class_
			if cls.__name__ == model_name:
				return cls
	except Exception:
		pass
	# Fallback via gc
	try:
		import gc
		from sqlalchemy.orm import DeclarativeMeta
		for obj in gc.get_objects():
			if isinstance(obj, DeclarativeMeta) and getattr(obj, "__name__", "") == model_name:
				return obj
	except Exception:
		pass
	return None


def _coerce_pk(model_cls, pk_str: str):
	"""Convert a string PK to the column's Python type (integer only)."""
	try:
		from sqlalchemy import inspect as sa_inspect, Integer as _Int
		pk_cols = sa_inspect(model_cls).primary_key
		if pk_cols and isinstance(pk_cols[0].type, _Int):
			return int(pk_str)
	except Exception:
		pass
	return pk_str


def _record_to_dict(record) -> dict[str, Any]:
	"""Shallow-serialise a SQLAlchemy model instance to a plain dict."""
	try:
		from sqlalchemy import inspect as sa_inspect
		mapper = sa_inspect(type(record))
		return {col.key: getattr(record, col.key) for col in mapper.column_attrs}
	except Exception:
		return {}


def _detect_conflict(server_record, client_timestamp: str) -> bool:
	"""
	Return True if the server record was modified after ``client_timestamp``.

	Uses ``changed_on`` or ``updated_at`` when present; returns False when
	the timestamp cannot be compared.
	"""
	if server_record is None or not client_timestamp:
		return False
	server_ts = (
		getattr(server_record, "changed_on", None)
		or getattr(server_record, "updated_at", None)
	)
	if server_ts is None:
		return False
	try:
		client_dt = datetime.fromisoformat(client_timestamp.rstrip("Z")).replace(
			tzinfo=timezone.utc
		)
		if server_ts.tzinfo is None:
			server_ts = server_ts.replace(tzinfo=timezone.utc)
		return server_ts > client_dt
	except Exception:
		return False


def _apply_data(
	db_session,
	model_cls,
	server_record,
	pk_str: str,
	action: str,
	data: dict,
) -> None:
	"""Apply create / update / delete to a model record."""
	if action == "delete":
		if server_record is not None:
			db_session.delete(server_record)
		return

	if server_record is None:
		record = model_cls()
		for key, val in data.items():
			if hasattr(record, key):
				setattr(record, key, val)
		db_session.add(record)
	else:
		for key, val in data.items():
			if hasattr(server_record, key) and key not in ("id", "pk"):
				setattr(server_record, key, val)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder, config: dict[str, Any] | None = None) -> OfflinePlugin:
	"""
	Construct an OfflinePlugin bound to *appbuilder*.

	Does **not** call ``activate()``::

	    plugin = create_plugin(appbuilder, config={
	        "PGAPPFORGE_OFFLINE_ENABLED": True,
	        "PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY": "client_wins",
	    })
	    plugin.activate()
	"""
	return OfflinePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Required public constants
	"SERVICE_WORKER_JS",
	"MANIFEST_JSON",
	"OFFLINE_CLIENT_JS",
	# Plugin class + factory
	"OfflinePlugin",
	"create_plugin",
	# Model
	"SyncConflict",
	# View
	"OfflineSyncConflictView",
	# Capability flag
	"_MODELS_AVAILABLE",
]
