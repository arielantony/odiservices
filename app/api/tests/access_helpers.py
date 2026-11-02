"""Fake Cloudflare Access for the BE-23 tests.

An RSA key pair is generated at run time. Tokens are signed with it and the
public key is served by a fake key client, so no key, no token and no network
call is ever stored or made. Names and emails are obviously fictitious.
"""

import base64
import hashlib
import hmac
import json
import time
from functools import lru_cache
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

TEAM = "exemplo.cloudflareaccess.com"
AUD = "0123456789abcdef" * 4
KID = "chave-ficticia-1"
EMAIL = "fulano@exemplo.com"


@lru_cache
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@lru_cache
def other_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(**overrides):
    now = int(time.time())
    base = {
        "iss": f"https://{TEAM}",
        "aud": [AUD],
        "sub": "sub-fulano",
        "email": EMAIL,
        "iat": now,
        "exp": now + 300,
    }
    base.update(overrides)
    return {name: value for name, value in base.items() if value is not None}


def make_token(key=None, headers=None, **overrides):
    """A valid token unless told otherwise. A claim set to None is omitted."""
    header = {"kid": KID}
    if headers is not None:
        header = headers
    return jwt.encode(
        claims(**overrides),
        key or private_key(),
        algorithm="RS256",
        headers=header,
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_hs256_token_with_public_key():
    """Algorithm confusion: HS256, with the RSA public key as the secret.
    Built by hand because PyJWT refuses to sign this way."""
    secret = private_key().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = _b64(json.dumps(claims()).encode())
    signature = hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(signature)}"


def make_unsigned_token():
    head = _b64(json.dumps({"alg": "none", "typ": "JWT", "kid": KID}).encode())
    body = _b64(json.dumps(claims()).encode())
    return f"{head}.{body}."


class FakeKeyClient:
    """Stands in for PyJWKClient: it serves one public key, or fails."""

    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error is not None:
            raise self.error
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != KID:
            raise jwt.PyJWKClientError("no matching key")
        return SimpleNamespace(key=private_key().public_key())
