"""Verification of the Cloudflare Access JWT (BE-23).

Access signs a token for the application and sends it to the origin in the
`Cf-Access-Jwt-Assertion` header. This module checks it and fails closed.
The token, its claims and the keys are never logged.
"""

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import jwt
from fastapi import Request
from jwt import PyJWKClient

# The only routes that need no token. Everything else is protected, so a
# router added later is protected without anyone remembering to do it.
PUBLIC_ROUTES = frozenset({"/healthz"})

HEADER = "cf-access-jwt-assertion"
CLOCK_TOLERANCE_SECONDS = 60
KEY_CACHE_SECONDS = 300
KEY_FETCH_TIMEOUT_SECONDS = 5
# A real Access token is about 1 KB. Refuse anything absurd before parsing.
MAX_TOKEN_LENGTH = 8192

UNAUTHORIZED = (
    401,
    "unauthorized",
    "Sessão inválida ou expirada. Entre novamente.",
)
UNAVAILABLE = (
    503,
    "auth_unavailable",
    "Não foi possível verificar sua sessão. Tente novamente.",
)


@dataclass(frozen=True)
class AccessIdentity:
    subject: str
    email: str | None


class AccessTokenInvalid(Exception):
    """The token is not a valid Access token for this application."""


class AccessUnavailable(Exception):
    """The keys cannot be fetched, or the verifier is not configured."""


class AccessError(Exception):
    """A refusal, with the status and the JSON error body to send."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


class KeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


def certs_url(team_domain: str) -> str:
    return f"https://{team_domain}/cdn-cgi/access/certs"


def build_key_client(team_domain: str) -> PyJWKClient:
    """Keys cached in memory, refetched once when a token names an unknown
    `kid` (PyJWT's own cooldown applies), with a short timeout."""
    return PyJWKClient(
        certs_url(team_domain),
        cache_jwk_set=True,
        lifespan=KEY_CACHE_SECONDS,
        timeout=KEY_FETCH_TIMEOUT_SECONDS,
    )


class AccessVerifier:
    def __init__(self, team_domain: str, aud: str, keys: KeyClient | None = None):
        self.issuer = f"https://{team_domain}"
        self.aud = aud
        self.keys = keys if keys is not None else build_key_client(team_domain)

    def verify(self, token: str) -> AccessIdentity:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            raise AccessTokenInvalid
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessTokenInvalid from exc
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise AccessTokenInvalid

        try:
            key = self.keys.get_signing_key_from_jwt(token)
        except (jwt.PyJWKClientConnectionError, jwt.PyJWKSetError, OSError) as exc:
            raise AccessUnavailable from exc
        except jwt.PyJWTError as exc:
            # An unknown `kid`, after PyJWT refetched the keys once.
            raise AccessTokenInvalid from exc

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.aud,
                leeway=CLOCK_TOLERANCE_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AccessTokenInvalid from exc

        subject = claims.get("sub")
        email = claims.get("email")
        if not isinstance(subject, str) or not subject:
            raise AccessTokenInvalid
        if email is not None and not isinstance(email, str):
            raise AccessTokenInvalid
        return AccessIdentity(subject=subject, email=email)


def log_not_configured() -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": "WARNING",
        "event": "access_not_configured",
    }
    sys.stdout.write(json.dumps(entry) + "\n")
    sys.stdout.flush()


def require_access(request: Request) -> AccessIdentity | None:
    """Applied to the whole application. Returns the verified identity, or
    None on a public route. BE-24 reads the identity from here."""
    route = request.scope.get("route")
    if route is not None and route.path in PUBLIC_ROUTES:
        return None

    verifier: AccessVerifier | None = request.app.state.access_verifier
    if verifier is None:
        raise AccessError(*UNAVAILABLE)
    token = request.headers.get(HEADER)
    if not token:
        raise AccessError(*UNAUTHORIZED)
    try:
        return verifier.verify(token)
    except AccessUnavailable:
        raise AccessError(*UNAVAILABLE) from None
    except AccessTokenInvalid:
        raise AccessError(*UNAUTHORIZED) from None
