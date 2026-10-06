"""Clerk sign-in for the hosted app (Railway). Off unless CLERK_PUBLISHABLE_KEY is set, so local runs stay open.

One shared workspace: any valid session token from this Clerk instance is enough; who may sign in at
all is set in the Clerk dashboard (allowlist or restricted sign-ups). The browser sends Clerk's
`__session` cookie with every request on the app's domain (fetches, images, downloads, WebSockets);
other clients may send `Authorization: Bearer <token>`.
"""

import base64
import os
import re

import jwt
from loguru import logger
from starlette.responses import JSONResponse

PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
# Origins whose tokens are accepted (the token's azp), e.g. https://daxagent.up.railway.app; empty = any
AUTHORIZED_PARTIES = [p.strip().rstrip("/") for p in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()]
# Reachable without signing in: the app shell and its files (they hold no data), health, OAuth returns.
OPEN = re.compile(r"^/(?:$|health$|assets/|mcp/callback/|settings/admin/seed$|[^/]+\.(?:svg|png|ico|jpg|jpeg|webp|gif|json|txt|webmanifest|js|css)$)")


def _issuer(publishable_key: str) -> str:
    """Clerk's frontend API (the token issuer) is encoded in the publishable key: pk_<env>_<base64(host$)>."""
    encoded = publishable_key.split("_", 2)[-1]
    host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    return f"https://{host}"


ISSUER = _issuer(PUBLISHABLE_KEY) if PUBLISHABLE_KEY else ""
_jwks = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True) if ISSUER else None


def enabled() -> bool:
    return bool(ISSUER)


def verify(token: str) -> dict:
    """The session's claims; raises when the token is missing, expired, or not from this Clerk instance."""
    if not token:
        raise jwt.InvalidTokenError("no session token")
    key = _jwks.get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER, leeway=30, options={"require": ["exp", "iat", "sub"]})
    if AUTHORIZED_PARTIES and str(claims.get("azp", "")).rstrip("/") not in AUTHORIZED_PARTIES:
        raise jwt.InvalidTokenError("token issued for another site")
    return claims


def _token(scope: dict) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    if headers.get("authorization", "").lower().startswith("bearer "):
        return headers["authorization"][7:].strip()
    for part in headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "__session":
            return value
    return ""


class ClerkGate:
    """ASGI middleware: every HTTP request and WebSocket outside OPEN needs a valid Clerk session."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not enabled() or scope["type"] not in ("http", "websocket") or OPEN.match(scope.get("path", "")) \
                or (scope["type"] == "http" and scope.get("method") == "OPTIONS"):
            return await self.app(scope, receive, send)
        try:
            verify(_token(scope))
        except Exception as e:
            logger.info(f"[auth] refused {scope['type']} {scope.get('path')}: {e}")
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4401})
            return await JSONResponse({"detail": "Sign in required"}, status_code=401)(scope, receive, send)
        return await self.app(scope, receive, send)
