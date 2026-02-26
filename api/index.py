"""
Vercel serverless entry point for the OilGas Nanobot Swarm API.

This module wraps the FastAPI app for Vercel's Python runtime.
The static dashboard is served from /nanobot/static/ via the vercel.json routes.

Note: Vercel serverless functions have a 250 MB code limit and 10 s cold-start
limit on the Hobby plan. For the full hierarchical swarm (Redis + background
scheduler) use Render or Railway. This entry point exposes the REST API
endpoints in a stateless-compatible mode.
"""

import os
from mangum import Mangum
from nanobot.api.gateway import app

# Vercel requires the ASGI handler to be named `handler`
handler = Mangum(app, lifespan="off")
