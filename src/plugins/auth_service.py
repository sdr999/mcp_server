"""Supabase Auth REST client service.

Provides async, non-blocking authentication endpoints against Supabase Auth API:
- sign_up (POST /auth/v1/signup)
- sign_in (POST /auth/v1/token?grant_type=password)
- refresh_token (POST /auth/v1/token?grant_type=refresh_token)
- recover_password (POST /auth/v1/recover)

Includes PII log masking and Supabase error sanitization.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx
# Use Starlette's HTTPException + status constants (same interface as FastAPI's)
# so this Starlette-based server does not hard-depend on fastapi (test-collect fix).
from starlette import status
from starlette.exceptions import HTTPException

log = logging.getLogger("MCP_logger")


def _mask_email(email: str) -> str:
    """Mask PII for safe logging: 'john@example.com' -> 'j***@e***.com'."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    parts = domain.split(".")
    masked_local = local[0] + "***" if local else "***"
    masked_domain = parts[0][0] + "***" if parts[0] else "***"
    return f"{masked_local}@{masked_domain}.{parts[-1]}"


def _sanitize_supabase_error(status_code: int, error_data: dict) -> HTTPException:
    """Extract a safe, user-facing HTTPException from Supabase REST response."""
    msg = (error_data.get("msg") or error_data.get("error_description") or error_data.get("message") or "").lower()

    if status_code == 429 or "rate" in msg or "too many" in msg:
        detail = "Too many attempts. Please try again later."
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)

    if "already registered" in msg or "duplicate" in msg or "already exists" in msg:
        detail = "An account with this email already exists."
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if "invalid" in msg and ("password" in msg or "credentials" in msg or "login" in msg):
        detail = "Invalid email or password."
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    if "email" in msg and "not confirmed" in msg:
        detail = "Email address has not been confirmed."
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if status_code == 401 or status_code == 400:
        detail = error_data.get("msg") or error_data.get("error_description") or "Authentication request invalid."
        return HTTPException(status_code=status_code, detail=detail)

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Authentication service unavailable. Please try again.",
    )


class SupabaseAuthService:
    def __init__(self, supabase_url: str, supabase_key: str):
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY/SUPABASE_PUBLISHABLE_KEY are required for SupabaseAuthService")
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_key = supabase_key

    def _get_headers(self, bearer_token: Optional[str] = None) -> dict:
        headers = {
            "apikey": self.supabase_key,
            "Content-Type": "application/json",
            "User-Agent": "MCP-Server/1.0",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return headers

    async def sign_up(self, email: str, password: str, metadata: Optional[dict] = None) -> Dict[str, Any]:
        masked = _mask_email(email)
        log.info("Supabase signup request received | email=%s", masked)
        url = f"{self.supabase_url}/auth/v1/signup"
        payload: Dict[str, Any] = {"email": email, "password": password}
        if metadata:
            payload["data"] = metadata

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, json=payload, headers=self._get_headers())
            except Exception as exc:
                log.error("Network error during Supabase signup | email=%s, err=%s", masked, exc)
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service unreachable.")

            if res.status_code not in (200, 201):
                err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"msg": res.text}
                raise _sanitize_supabase_error(res.status_code, err_body)

            data = res.json()
            log.info("Supabase signup successful | email=%s", masked)
            return data

    async def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        masked = _mask_email(email)
        log.info("Supabase signin request received | email=%s", masked)
        url = f"{self.supabase_url}/auth/v1/token?grant_type=password"
        payload = {"email": email, "password": password}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, json=payload, headers=self._get_headers())
            except Exception as exc:
                log.error("Network error during Supabase signin | email=%s, err=%s", masked, exc)
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service unreachable.")

            if res.status_code != 200:
                err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"msg": res.text}
                raise _sanitize_supabase_error(res.status_code, err_body)

            data = res.json()
            log.info("Supabase signin successful | email=%s", masked)
            return data

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        log.info("Supabase token refresh requested")
        url = f"{self.supabase_url}/auth/v1/token?grant_type=refresh_token"
        payload = {"refresh_token": refresh_token}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, json=payload, headers=self._get_headers())
            except Exception as exc:
                log.error("Network error during token refresh | err=%s", exc)
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service unreachable.")

            if res.status_code != 200:
                err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"msg": res.text}
                raise _sanitize_supabase_error(res.status_code, err_body)

            return res.json()

    async def recover_password(self, email: str) -> Dict[str, Any]:
        masked = _mask_email(email)
        log.info("Supabase password recovery requested | email=%s", masked)
        url = f"{self.supabase_url}/auth/v1/recover"
        payload = {"email": email}

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, json=payload, headers=self._get_headers())
            except Exception as exc:
                log.error("Network error during password recovery | email=%s, err=%s", masked, exc)
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth service unreachable.")

            if res.status_code not in (200, 201):
                err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"msg": res.text}
                raise _sanitize_supabase_error(res.status_code, err_body)

            return {"message": "If that email exists, a password reset email has been sent."}
