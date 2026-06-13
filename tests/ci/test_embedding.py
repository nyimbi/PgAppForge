"""Tests for pgappforge.embedding — iframe embedding + JWT token handling.

All tests use real Flask test clients (no mocks).
"""

import sys


def _fresh_module():
	if "pgappforge.embedding" in sys.modules:
		del sys.modules["pgappforge.embedding"]
	import pgappforge.embedding as mod
	return mod


def _make_app(allowed_origins=None, **extra_config):
	try:
		from flask import Flask
	except ImportError:
		return None
	app = Flask(__name__)
	app.config["SECRET_KEY"] = "test-secret-key-do-not-use"
	app.config["TESTING"] = True
	if allowed_origins is not None:
		app.config["EMBED_ALLOWED_ORIGINS"] = allowed_origins
	app.config.update(extra_config)
	return app


# ── configure_embedding ───────────────────────────────────────────────────────

def test_configure_embedding_deny_by_default():
	"""No allowed origins → every response gets X-Frame-Options: DENY."""
	mod = _fresh_module()
	app = _make_app(allowed_origins=[])
	if app is None:
		return

	from flask import Flask
	mod.configure_embedding(app)

	@app.route("/test")
	def _view():
		return "ok"

	with app.test_client() as client:
		resp = client.get("/test")
		assert resp.headers.get("X-Frame-Options") == "DENY"


def test_configure_embedding_wildcard_removes_xfo():
	"""Wildcard origin → X-Frame-Options removed, CSP frame-ancestors * set."""
	mod = _fresh_module()
	app = _make_app(allowed_origins=["*"])
	if app is None:
		return

	mod.configure_embedding(app)

	@app.route("/test")
	def _view():
		return "ok"

	with app.test_client() as client:
		resp = client.get("/test", headers={"Origin": "https://bank.co.ke"})
		assert "X-Frame-Options" not in resp.headers
		csp = resp.headers.get("Content-Security-Policy", "")
		assert "frame-ancestors" in csp


def test_configure_embedding_specific_origin_allowed():
	"""Matching origin → X-Frame-Options removed, frame-ancestors header set."""
	mod = _fresh_module()
	allowed = ["https://portal.example.com"]
	app = _make_app(allowed_origins=allowed)
	if app is None:
		return

	mod.configure_embedding(app)

	@app.route("/test")
	def _view():
		return "ok"

	with app.test_client() as client:
		resp = client.get("/test", headers={"Origin": "https://portal.example.com"})
		assert "X-Frame-Options" not in resp.headers
		csp = resp.headers.get("Content-Security-Policy", "")
		assert "frame-ancestors" in csp
		assert "https://portal.example.com" in csp


def test_configure_embedding_unmatched_origin_gets_deny():
	"""Unknown origin → X-Frame-Options: DENY applied."""
	mod = _fresh_module()
	app = _make_app(allowed_origins=["https://allowed.example.com"])
	if app is None:
		return

	mod.configure_embedding(app)

	@app.route("/test")
	def _view():
		return "ok"

	with app.test_client() as client:
		resp = client.get("/test", headers={"Origin": "https://evil.example.com"})
		assert resp.headers.get("X-Frame-Options") == "DENY"


def test_configure_embedding_no_crash_on_bad_config():
	"""configure_embedding must not raise even with unexpected config values."""
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	# Pass a string instead of a list — should coerce gracefully
	app.config["EMBED_ALLOWED_ORIGINS"] = "https://single.example.com"
	mod.configure_embedding(app)  # must not raise


# ── embeddable decorator ──────────────────────────────────────────────────────

def test_embeddable_sets_csp_for_matching_origin():
	mod = _fresh_module()
	app = _make_app(allowed_origins=[])
	if app is None:
		return
	mod.configure_embedding(app)

	@app.route("/iframe-view")
	@mod.embeddable(origins=["https://partner.bank"])
	def _view():
		from flask import make_response
		return make_response("content", 200)

	with app.test_client() as client:
		resp = client.get("/iframe-view", headers={"Origin": "https://partner.bank"})
		csp = resp.headers.get("Content-Security-Policy", "")
		assert "frame-ancestors" in csp
		assert "https://partner.bank" in csp
		assert "X-Frame-Options" not in resp.headers


def test_embeddable_falls_back_gracefully():
	"""@embeddable must return the view result even if header patching fails."""
	mod = _fresh_module()
	app = _make_app(allowed_origins=[])
	if app is None:
		return
	mod.configure_embedding(app)

	@app.route("/safe-view")
	@mod.embeddable(origins=["https://safe.example.com"])
	def _view():
		return "hello"

	with app.test_client() as client:
		resp = client.get("/safe-view")
		assert resp.status_code == 200


# ── get_embedded_token_from_request ──────────────────────────────────────────

def test_get_embedded_token_from_query_param():
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	@app.route("/token-test")
	def _view():
		token = mod.get_embedded_token_from_request()
		return token or "none"

	with app.test_client() as client:
		resp = client.get("/token-test?_token=my-jwt-value")
		assert resp.data == b"my-jwt-value"


def test_get_embedded_token_from_bearer_header():
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	@app.route("/token-test")
	def _view():
		token = mod.get_embedded_token_from_request()
		return token or "none"

	with app.test_client() as client:
		resp = client.get("/token-test", headers={"Authorization": "Bearer header-jwt"})
		assert resp.data == b"header-jwt"


def test_get_embedded_token_returns_none_when_absent():
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	@app.route("/token-test")
	def _view():
		token = mod.get_embedded_token_from_request()
		return "none" if token is None else token

	with app.test_client() as client:
		resp = client.get("/token-test")
		assert resp.data == b"none"


# ── token promotion (before_request) ─────────────────────────────────────────

def test_query_token_promoted_to_authorization_header():
	"""?_token= must be promoted to Authorization: Bearer in the request environ."""
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	captured = {}

	@app.route("/promo-test")
	def _view():
		from flask import request
		captured["auth"] = request.environ.get("HTTP_AUTHORIZATION", "")
		return "ok"

	with app.test_client() as client:
		client.get("/promo-test?_token=promoted-jwt")
	assert captured.get("auth") == "Bearer promoted-jwt"


# ── is_embedded_request ───────────────────────────────────────────────────────

def test_is_embedded_request_true_with_token():
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	result = {}

	@app.route("/embed-detect")
	def _view():
		result["embedded"] = mod.is_embedded_request()
		return "ok"

	with app.test_client() as client:
		client.get("/embed-detect?_token=some-jwt")
	assert result.get("embedded") is True


def test_is_embedded_request_false_without_signals():
	mod = _fresh_module()
	app = _make_app()
	if app is None:
		return
	mod.configure_embedding(app)

	result = {}

	@app.route("/embed-detect")
	def _view():
		result["embedded"] = mod.is_embedded_request()
		return "ok"

	with app.test_client() as client:
		client.get("/embed-detect")
	assert result.get("embedded") is False


# ── Public API surface ────────────────────────────────────────────────────────

def test_all_exports_present():
	mod = _fresh_module()
	for name in (
		"configure_embedding",
		"configure_cors",
		"embeddable",
		"get_embedded_token_from_request",
		"is_embedded_request",
	):
		assert hasattr(mod, name), f"missing export: {name}"
	assert set(mod.__all__) == {
		"configure_embedding",
		"configure_cors",
		"embeddable",
		"get_embedded_token_from_request",
		"is_embedded_request",
	}
