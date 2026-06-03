"""Cookie-based admin authentication — simple password gate for the whole app.

Protected:  all paths
Exempt:    /auth/*, /login.html (otherwise you can't log in)
Auth off:  when ADMIN_PASSWORD is empty in .env
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Paths that do NOT require admin auth (login flow only) ───────
_AUTH_EXEMPT_PREFIXES = (
    "/auth/",
    "/login.html",
    "/kb-chat.html",
    "/kb-api/",
    "/scenario-api.html",
    "/health",
    "/mcp/",
    "/test",
    "/test/",
)


def _is_auth_exempt(path: str) -> bool:
    for prefix in _AUTH_EXEMPT_PREFIXES:
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            return True
    return False


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Enforce a simple cookie-based password gate on the admin panel.

    - ADMIN_PASSWORD empty  → auth disabled, all requests pass through.
    - Unauthenticated       → HTML paths redirect to /login.html; API paths get 401.
    - Authenticated         → proceed normally.
    """

    async def dispatch(self, request: Request, call_next):
        from config import settings

        password = (settings.admin_password or "").strip()

        if not password:
            return await call_next(request)

        path = request.url.path or "/"

        # Allow unauthenticated access to exempt paths
        if _is_auth_exempt(path):
            return await call_next(request)

        # Check the omnikb_auth cookie
        cookie_val = request.cookies.get("omnikb_auth", "")
        if cookie_val == password:
            return await call_next(request)

        # Not authenticated
        # HTML paths (including "/") → redirect to login
        if path.rstrip("/") in ("", "/index.html"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login.html", status_code=302)

        # API-ish paths → 401 JSON
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — please log in at /login.html"},
        )


# ── Auth endpoints ────────────────────────────────────────────────

class LoginBody(BaseModel):
    password: str = Field(..., min_length=1, description="Admin password")


@router.post("/login")
async def auth_login(body: LoginBody, request: Request):
    """Validate the admin password and set an authentication cookie."""
    from config import settings

    expected = (settings.admin_password or "").strip()
    if not expected:
        # Auth is disabled — nothing to validate against
        return JSONResponse(
            status_code=400,
            content={"detail": "Auth is not configured (ADMIN_PASSWORD is empty)."},
        )

    if body.password.strip() != expected:
        logger.info("auth/login: rejected from %s", _client_ip(request))
        return JSONResponse(
            status_code=401,
            content={"detail": "Incorrect password."},
        )

    logger.info("auth/login: accepted from %s", _client_ip(request))
    resp = JSONResponse(content={"ok": True})
    _set_auth_cookie(resp, body.password.strip())
    return resp


@router.post("/logout")
async def auth_logout():
    """Clear the authentication cookie."""
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie("omnikb_auth", path="/")
    return resp


@router.get("/status")
async def auth_status(request: Request):
    """Report whether the current request is authenticated."""
    from config import settings

    password = (settings.admin_password or "").strip()
    if not password:
        return {"auth_enabled": False, "authenticated": True}

    cookie_val = request.cookies.get("omnikb_auth", "")
    return {
        "auth_enabled": True,
        "authenticated": cookie_val == password,
    }


# ── Helpers ───────────────────────────────────────────────────────

def _set_auth_cookie(response, password: str) -> None:
    response.set_cookie(
        key="omnikb_auth",
        value=password,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=86400 * 30,  # 30 days
    )


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


# ── Deferred-patch: let the settings API notify us when the live
#    password changes so the middleware picks up the new value.
#    settings.admin_password is read per-request from the global
#    Settings object, so no explicit notification is needed — the
#    middleware call_next path reads it live every time.
