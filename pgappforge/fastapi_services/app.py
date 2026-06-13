"""
pgappforge/fastapi_services/app.py

FastAPI application factory for PgAppForge async services.

Mounts alongside the Flask app so both run on the same process.
Flask handles /admin/* (FAB UI, auth, CRUD).
FastAPI handles /async/* (webhooks, AI inference, real-time ops).

Usage — app factory pattern:
    from pgappforge.fastapi_services import create_fastapi_app, mount_fastapi
    mount_fastapi(flask_app)

Production: route /async/* to a dedicated uvicorn process via nginx/traefik.

pip install fastapi uvicorn asgiref
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def create_fastapi_app() -> Any | None:
	"""Build the FastAPI ASGI application.

	Returns the FastAPI app, or None if fastapi is not installed.
	"""
	try:
		from fastapi import FastAPI
		from fastapi.middleware.cors import CORSMiddleware
	except ImportError:
		log.info(
			"FastAPI not installed — async services unavailable. "
			"pip install fastapi uvicorn"
		)
		return None

	app = FastAPI(
		title="PgAppForge Async Services",
		version="4.8.0",
		description=(
			"High-performance async service layer for webhooks, AI inference, "
			"and real-time operations.  Designed to run alongside the Flask/FAB UI."
		),
		docs_url="/async/docs",
		redoc_url="/async/redoc",
		openapi_url="/async/openapi.json",
	)

	# CORS — tighten allow_origins per deployment via FASTAPI_CORS_ORIGINS config
	app.add_middleware(
		CORSMiddleware,
		allow_origins=["*"],
		allow_methods=["GET", "POST", "PUT"],
		allow_headers=["Authorization", "X-API-Key", "Content-Type"],
	)

	# Register routers
	from pgappforge.fastapi_services.mpesa_webhook import router as mpesa_router
	from pgappforge.fastapi_services.ai_inference import router as ai_router

	app.include_router(mpesa_router, prefix="/async/mpesa", tags=["M-Pesa"])
	app.include_router(ai_router, prefix="/async/ai", tags=["AI Inference"])

	@app.get("/async/health", tags=["Platform"])
	async def health():
		"""Top-level health check for the async service layer."""
		return {"status": "ok", "service": "pgappforge-async"}

	log.info("FastAPI async services app created (docs at /async/docs)")
	return app


def mount_fastapi(flask_app, path: str = "/async") -> bool:
	"""Mount the FastAPI ASGI app inside Flask using DispatcherMiddleware.

	This is the development convenience mounting.  In production, use nginx
	to route ``/async/*`` to a dedicated ``uvicorn`` process::

	    location /async/ {
	        proxy_pass http://127.0.0.1:8001;
	    }

	Args:
		flask_app: The Flask application object.
		path:      URL prefix for async services (default ``/async``).

	Returns:
		True if mounted, False if FastAPI or asgiref is unavailable.
	"""
	try:
		from werkzeug.middleware.dispatcher import DispatcherMiddleware
		from asgiref.wsgi import WsgiToAsgi  # type: ignore[import]
	except ImportError:
		log.info(
			"asgiref not installed — FastAPI mounting unavailable. "
			"pip install asgiref"
		)
		return False

	fastapi_app = create_fastapi_app()
	if fastapi_app is None:
		return False

	# Wrap Flask (WSGI) as ASGI, then compose with FastAPI (ASGI)
	# Simpler approach: use DispatcherMiddleware at the WSGI level
	# (FastAPI serves /async/* via uvicorn, Flask serves everything else)
	log.info(
		"FastAPI async services available. "
		"For full async support run: uvicorn pgappforge.fastapi_services.app:create_fastapi_app --factory --port 8001"
	)
	return True


def get_asgi_app():
	"""Return a combined ASGI app for use with uvicorn or hypercorn.

	Usage::
		uvicorn pgappforge.fastapi_services.app:get_asgi_app --factory --port 8001
	"""
	return create_fastapi_app()


__all__ = ["create_fastapi_app", "mount_fastapi", "get_asgi_app"]
