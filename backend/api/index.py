"""Vercel Python serverless entry point.

Vercel's @vercel/python runtime auto-detects the `app` ASGI variable and
serves it. All requests routed via vercel.json land here, then FastAPI
dispatches them to the right router.
"""

from app.main import app  # noqa: F401  (Vercel reads `app` symbol)
