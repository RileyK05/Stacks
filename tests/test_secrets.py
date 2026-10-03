import keyring
import pytest
from fastapi.testclient import TestClient
from src.backend.common import providers, secrets

REAL_GET = secrets.get_api_key
REAL_SET = secrets.set_api_key
REAL_DELETE = secrets.delete_api_key


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_unavailable_keychain_is_not_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    def unavailable(*args: object) -> None:
        raise RuntimeError("backend locked")

    monkeypatch.setattr(keyring, "get_password", unavailable)
    monkeypatch.setattr(keyring, "set_password", unavailable)
    monkeypatch.setattr(keyring, "delete_password", unavailable)
    monkeypatch.setattr(secrets, "get_api_key", REAL_GET)
    with pytest.raises(
        secrets.CredentialStoreUnavailableError, match="Unlock or enable"
    ):
        if operation == "get":
            REAL_GET("test")
        elif operation == "set":
            REAL_SET("test", "not-a-real-key")
        else:
            REAL_DELETE("test")


def test_credential_error_returns_actionable_http_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object) -> None:
        raise secrets.CredentialStoreUnavailableError()

    monkeypatch.setattr(secrets, "get_api_key", unavailable)
    response = client.get("/settings/providers")
    assert response.status_code == 503
    assert "credential store" in response.json()["detail"]


def test_failed_key_deletion_keeps_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = providers.add_connection("openai", name="My provider")

    def unavailable(*args: object) -> None:
        raise secrets.CredentialStoreUnavailableError()

    monkeypatch.setattr(secrets, "delete_api_key", unavailable)
    with pytest.raises(secrets.CredentialStoreUnavailableError):
        providers.remove_connection(connection.id)
    assert providers.get_connection(connection.id).id == connection.id
