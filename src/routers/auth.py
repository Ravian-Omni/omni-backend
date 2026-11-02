"""Email and password sign-in for the hosted app (src/auth.py): log in, log out, who am I, add accounts."""

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src import auth
from src.database import end_session, get_user, save_account, save_user, start_session

router = APIRouter()


class Login(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class NewUser(Login):
    name: str = Field("", max_length=100)


@router.get("/me")
async def me(request: Request) -> dict:
    """Whether sign-in is on, which kind, and who is signed in (null when nobody is)."""
    if not auth.enabled():
        return {"auth": False, "user": None}
    user = await auth.SessionGate.user(request.scope)
    if auth.mode() == "clerk":  # the page needs the publishable key to load Clerk; it is public by design
        return {"auth": True, "mode": "clerk", "publishable_key": auth.clerk().publishable_key, "user": user}
    return {"auth": True, "user": user}


class Account(BaseModel):
    email: str = Field("", max_length=200)
    name: str = Field("", max_length=200)


@router.put("/me")
async def report_me(body: Account, request: Request) -> dict:
    """The app reports the signed-in person's email and name (a Clerk session token carries only their user id),
    so the admin dashboard can say who asked what. A label only: access is decided by the verified id."""
    user = await auth.SessionGate.user(request.scope) if auth.enabled() else None
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    await save_account(user.get("id") or user["email"], body.email.strip(), body.name.strip())
    return {"saved": True}


@router.post("/login")
async def login(body: Login, request: Request) -> JSONResponse:
    user = await get_user(body.email.strip())
    if not user or not auth.check_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    token = secrets.token_urlsafe(32)
    await start_session(user["email"], token, auth.SESSION_DAYS)
    response = JSONResponse({"email": user["email"], "name": user["name"]})
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=https, samesite="lax", path="/")
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    await end_session(request.cookies.get(auth.COOKIE, ""))
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@router.post("/users")
async def add_user(body: NewUser, request: Request) -> dict:
    """Add an account (or reset its password); needs X-Admin-Token = DAXAGENT_ADMIN_TOKEN."""
    if not auth.admin_ok(request.headers.get("x-admin-token", "")):
        raise HTTPException(status_code=403, detail="Adding accounts needs the admin token")
    await save_user(body.email.strip(), auth.hash_password(body.password), body.name.strip())
    return {"email": body.email.strip().lower(), "name": body.name.strip()}
