"""
pgappforge/pwa.py

Progressive Web App (PWA) support for PgAppForge deployments.

Critical for Africa where 40% of the workforce operates in areas with
unreliable connectivity. Provides Mendix-style one-click PWA toggle.

Usage in app factory::

    from pgappforge.pwa import setup_pwa, PWAConfig

    pwa_config = PWAConfig()
    pwa_config.enabled = app.config.get("PWA_ENABLED", False)
    pwa_config.app_name = app.config.get("APP_NAME", "PgAppForge")
    setup_pwa(app, pwa_config)

Config keys (all optional):
    PWA_ENABLED          bool   — toggle (default False)
    PWA_SHORT_NAME       str    — install icon label
    PWA_THEME_COLOR      str    — browser toolbar colour
    PWA_CACHE_STRATEGY   str    — network-first | cache-first | stale-while-revalidate
    PWA_OFFLINE_PAGES    list   — extra URLs to pre-cache
    PWA_SYNC_QUEUE       bool   — background-sync for offline form submissions
    PWA_ICON_URL         str    — path to 192×192+ PNG icon
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class PWAConfig:
	"""PWA configuration for a PgAppForge deployment."""

	enabled: bool = False
	app_name: str = "PgAppForge"
	short_name: str = "PgAF"
	theme_color: str = "#1a56db"
	background_color: str = "#ffffff"
	display: str = "standalone"
	# network-first | cache-first | stale-while-revalidate
	cache_strategy: str = "network-first"
	# Extra URLs to cache for offline access
	offline_pages: list[str]
	# Queue writes when offline, sync when online
	sync_queue: bool = True
	icon_url: str = "/static/appbuilder/img/favicon.png"

	def __init__(self) -> None:
		self.enabled = False
		self.app_name = "PgAppForge"
		self.short_name = "PgAF"
		self.theme_color = "#1a56db"
		self.background_color = "#ffffff"
		self.display = "standalone"
		self.cache_strategy = "network-first"
		self.offline_pages = []
		self.sync_queue = True
		self.icon_url = "/static/appbuilder/img/favicon.png"


def setup_pwa(app, config: PWAConfig | None = None) -> None:
	"""Set up Progressive Web App support for a Flask PgAppForge application.

	Registers:
	  1. GET /manifest.json  — Web App Manifest for installability
	  2. GET /sw.js          — Service Worker with offline caching
	  3. Injects PWA meta tags into base template via Jinja2 globals

	Args:
		app:    Flask application instance.
		config: PWAConfig instance.  If None, config is read from app.config.
	"""
	if config is None:
		config = PWAConfig()
		config.enabled = app.config.get("PWA_ENABLED", False)
		config.app_name = app.config.get("APP_NAME", "PgAppForge")
		config.short_name = app.config.get("PWA_SHORT_NAME", "PgAF")
		config.theme_color = app.config.get("PWA_THEME_COLOR", "#1a56db")
		config.background_color = app.config.get("PWA_BACKGROUND_COLOR", "#ffffff")
		config.display = app.config.get("PWA_DISPLAY", "standalone")
		config.cache_strategy = app.config.get("PWA_CACHE_STRATEGY", "network-first")
		config.offline_pages = app.config.get("PWA_OFFLINE_PAGES", [])
		config.sync_queue = app.config.get("PWA_SYNC_QUEUE", True)
		config.icon_url = app.config.get("PWA_ICON_URL", "/static/appbuilder/img/favicon.png")

	if not config.enabled:
		log.info("PWA: disabled (set PWA_ENABLED=True to enable)")
		# Still expose globals so templates don't blow up
		app.jinja_env.globals["pwa_enabled"] = False
		app.jinja_env.globals["pwa_manifest_url"] = ""
		app.jinja_env.globals["pwa_theme_color"] = config.theme_color
		return

	from flask import Response

	@app.route("/manifest.json")
	def pwa_manifest():
		"""Web App Manifest — makes the app installable on iOS/Android."""
		manifest = {
			"name": config.app_name,
			"short_name": config.short_name,
			"start_url": "/",
			"display": config.display,
			"theme_color": config.theme_color,
			"background_color": config.background_color,
			"description": f"{config.app_name} — Enterprise ERP Platform",
			"lang": "en",
			"dir": "ltr",
			"icons": [
				{
					"src": config.icon_url,
					"sizes": "192x192",
					"type": "image/png",
					"purpose": "any maskable",
				},
				{
					"src": config.icon_url,
					"sizes": "512x512",
					"type": "image/png",
					"purpose": "any maskable",
				},
			],
			"categories": ["business", "finance", "productivity"],
			"shortcuts": [
				{"name": "Dashboard", "url": "/", "description": "Main dashboard"},
				{
					"name": "Reports",
					"url": "/platform/reports/",
					"description": "Reports",
				},
			],
		}
		return Response(
			json.dumps(manifest, indent=2),
			content_type="application/manifest+json",
			headers={"Cache-Control": "public, max-age=86400"},
		)

	@app.route("/sw.js")
	def service_worker():
		"""Service Worker for offline support and background sync."""
		sw_code = _generate_service_worker(config)
		return Response(
			sw_code,
			content_type="application/javascript",
			headers={
				# SW must never be cached by the browser
				"Cache-Control": "no-store",
				"Service-Worker-Allowed": "/",
			},
		)

	# Inject PWA bootstrap into templates
	app.jinja_env.globals["pwa_enabled"] = True
	app.jinja_env.globals["pwa_manifest_url"] = "/manifest.json"
	app.jinja_env.globals["pwa_theme_color"] = config.theme_color

	log.info(
		"PWA: enabled for %s (cache strategy: %s)",
		config.app_name,
		config.cache_strategy,
	)


def _generate_service_worker(config: PWAConfig) -> str:
	"""Generate the service worker JavaScript for the configured strategy.

	Args:
		config: PWAConfig instance controlling caching behaviour.

	Returns:
		Complete service worker source as a string.
	"""
	cache_name = "pgappforge-v1"

	# Core assets to always pre-cache
	precache_urls: list[str] = [
		"/static/appbuilder/css/erp_islands.css",
		"/static/appbuilder/js/erp_islands.js",
		"/manifest.json",
		"/",
	] + config.offline_pages

	# Background sync code (optional)
	sync_code = (
		"""
// ── Background Sync — queue form submissions when offline ─────────────────
self.addEventListener('sync', event => {
	if (event.tag === 'pgaf-sync-queue') {
		event.waitUntil(_processSyncQueue());
	}
});

async function _processSyncQueue() {
	const cache = await caches.open('pgaf-sync-queue');
	const requests = await cache.keys();
	for (const req of requests) {
		try {
			const res = await fetch(req.clone());
			if (res.ok) {
				await cache.delete(req);
				console.log('[SW] Synced queued request:', req.url);
			}
		} catch (err) {
			console.warn('[SW] Sync failed, will retry:', err);
		}
	}
}
"""
		if config.sync_queue
		else ""
	)

	# Strategy-specific fetch handler body (indented 2 tabs to sit inside async IIFE)
	if config.cache_strategy == "cache-first":
		fetch_strategy = """\t\t// Cache-first: ideal for static assets — serve instantly, network as fallback
\t\tconst cached = await caches.match(event.request);
\t\tif (cached) return cached;
\t\tconst response = await fetch(event.request);
\t\t(await caches.open(CACHE_NAME)).put(event.request, response.clone());
\t\treturn response;"""
	elif config.cache_strategy == "stale-while-revalidate":
		fetch_strategy = """\t\t// Stale-while-revalidate: serve from cache immediately, refresh in background
\t\tconst cache = await caches.open(CACHE_NAME);
\t\tconst cached = await cache.match(event.request);
\t\tconst networkFetch = fetch(event.request).then(res => {
\t\t\tcache.put(event.request, res.clone());
\t\t\treturn res;
\t\t});
\t\treturn cached || networkFetch;"""
	else:
		# network-first — best default for dynamic ERP data
		fetch_strategy = """\t\t// Network-first: freshest data, graceful offline fallback
\t\ttry {
\t\t\tconst response = await fetch(event.request);
\t\t\t(await caches.open(CACHE_NAME)).put(event.request, response.clone());
\t\t\treturn response;
\t\t} catch (err) {
\t\t\tconst cached = await caches.match(event.request);
\t\t\tif (cached) return cached;
\t\t\t// Navigation requests: serve offline fallback page
\t\t\tif (event.request.mode === 'navigate') {
\t\t\t\treturn (
\t\t\t\t\t(await caches.match('/offline.html')) ||
\t\t\t\t\tnew Response('<h1>Offline</h1><p>No network. Please try again later.</p>',
\t\t\t\t\t\t{status: 503, headers: {'Content-Type': 'text/html'}})
\t\t\t\t);
\t\t\t}
\t\t\tthrow err;
\t\t}"""

	precache_json = json.dumps(precache_urls, indent=2)

	return f"""// PgAppForge Service Worker — {config.app_name}
// Generated by pgappforge.pwa — do not edit directly.
// Cache strategy: {config.cache_strategy}
'use strict';

const CACHE_NAME = '{cache_name}';
const PRECACHE_URLS = {precache_json};

// ── Install: pre-cache core assets ────────────────────────────────────────
self.addEventListener('install', event => {{
	event.waitUntil(
		caches.open(CACHE_NAME)
			.then(cache => cache.addAll(PRECACHE_URLS.filter(Boolean)))
			.then(() => self.skipWaiting())
	);
}});

// ── Activate: remove stale caches ─────────────────────────────────────────
self.addEventListener('activate', event => {{
	event.waitUntil(
		caches.keys()
			.then(keys => Promise.all(
				keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
			))
			.then(() => self.clients.claim())
	);
}});

// ── Fetch handler ─────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {{
	// Only intercept same-origin GET requests
	if (!event.request.url.startsWith(self.location.origin)) return;
	// Non-GET API calls bypass the cache (mutations must reach the server)
	if (event.request.url.includes('/api/') && event.request.method !== 'GET') return;

	event.respondWith((async () => {{
{fetch_strategy}
	}})());
}});
{sync_code}
// ── Push notifications ─────────────────────────────────────────────────────
self.addEventListener('push', event => {{
	const data = event.data?.json() || {{}};
	event.waitUntil(
		self.registration.showNotification(data.title || '{config.app_name}', {{
			body:  data.body  || '',
			icon:  '{config.icon_url}',
			badge: '{config.icon_url}',
			data:  data,
		}})
	);
}});

console.log('[SW] {config.app_name} service worker active (strategy: {config.cache_strategy})');
"""


def generate_pwa_html_snippet() -> str:
	"""Return HTML to inject into base template for PWA support.

	The snippet is safe to paste inside <head>; it relies on the
	``pwa_theme_color`` Jinja2 global that ``setup_pwa`` injects.
	"""
	return """
	<!-- PWA Support (pgappforge.pwa) -->
	<link rel="manifest" href="/manifest.json">
	<meta name="theme-color" content="{{ pwa_theme_color | default('#1a56db') }}">
	<meta name="mobile-web-app-capable" content="yes">
	<meta name="apple-mobile-web-app-capable" content="yes">
	<meta name="apple-mobile-web-app-status-bar-style" content="default">
	<meta name="apple-mobile-web-app-title" content="{{ pwa_short_name | default('PgAF') }}">
	<script>
	if ('serviceWorker' in navigator) {
		navigator.serviceWorker.register('/sw.js')
			.then(reg  => console.log('[PWA] SW registered:', reg.scope))
			.catch(err => console.warn('[PWA] SW registration failed:', err));
	}
	</script>
"""


__all__ = ["setup_pwa", "PWAConfig", "generate_pwa_html_snippet"]
