from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from src.backend.artifacts import edit
from src.backend.common import config, provider, providers, secrets, storage, usage_repo
from src.backend.common.db import connection
from src.backend.office_addin import host, windows
from src.backend.runtime import downloads, server, supervisor, user_models
from tests.conftest import configure_test_provider
from tests.test_artifacts import _course
from tests.test_course_archive import _course_with_sources
from tests.test_providers import OK_BODY, REAL_CALL, _capture_post, _endpoint, _Response
from tests.test_runtime import _fake_launch
from tests.test_sources_api import _course as source_course
from tests.test_sources_api import _upload
from tests.test_tutor_api import _ask, _seeded_course

REAL_DOTENV_LOADER = config._load_dotenv


def test_dotenv_preserves_literal_quotes_and_reads_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "DOTENV_QUOTED_EXPORT='C:\\path\\'\nDOTENV_QUOTED_LITERAL=\"'literal'\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DOTENV_QUOTED_EXPORT", raising=False)
    monkeypatch.delenv("DOTENV_QUOTED_LITERAL", raising=False)
    reads: list[Path] = []

    def load(path: Path) -> None:
        reads.append(path)
        REAL_DOTENV_LOADER(path)

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "_load_dotenv", load)
    config._load_project_dotenv.cache_clear()
    try:
        config.get_settings()
        config.get_settings()
        assert reads == [path]
        assert config.os.environ["DOTENV_QUOTED_EXPORT"] == "C:\\path\\"
        assert config.os.environ["DOTENV_QUOTED_LITERAL"] == "'literal'"
        monkeypatch.setenv("APP_OFFICE_PORT", "47832")
        assert config.get_settings().office_port == 47832
    finally:
        config._load_project_dotenv.cache_clear()


@pytest.mark.parametrize("port", ["not-a-number", "80", "65536"])
def test_bad_office_port_explains_the_setting(
    monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("APP_OFFICE_PORT", port)
    with pytest.raises(config.ConfigurationError, match="APP_OFFICE_PORT"):
        config.get_settings()


def test_office_disconnect_failure_is_actionable_in_the_api(
    client, monkeypatch
) -> None:
    from src.backend.office_addin import service

    def failed():
        raise service.OfficeSetupError("Host did not stop; files and trust were kept.")

    monkeypatch.setattr(service, "disconnect", failed)
    response = client.post("/office/disconnect")
    assert response.status_code == 409
    assert "files and trust were kept" in response.json()["detail"]


@pytest.mark.parametrize(
    "error",
    [
        downloads.DownloadError("offline"),
        zipfile.BadZipFile("bad archive"),
        httpx.ConnectError("offline"),
    ],
)
def test_failed_runtime_install_leaves_an_actionable_terminal_state(
    monkeypatch, tmp_path, error
):
    _fake_launch(monkeypatch, tmp_path, {})
    attempted = []

    def fail(key):
        attempted.append(key)
        raise error

    monkeypatch.setattr(server, "ensure_binary", fail)
    manager = server.LlamaServer()
    manager._job = None
    with pytest.raises(server.RuntimeUnavailableError):
        manager.start("minicpm5-2b")
    assert attempted == ["windows-x64-vulkan", "windows-x64-cpu"]
    assert manager.status().state == "failed"
    assert manager.status().error


def test_concurrent_local_requests_share_a_healthy_model(monkeypatch, tmp_path):
    commands = _fake_launch(monkeypatch, tmp_path, {"windows-x64-vulkan": None})
    manager = server.LlamaServer()
    manager._job = None
    ready = threading.Barrier(3)
    failures = []

    def start():
        ready.wait()
        try:
            manager.start("minicpm5-2b")
        except Exception as err:
            failures.append(err)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert failures == []
    assert len(commands) == 1
    assert manager.status().state == "running"
    manager.stop()


def test_supervisor_survives_a_transient_tick_failure(monkeypatch):
    calls = []
    stopped = []

    async def scenario():
        stop = asyncio.Event()

        class Manager:
            def check_and_restart(self):
                calls.append("tick")
                if len(calls) == 1:
                    raise sqlite3.OperationalError("database is busy")
                asyncio_loop.call_soon_threadsafe(stop.set)

            def stop(self, *, forget: bool = True) -> None:
                stopped.append(forget)

        asyncio_loop = asyncio.get_running_loop()
        monkeypatch.setattr(supervisor, "get_server", lambda: Manager())
        monkeypatch.setattr(supervisor, "cleanup_stale_server", lambda: None)
        monkeypatch.setattr(supervisor.settings_repo, "get_setting", lambda key: None)
        monkeypatch.setattr(supervisor, "CHECK_INTERVAL_SECONDS", 0.001)
        await asyncio.wait_for(supervisor.run_forever(stop), timeout=5)

    asyncio.run(scenario())
    assert calls == ["tick", "tick"]
    assert stopped == [False]


def test_null_usage_does_not_discard_a_successful_model_response(monkeypatch):
    body = {**OK_BODY, "usage": {"prompt_tokens": None, "completion_tokens": None}}
    _capture_post(monkeypatch, _Response(200, body))
    text, input_tokens, output_tokens = REAL_CALL(
        "tutor_answer", _endpoint(), "question"
    )
    assert text
    assert input_tokens == output_tokens == 0


def test_redirected_provider_reports_the_configuration_issue(monkeypatch):
    _capture_post(monkeypatch, _Response(307, {}))
    with pytest.raises(provider.ProviderRequestRejectedError, match="redirected"):
        REAL_CALL("tutor_answer", _endpoint(), "question")


def test_provider_follows_a_valid_redirect_without_losing_the_request(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(307, headers={"Location": "/final/chat/completions"})
        return httpx.Response(200, json=OK_BODY)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(httpx, "post", client.post)
        text, _, _ = REAL_CALL(
            "tutor_answer",
            _endpoint(base_url="https://provider.test/v1", api_key="fixture-key"),
            "student question",
        )
    assert text
    assert [request.method for request in seen] == ["POST", "POST"]
    assert json.loads(seen[1].content)["messages"][0]["content"] == "student question"
    assert seen[1].headers["Authorization"] == "Bearer fixture-key"


def test_local_runtime_rejects_a_foreign_listener_before_launch(monkeypatch, tmp_path):
    commands = _fake_launch(monkeypatch, tmp_path, {"windows-x64-vulkan": None})

    class OccupiedPort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, address):
            raise OSError("address in use")

    monkeypatch.setattr(server.socket, "socket", lambda *args: OccupiedPort())
    manager = server.LlamaServer()
    manager._job = None
    with pytest.raises(server.RuntimeUnavailableError, match="port .* already in use"):
        manager.start("minicpm5-2b")
    assert commands == []
    assert manager.status().state == "failed"


def test_blank_key_cannot_replace_an_existing_credential(client, _memory_keyring):
    assert (
        client.put("/settings/keys/openrouter", json={"key": "existing"}).status_code
        == 204
    )
    response = client.put("/settings/keys/openrouter", json={"key": " \t "})
    assert response.status_code == 422
    assert _memory_keyring["openrouter"] == "existing"


def test_keyring_failure_does_not_publish_an_unusable_connection(client, monkeypatch):
    def fail(*args):
        raise secrets.CredentialStoreUnavailableError()

    monkeypatch.setattr(secrets, "set_api_key", fail)
    response = client.post(
        "/settings/connections", json={"preset": "openrouter", "key": "new-key"}
    )
    assert response.status_code == 503
    assert [item.id for item in providers.list_connections()] == ["local"]


def test_failed_connection_removal_restores_its_credential(
    monkeypatch, _memory_keyring
):
    saved = providers.add_connection("openrouter", api_key="original")
    real_connection = providers.db_connection

    @contextmanager
    def failing_commit():
        with real_connection() as conn:

            class Transaction:
                execute = conn.execute

                def commit(self):
                    raise sqlite3.OperationalError("busy commit")

            yield Transaction()

    with monkeypatch.context() as scoped:
        scoped.setattr(providers, "db_connection", failing_commit)
        with pytest.raises(sqlite3.OperationalError, match="busy commit"):
            providers.remove_connection(saved.id)
    assert providers.get_connection(saved.id) is not None
    assert _memory_keyring[saved.id] == "original"


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
def test_viewer_reports_a_missing_stored_source(client, encoding):
    course_id = source_course(client)
    uploaded = _upload(client, course_id, "notes.txt", b"readable notes " * 500).json()
    source_id = UUID(uploaded["source_id"])
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET stored_encoding = ? WHERE source_id = ?",
            (encoding, source_id),
        )
        conn.commit()
    storage.source_disk_path(course_id, source_id).unlink()
    response = client.get(f"/courses/{course_id}/sources/{source_id}/content")
    assert response.status_code == 410
    assert "missing" in response.json()["detail"]


def test_viewer_reports_corrupt_stored_source(client):
    course_id = source_course(client)
    uploaded = _upload(client, course_id, "notes.txt", b"readable notes " * 500).json()
    source_id = UUID(uploaded["source_id"])
    storage.source_disk_path(course_id, source_id).write_bytes(b"not a gzip stream")
    response = client.get(f"/courses/{course_id}/sources/{source_id}/content")
    assert response.status_code == 422


def test_overlong_saved_quiz_returns_validation_error(client):
    from src.backend.common import conversations_repo

    course_id, _ = _course(client)
    conversation = conversations_repo.create(UUID(course_id))
    with connection() as conn:
        _, message = conversations_repo.add_turn(
            conn,
            conversation.conversation_id,
            question="Quiz me",
            answer="Saved quiz",
            trace_id=None,
            payload={
                "workspace": [
                    {
                        "type": "quiz",
                        "questions": [
                            {
                                "prompt": "x" * 5001,
                                "options": ["a", "b"],
                                "answer": 0,
                                "explanation": "",
                                "sources": [1],
                            }
                        ],
                    }
                ]
            },
        )
        conn.commit()
    response = client.post(
        f"/courses/{course_id}/practice",
        json={
            "message_id": str(message.message_id),
        },
    )
    assert response.status_code == 422


def test_practice_budget_error_is_a_designed_response(client, monkeypatch):
    from src.backend.student_model import practice_support

    course_id, _ = _course(client)

    def exhausted(*args, **kwargs):
        raise usage_repo.BudgetExceededError(10, 10)

    monkeypatch.setattr(practice_support, "help_with", exhausted)
    from uuid import uuid4

    response = client.post(
        f"/courses/{course_id}/practice/{uuid4()}/questions/0/help",
        json={"run_id": str(uuid4()), "kind": "hint"},
    )
    assert response.status_code == 402


@pytest.mark.parametrize(
    "bad",
    [
        {"cited_chunk_ids": [None]},
        {"cited_chunk_ids": ["not-a-uuid"]},
        {"cited_chunk_ids": [], "citation_markers": {}},
    ],
)
def test_malformed_trace_is_not_a_server_crash(client, monkeypatch, bad):
    course_id = _seeded_course(client)
    configure_test_provider(monkeypatch, "linearity [1]")
    answer = _ask(client, course_id).json()
    with connection() as conn:
        conn.execute(
            "UPDATE retrieval_traces SET retrieved_chunk_ids = ? WHERE trace_id = ?",
            (json.dumps(bad), answer["trace_id"]),
        )
        conn.commit()
    response = client.get(f"/courses/{course_id}/traces/{answer['trace_id']}/citations")
    assert response.status_code == 422


def test_an_uncited_trace_does_not_show_all_retrieved_material_as_evidence(
    client, monkeypatch
):
    course_id = _seeded_course(client)
    configure_test_provider(monkeypatch, "linearity [1]")
    answer = _ask(client, course_id).json()
    with connection() as conn:
        conn.execute(
            "UPDATE retrieval_traces SET retrieved_chunk_ids = ? WHERE trace_id = ?",
            (
                json.dumps({"chunk_ids": answer["chunk_ids"], "cited_chunk_ids": []}),
                answer["trace_id"],
            ),
        )
        conn.commit()
    response = client.get(f"/courses/{course_id}/traces/{answer['trace_id']}/citations")
    assert response.status_code == 200
    assert response.json() == []


def test_legacy_source_hash_is_recomputed_from_exported_bytes(client):
    course_id = _course_with_sources(client)
    with connection() as conn:
        conn.execute(
            "UPDATE sources SET file_hash = NULL WHERE course_id = ?", (course_id,)
        )
        conn.commit()
    response = client.post(f"/courses/{course_id}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(Path(response.json()["path"])) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for source in manifest["sources"]:
            assert (
                source["sha256"]
                == hashlib.sha256(archive.read(source["path"])).hexdigest()
            )


def test_slide_proposal_preserves_existing_copied_student_lines():
    body = (
        "Original discussion of the historical political coalition\n"
        "Another long line on collective organization and participation\n"
        "Final long line on national ancestry and local mobilization"
    )
    shown = {"slides": [{"title": "Student slide", "body": body, "notes": ""}]}
    proposed = {"slides": [{"title": "Student slide", "body": body, "notes": ""}]}
    stripped = edit._strip_echo("slides", proposed, shown, [body])
    assert stripped["slides"][0]["body"] == body
    attributed, uncited = edit._attribute("slides", proposed, shown, [body])
    assert attributed["slides"][0]["body"] == body
    assert uncited == 0


def test_malformed_model_size_returns_a_readable_add_model_error():
    link = user_models.parse_link("https://huggingface.co/org/model")
    with pytest.raises(user_models.AddModelError, match="invalid size"):
        user_models.gguf_files(
            link, http_get=lambda _: [{"path": "model.gguf", "lfs": {"oid": "a" * 64}}]
        )


def test_office_host_cleans_bound_sockets_when_configuration_fails(
    monkeypatch, tmp_path
):
    from fastapi import FastAPI

    closed = []

    class Socket:
        def close(self):
            closed.append(True)

    def bad_config(*args, **kwargs):
        raise ValueError("invalid certificate configuration")

    monkeypatch.setattr(host, "_bind", lambda port: [Socket()])
    monkeypatch.setattr(host.uvicorn, "Config", bad_config)
    manager = host.AddinHost()
    with pytest.raises(ValueError, match="invalid certificate"):
        manager.start(FastAPI(), port=47831, cert=tmp_path / "ca", key=tmp_path / "key")
    assert closed == [True]
    assert not manager.running


def test_windows_trust_timeout_is_actionable_and_bounded(monkeypatch, tmp_path):
    def timeout(arguments, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(arguments, 30)

    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.subprocess, "run", timeout)
    with pytest.raises(OSError, match="timed out"):
        windows.trust(tmp_path / "ca.pem")
    with pytest.raises(OSError, match="timed out"):
        windows.untrust("fingerprint")


def test_freeze_names_support_version_exclusions_and_direct_urls(monkeypatch, tmp_path):
    from scripts import freeze_constraints

    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        '[project]\ndependencies = ["foo!=1.0", "bar <= 2", "Baz[extra]===3", '
        '"alpha @ https://example.test/alpha.whl", "FOO>=2"]',
        encoding="utf-8",
    )
    monkeypatch.setattr(freeze_constraints, "PYPROJECT", declaration)
    assert freeze_constraints._requirement_names() == ["foo", "bar", "Baz", "alpha"]


@pytest.mark.parametrize(
    "documents",
    [
        [],
        [{"id": "empty", "text": "content", "checks": []}],
        [{"id": "drift", "text": "content", "checks": [{"evidence": "missing"}]}],
        [{"id": "duplicate", "text": "term term", "checks": [{"evidence": "term"}]}],
    ],
)
def test_invalid_passage_eval_cases_fail_before_model_work(documents):
    from scripts.eval_passages import _validate_cases

    with pytest.raises(ValueError):
        _validate_cases({"documents": documents})
