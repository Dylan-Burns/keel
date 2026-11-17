"""The visitor key check and the visitor Principal (auth.public)."""

from __future__ import annotations

import fastapi
import pydantic
import pytest

from keel import config
from keel import users
from keel.api import auth

KEY = "sk-ant-api03-" + "a" * 40


@pytest.mark.parametrize("header", [None, "", "   "])
def test_no_visitor_key(header: str | None) -> None:
    assert auth.visitor_key(header) is None


def test_visitor_key_is_secret() -> None:
    key = auth.visitor_key(f"  {KEY}  ")
    assert key is not None
    assert key.get_secret_value() == KEY
    assert KEY not in repr(key)


@pytest.mark.parametrize(
    "header",
    [
        "sk-ant-short",
        "Bearer " + KEY,
        KEY[:20] + " " + KEY[20:],
        "sk-ant-" + "a" * 20 + "!",
    ],
)
def test_malformed_visitor_key(header: str) -> None:
    with pytest.raises(fastapi.HTTPException) as caught:
        auth.visitor_key(header)
    assert caught.value.status_code == 400
    assert header.strip() not in str(caught.value.detail)


def test_visitor_name_is_a_stable_hash_of_the_key() -> None:
    first = auth.visitor(pydantic.SecretStr(KEY))
    again = auth.visitor(pydantic.SecretStr(KEY))
    other = auth.visitor(pydantic.SecretStr(KEY[:-1] + "b"))
    assert first.user == again.user
    assert first.user != other.user
    assert first.user.name.startswith("visitor-")
    assert KEY[7:] not in first.user.name
    assert first.is_visitor
    assert not first.is_admin
    assert auth.visitor(None).user == users.User("visitor", "visitor")


def test_public_mode_makes_a_visitor(settings: config.Settings) -> None:
    public = settings.model_copy(
        update={"auth": settings.auth.model_copy(update={"public": True})}
    )
    caller = auth.authenticate(public, None, key=pydantic.SecretStr(KEY))
    assert caller.is_visitor


def test_token_mode_refuses_a_visitor(settings: config.Settings) -> None:
    with pytest.raises(fastapi.HTTPException) as caught:
        auth.authenticate(settings, None, key=pydantic.SecretStr(KEY))
    assert caught.value.status_code == 401
