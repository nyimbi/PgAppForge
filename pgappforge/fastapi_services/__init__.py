"""
pgappforge/fastapi_services/__init__.py

FastAPI async service layer for PgAppForge.

Provides high-throughput async endpoints alongside the main Flask/FAB application:
  /async/mpesa/*   — M-Pesa C2B webhooks (confirmation, validation, STK status)
  /async/ai/*      — NL-to-SQL and document extraction inference
  /async/health    — top-level health check

Quick start::

    from pgappforge.fastapi_services import create_fastapi_app, mount_fastapi

    # In your Flask app factory:
    mount_fastapi(flask_app)

    # Standalone uvicorn (production / high-throughput):
    # uvicorn pgappforge.fastapi_services.app:get_asgi_app --factory --port 8001

pip install fastapi uvicorn asgiref
"""
from pgappforge.fastapi_services.app import create_fastapi_app, mount_fastapi, get_asgi_app

__all__ = ["create_fastapi_app", "mount_fastapi", "get_asgi_app"]
