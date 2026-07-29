"""OIDC authorization-code flow with PKCE.

PKCE is used even though this is a confidential client: it costs one hash and it
removes the whole class of attack where an intercepted authorization code is
redeemed by someone else.

The verifier is held server-side in Redis keyed by `state`, not in a cookie, so
a browser that never completes the flow leaves nothing behind after the TTL.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt

from nexus.cache import get_redis
from nexus.config import Settings

FLOW_TTL_SECONDS = 600
_FLOW_KEY = "nexus:oidc:flow:{state}"


@dataclass(slots=True)
class OidcClaims:
    subject: str
    issuer: str
    email: str
    name: str
    picture: str | None = None


class OidcError(RuntimeError):
    pass


class OidcClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._metadata: dict[str, Any] | None = None
        self._jwks: Any = None

    async def _discover(self) -> dict[str, Any]:
        if self._metadata is None:
            url = f"{self._settings.auth.issuer.rstrip('/')}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
                response.raise_for_status()
                self._metadata = response.json()
        return self._metadata

    async def _keys(self) -> Any:
        if self._jwks is None:
            metadata = await self._discover()
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(metadata["jwks_uri"])
                response.raise_for_status()
                self._jwks = JsonWebKey.import_key_set(response.json())
        return self._jwks

    async def start(self, redirect_uri: str, next_path: str = "/") -> str:
        """Create the flow and return the URL to send the browser to."""
        metadata = await self._discover()
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        await get_redis().setex(
            _FLOW_KEY.format(state=state),
            FLOW_TTL_SECONDS,
            json.dumps({"verifier": verifier, "redirect_uri": redirect_uri, "next": next_path}),
        )

        params = {
            "client_id": self._settings.auth.client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{metadata['authorization_endpoint']}?{urlencode(params)}"

    async def complete(self, code: str, state: str) -> tuple[OidcClaims, str]:
        """Exchange the code and return (claims, next_path)."""
        redis = get_redis()
        key = _FLOW_KEY.format(state=state)
        raw = await redis.get(key)
        if raw is None:
            # Unknown or already-used state. Both are treated the same, which
            # also makes the endpoint single-use by construction.
            raise OidcError("unknown or expired state")
        await redis.delete(key)
        flow = json.loads(raw)

        metadata = await self._discover()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": flow["redirect_uri"],
            "client_id": self._settings.auth.client_id,
            "code_verifier": flow["verifier"],
        }
        if self._settings.auth.client_secret:
            data["client_secret"] = self._settings.auth.client_secret.get_secret_value()

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(metadata["token_endpoint"], data=data)
        if response.status_code != 200:
            raise OidcError(f"token exchange failed: {response.status_code}")

        id_token = response.json().get("id_token")
        if not id_token:
            raise OidcError("no id_token in token response")

        claims = jwt.decode(id_token, await self._keys())
        claims.validate()  # signature, exp, iat

        if claims.get("iss") != metadata["issuer"]:
            raise OidcError("issuer mismatch")

        email = claims.get("email")
        if not email:
            raise OidcError("id_token has no email claim")

        return (
            OidcClaims(
                subject=str(claims["sub"]),
                issuer=str(claims["iss"]),
                email=str(email).lower().strip(),
                name=str(claims.get("name") or email.split("@")[0]),
                picture=claims.get("picture"),
            ),
            flow.get("next", "/"),
        )
