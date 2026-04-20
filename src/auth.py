"""Token validation middleware — rejects any request missing ?token=SERVER_TOKEN."""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        presented = request.query_params.get("token", "")
        if not presented or not hmac.compare_digest(presented, config.server_token()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
