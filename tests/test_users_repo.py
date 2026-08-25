from uuid import uuid4

import pytest
from src.backend.common import auth, users_repo
from src.backend.common.queries import get


def _email() -> str:
    return f"{uuid4().hex}@test.invalid"


def test_query_loader_raises_on_missing_block() -> None:
    with pytest.raises(KeyError, match="no_such_block"):
        get("users", "no_such_block")

def test_create_and_get_by_email() -> None:
    email = _email()
    created = users_repo.create("Ada", email, auth.hash_password("pw"))
    fetched = users_repo.get_by_email(email)
    assert fetched is not None
    assert fetched.user_id == created.user_id
    assert fetched.email == email


def test_get_by_email_missing_returns_none() -> None:
    assert users_repo.get_by_email("missing@nowhere.test") is None


def test_get_by_id_roundtrips() -> None:
    email = _email()
    created = users_repo.create("Bo", email, auth.hash_password("pw"))
    fetched = users_repo.get_by_id(created.user_id)
    assert fetched is not None
    assert fetched.name == "Bo"


def test_email_unique_constraint() -> None:
    email = _email()
    users_repo.create("Cara", email, auth.hash_password("pw"))
    with pytest.raises(Exception, match="unique"):
        users_repo.create("Other", email, auth.hash_password("pw"))


def test_password_hash_not_stored_plaintext() -> None:
    email = _email()
    users_repo.create("Dee", email, auth.hash_password("secret"))
    fetched = users_repo.get_by_email(email)
    assert fetched is not None
    assert fetched.password_hash != "secret"
    assert auth.verify_password("secret", fetched.password_hash)
