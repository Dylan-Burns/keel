"""The users file, the token hashes, and `keel users` (chapter 27.2)."""

import os
import pathlib
import stat

import fastapi
import pydantic
import pytest

from keel import cli
from keel import config
from keel import errors
from keel import users
from keel.api import auth

pytestmark = pytest.mark.unit


def test_hash_token() -> None:
    hashed = users.hash_token("abc")
    assert hashed == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert users.hash_token("abd") != hashed
    token = users.new_token()
    assert len(token) >= 43
    assert token != users.new_token()


def test_add_user_stores_the_hash_only(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "conf" / "users.yaml"
    token = users.add_user(path, "alice", "analyst")
    text = path.read_text()
    assert token not in text
    assert users.hash_token(token) in text
    assert stat.S_IMODE(os.stat(path).st_mode) == users.FILE_MODE
    second = users.add_user(path, "bob", "admin")
    loaded = users.load_file(path)
    assert [(u.name, u.role) for u in loaded.users] == [
        ("alice", "analyst"),
        ("bob", "admin"),
    ]
    assert second != token


@pytest.mark.parametrize(
    ("name", "role", "message"),
    [
        ("alice", "analyst", "exists"),
        ("legacy", "admin", "legacy"),
        ("Alice", "analyst", "must match"),
        ("bad name", "analyst", "must match"),
        ("eve", "owner", "role"),
    ],
)
def test_add_user_rejects(
    tmp_path: pathlib.Path, name: str, role: str, message: str
) -> None:
    path = tmp_path / "users.yaml"
    users.add_user(path, "alice", "analyst")
    with pytest.raises(errors.ConfigError, match=message):
        users.add_user(path, name, role)


def test_load_file_errors(tmp_path: pathlib.Path) -> None:
    assert users.load_file(tmp_path / "absent.yaml").users == []
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert users.load_file(empty).users == []
    bad = tmp_path / "bad.yaml"
    for text in (
        "users: [{name: a, role: admin, token_hash: plain-token}]",
        "users: [{name: a, role: admin, token: x}]",
        "users: :",
    ):
        bad.write_text(text)
        with pytest.raises(errors.ConfigError):
            users.load_file(bad)
    hashed = users.hash_token("x")
    bad.write_text(
        f"users: [{{name: a, role: admin, token_hash: '{hashed}'}},"
        f" {{name: a, role: analyst, token_hash: '{hashed}'}}]"
    )
    with pytest.raises(errors.ConfigError, match="twice"):
        users.load_file(bad)


def test_save_file_error(tmp_path: pathlib.Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(errors.ConfigError, match="cannot write"):
        users.save_file(blocker / "users.yaml", users.UsersFile())


def test_directory_find(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "users.yaml"
    alice = users.add_user(path, "alice", "analyst")
    carol = users.add_user(path, "carol", "admin")
    directory = users.UserDirectory(path, "legacy-token")
    assert directory.configured
    assert directory.find(alice) == users.User("alice", "analyst")
    assert directory.find(carol) == users.User("carol", "admin")
    assert directory.find(carol).is_admin
    assert directory.find("legacy-token") == users.LEGACY
    assert directory.find("nope") is None
    assert directory.find("") is None
    assert directory.find(users.hash_token(alice)) is None
    assert directory.names() == [("alice", "analyst"), ("carol", "admin")]
    without_legacy = users.UserDirectory(path, None)
    assert without_legacy.find("legacy-token") is None
    assert not users.UserDirectory(tmp_path / "absent.yaml", "").configured


def test_directory_reloads_on_change(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "users.yaml"
    alice = users.add_user(path, "alice", "analyst")
    directory = users.UserDirectory(path, None)
    assert directory.find(alice) is not None
    bob = users.add_user(path, "bob", "partner")
    os.utime(path, ns=(1, 1))  # the same old time: the inode still changed
    assert directory.find(bob) == users.User("bob", "partner")
    users.remove_user(path, "bob")
    assert directory.find(bob) is None
    assert directory.find(alice) is not None
    with pytest.raises(errors.ConfigError, match="no user bob"):
        users.remove_user(path, "bob")


def test_bad_edit_fails_closed_and_a_fix_restores(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "users.yaml"
    alice = users.add_user(path, "alice", "analyst")
    bob = users.add_user(path, "bob", "partner")
    directory = users.UserDirectory(path, "legacy-token")
    assert directory.find(bob) is not None
    # The operator removes bob by hand and breaks the file in the same edit.
    good = path.read_text()
    kept = good.split("- name: bob")[0]
    path.write_text(kept + "  broken: [\n")
    assert directory.find(bob) is None  # revoked, not kept from the old list
    assert directory.find(alice) is None  # fail closed
    assert directory.find("legacy-token") == users.LEGACY
    # The stamp was not stored: the same broken file is read again.
    assert directory.find(alice) is None
    path.write_text(kept)
    assert directory.find(alice) == users.User("alice", "analyst")
    assert directory.find(bob) is None
    path.unlink()
    assert directory.find(alice) is None
    nobody = users.UserDirectory(path, None)
    assert not nobody.configured


def test_unreadable_file_fails_closed(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "users.yaml"
    alice = users.add_user(path, "alice", "analyst")
    directory = users.UserDirectory(path / "below-a-file", None)
    assert directory.find(alice) is None


def test_authenticate_users(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "users.yaml"
    token = users.add_user(path, "alice", "analyst")
    only_users = settings.model_copy(
        update={"auth": config.AuthConfig(users_file=path)}
    )
    principal = auth.authenticate(only_users, f"Bearer {token}")
    assert principal.user == users.User("alice", "analyst")
    assert not principal.is_admin
    with pytest.raises(fastapi.HTTPException) as raised:
        auth.authenticate(only_users, "Bearer nope")
    assert raised.value.status_code == 401
    nobody = settings.model_copy(
        update={"auth": config.AuthConfig(users_file=tmp_path / "none.yaml")}
    )
    with pytest.raises(fastapi.HTTPException, match="401"):
        auth.authenticate(nobody, "Bearer x")
    legacy = nobody.model_copy(update={"api_token": pydantic.SecretStr("t")})
    principal = auth.authenticate(legacy, "Bearer t")
    assert principal.user == users.LEGACY
    assert principal.is_admin


def test_users_command(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_env: pytest.MonkeyPatch,
) -> None:
    del clean_env
    path = tmp_path / "users.yaml"
    monkeypatch.setenv("KEEL_AUTH__USERS_FILE", str(path))
    assert cli.main(["users", "add", "alice", "--role", "partner"]) == 0
    out = capsys.readouterr().out.splitlines()
    token = out[-1]
    assert users.UserDirectory(path, None).find(token) == users.User(
        "alice", "partner"
    )
    assert cli.main(["users", "list"]) == 0
    listing = capsys.readouterr().out
    assert "alice\tpartner" in listing
    assert token not in listing
    assert cli.main(["users", "add", "alice", "--role", "partner"]) == 2
    assert cli.main(["users", "remove", "alice"]) == 0
    assert "removed alice" in capsys.readouterr().out
    assert users.UserDirectory(path, None).find(token) is None
    assert cli.main(["users", "remove", "alice"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["users", "add", "bob", "--role", "owner"])
