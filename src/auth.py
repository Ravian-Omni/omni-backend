"""Sign-in for the hosted app: email and password accounts kept in DAXAGENT's own database.

Off unless DAXAGENT_AUTH=on (local runs stay open). Each signed-in person has their own chats, agents and
connections: the gate sets every request's user_id to the person (as_user), their Clerk user id or email. Logging in sets an HttpOnly `dax_session` cookie that the browser sends with
every request on the app's domain (fetches, images, downloads, WebSockets); the session lives in the
`sessions` table, so signing out ends it. Accounts are added with DAXAGENT_ADMIN_TOKEN (POST /auth/users).

DAXAGENT_AUTH=clerk hands sign-in to Clerk instead (CLERK_PUBLISHABLE_KEY names the instance; no secret key is
needed). Clerk's script keeps a short-lived session token in the `__session` cookie on the app's domain and
renews it; the gate checks it against the instance's published keys.
"""

import base64
import functools
import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import parse_qsl, urlencode

import jwt
from loguru import logger
from starlette.responses import JSONResponse

COOKIE = "dax_session"
CLERK_COOKIE = "__session"
SESSION_DAYS = 30
# Reachable without signing in: the app shell and its files (they hold no data), health, the login
# itself, OAuth returns, the token-guarded admin endpoints and the Teams and Slack bots (each checks its own signature).
OPEN = re.compile(r"^/(?:$|health$|assets/|auth/(?:login|me|users)$|mcp/callback/|settings/admin/seed$|teams/messages$|slack/events$"
                  r"|[^/]+\.(?:svg|png|ico|jpg|jpeg|webp|gif|json|txt|webmanifest|js|css)$)")


def mode() -> str:
    """off (local runs), local (email and password accounts) or clerk (Clerk sign-in)."""
    value = os.getenv("DAXAGENT_AUTH", "").lower()
    return "clerk" if value == "clerk" else "local" if value in ("on", "1", "true") else "off"


def enabled() -> bool:
    return mode() != "off"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        given = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(given.hex(), digest)
    except ValueError:
        return False


def admin_ok(token: str) -> bool:
    expected = os.getenv("DAXAGENT_ADMIN_TOKEN", "")
    return bool(expected) and hmac.compare_digest(token or "", expected)


def is_admin(user_id: str) -> bool:
    """Who may open the admin dashboard (every user's chats): the user ids in DAXAGENT_ADMINS (comma-separated Clerk
    user ids, or emails with local sign-in), else DAXAGENT_OWNER. Anyone on a local run, where sign-in is off."""
    if not enabled():
        return True
    admins = os.getenv("DAXAGENT_ADMINS") or os.getenv("DAXAGENT_OWNER", "")
    return user_id in {a.strip() for a in admins.split(",") if a.strip()}


def cookie(scope: dict, name: str) -> str:
    for k, v in scope.get("headers", []):
        if k.decode().lower() == "cookie":
            for part in v.decode().split(";"):
                key, _, value = part.strip().partition("=")
                if key == name:
                    return value
    return ""


def as_user(scope: dict, uid: str) -> None:
    """Chats, settings and connections are keyed by user_id; a signed-in request acts only as its own account."""
    kept = [(k, v) for k, v in parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True) if k != "user_id"]
    scope["query_string"] = urlencode(kept + [("user_id", uid)]).encode()


def origin(scope: dict) -> str:
    """This request's own origin: the page is served from here, so a Clerk token must have been issued to it."""
    scheme = scope.get("scheme", "http")
    host = next((v.decode() for k, v in scope.get("headers", []) if k == b"host"), "")
    return f"{ {'ws': 'http', 'wss': 'https'}.get(scheme, scheme) }://{host}"


class Clerk:
    """Clerk sign-in: checks a session token against the instance's published keys (fetched once, cached)."""

    def __init__(self, publishable_key: str):
        self.publishable_key = publishable_key
        encoded = publishable_key.split("_", 2)[2]  # pk_<env>_<base64 of the Frontend API host followed by "$">
        self.frontend_api = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
        self._keys = jwt.PyJWKClient(f"https://{self.frontend_api}/.well-known/jwks.json", cache_keys=True)

    def user(self, token: str, origin: str) -> dict | None:
        """Who the token signs in on this origin ({"id": the Clerk user}), or None when it is missing,
        expired, issued to another site, or the person still has a Clerk step to finish (pending)."""
        if not token:
            return None
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], leeway=30, options={"require": ["exp", "sub"]})
        except jwt.PyJWTError as e:
            logger.debug(f"[auth] Clerk session token rejected: {e}")
            return None
        if claims.get("azp", origin) != origin or claims.get("sts") == "pending":
            return None
        return {"id": claims["sub"]}


@functools.lru_cache(maxsize=1)
def clerk() -> Clerk:
    return Clerk(os.environ["CLERK_PUBLISHABLE_KEY"])


class SessionGate:
    """ASGI middleware: every HTTP request and WebSocket outside OPEN needs a live session."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not enabled() or scope["type"] not in ("http", "websocket") or OPEN.match(scope.get("path", "")) \
                or (scope["type"] == "http" and scope.get("method") == "OPTIONS"):
            return await self.app(scope, receive, send)
        user = await self.user(scope)
        if user:
            as_user(scope, user.get("id") or user["email"])
            return await self.app(scope, receive, send)
        logger.info(f"[auth] refused {scope['type']} {scope.get('path')}: not signed in")
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4401})
        return await JSONResponse({"detail": "Sign in required"}, status_code=401)(scope, receive, send)

    @staticmethod
    async def user(scope: dict) -> dict | None:
        """The signed-in person behind a request, by the mode in force."""
        if mode() == "clerk":
            return clerk().user(cookie(scope, CLERK_COOKIE), origin(scope))
        from src.database import session_user

        return await session_user(cookie(scope, COOKIE))
