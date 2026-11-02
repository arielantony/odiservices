import time

import jwt
import pytest

from server.access import (
    AccessIdentity,
    AccessTokenInvalid,
    AccessUnavailable,
    AccessVerifier,
)
from tests.access_helpers import (
    AUD,
    EMAIL,
    TEAM,
    FakeKeyClient,
    make_hs256_token_with_public_key,
    make_token,
    make_unsigned_token,
    other_private_key,
)


def verifier(error=None) -> AccessVerifier:
    return AccessVerifier(TEAM, AUD, FakeKeyClient(error))


def rejected(token):
    with pytest.raises(AccessTokenInvalid):
        verifier().verify(token)


def test_valid_token_returns_identity():
    identity = verifier().verify(make_token())

    assert identity == AccessIdentity(subject="sub-fulano", email=EMAIL)


def test_audience_as_list_matches():
    token = make_token(aud=["outro-aplicativo", AUD])

    assert verifier().verify(token).subject == "sub-fulano"


def test_wrong_audience_rejected():
    rejected(make_token(aud=["f" * 64]))


def test_wrong_issuer_rejected():
    rejected(make_token(iss="https://outro.cloudflareaccess.com"))


def test_expired_token_rejected():
    rejected(make_token(exp=int(time.time()) - 120))


def test_clock_tolerance():
    now = int(time.time())

    assert verifier().verify(make_token(exp=now - 30))
    assert verifier().verify(make_token(nbf=now + 30))
    rejected(make_token(nbf=now + 120))


def test_missing_exp_rejected():
    rejected(make_token(exp=None))


@pytest.mark.parametrize("subject", [None, ""])
def test_missing_or_empty_subject_rejected(subject):
    rejected(make_token(sub=subject))


def test_email_must_be_string():
    rejected(make_token(email=123))


def test_signed_with_other_key_rejected():
    rejected(make_token(key=other_private_key()))


def test_none_algorithm_rejected():
    rejected(make_unsigned_token())


def test_hs256_with_public_key_rejected():
    rejected(make_hs256_token_with_public_key())


def test_missing_kid_rejected():
    rejected(make_token(headers={}))


def test_unknown_kid_rejected():
    rejected(make_token(headers={"kid": "outra-chave"}))


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "é.ã.ç", "x" * 9000])
def test_garbage_rejected(garbage):
    rejected(garbage)


@pytest.mark.parametrize(
    "error", [jwt.PyJWKClientConnectionError("rede"), OSError("rede")]
)
def test_key_fetch_failure_is_unavailable(error):
    with pytest.raises(AccessUnavailable):
        verifier(error).verify(make_token())
