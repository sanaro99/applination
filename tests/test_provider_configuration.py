"""Provider credentials and model IDs can be edited without exposing secrets."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import requests
import pytest
from openai import BadRequestError
from openai.resources.responses import Responses
import yaml
from fastapi.testclient import TestClient

import server.db as db
from server.user_paths import UserPaths
from server.user_secrets import get_secret

from .conftest import make_engine, register


def test_model_and_key_are_saved_for_one_user(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as alice, TestClient(app) as bob:
        register(alice, "alice@example.com")
        register(bob, "bob@example.com")
        result = alice.put("/api/providers/openai/configuration", json={
            "model": "gpt-user-selected", "api_key": "sk-alice-private",
        })
        assert result.status_code == 200, result.text
        alice_config = yaml.safe_load(UserPaths(user_id=1).config_path.read_text(encoding="utf-8"))
        assert alice_config["llm"]["openai"]["model"] == "gpt-user-selected"
        assert alice_config["llm"]["openai"]["api_key"] == ""
        assert get_secret(1, "llm.openai.api_key") == "sk-alice-private"
        assert "sk-alice-private" not in alice.get("/api/providers").text
        assert next(p for p in alice.get("/api/providers").json() if p["name"] == "openai")["model"] == "gpt-user-selected"
        assert next(p for p in bob.get("/api/providers").json() if p["name"] == "openai")["model"] != "gpt-user-selected"

        # Editing only the model keeps the encrypted key and is used by Test.
        assert alice.put("/api/providers/openai/configuration", json={"model": "gpt-another"}).status_code == 200
        assert get_secret(1, "llm.openai.api_key") == "sk-alice-private"
        import src.providers
        seen = {}
        budgets = []

        class FakeProvider:
            def text_call(self, *_args, **kwargs):
                budgets.append(kwargs["max_tokens"])
                return "ok"

        def fake_provider(name, llm, *, user_id):
            assert user_id == 1
            seen.update({"name": name, "model": llm[name]["model"], "key": llm[name]["api_key"]})
            return FakeProvider()

        monkeypatch.setattr(src.providers, "get_provider", fake_provider)
        assert alice.post("/api/providers/test", json={"provider": "openai"}).json()["ok"] is True
        assert seen == {"name": "openai", "model": "gpt-another", "key": "sk-alice-private"}
        assert budgets[0] >= 16


def test_openai_connection_check_meets_responses_token_minimum(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    calls = []

    def create_response(self, **kwargs):
        calls.append(kwargs)
        budget = kwargs["max_output_tokens"]
        if budget < 16:
            error = {"error": {
                "message": "Invalid 'max_output_tokens': integer below minimum value. "
                           f"Expected a value >= 16, but got {budget} instead.",
                "type": "invalid_request_error",
                "param": "max_output_tokens",
                "code": "integer_below_min_value",
            }}
            raise BadRequestError(
                str(error),
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
                ),
                body=error,
            )
        return SimpleNamespace(output_text="ok")

    # Keep the endpoint, stored credentials, factory and adapter real; replace
    # only the SDK request with the API's documented minimum-token contract.
    monkeypatch.setattr(Responses, "create", create_response)
    with TestClient(app) as client:
        register(client, "alice@example.com")
        configured = client.put("/api/providers/openai/configuration", json={
            "model": "gpt-5.6-luna", "api_key": "sk-test-private",
        })
        assert configured.status_code == 200, configured.text

        result = client.post("/api/providers/test", json={"provider": "openai"})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["ok"] is True, body["error"]
        assert body["sample"] == "ok"
        assert body["model"] == "gpt-5.6-luna"
        assert len(calls) == 1
        assert calls[0]["model"] == "gpt-5.6-luna"
        assert calls[0]["max_output_tokens"] >= 16


def test_model_list_uses_temporary_or_stored_key(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "gpt-current"}, {"id": "gpt-next"}]}

    def fake_get(url, *, headers, params, timeout, allow_redirects):
        calls.append((url, headers, params, timeout, allow_redirects))
        return Response()

    monkeypatch.setattr(provider_models.requests, "get", fake_get)
    with TestClient(app) as client:
        register(client, "alice@example.com")
        r = client.post("/api/providers/openai/models", json={"api_key": "sk-temporary"})
        assert r.status_code == 200, r.text
        assert r.json() == {"models": ["gpt-current", "gpt-next"]}
        assert calls[-1][0] == "https://api.openai.com/v1/models"
        assert calls[-1][1]["Authorization"] == "Bearer sk-temporary"
        assert get_secret(1, "llm.openai.api_key") is None

        client.put("/api/providers/openai/configuration", json={"model": "gpt-current", "api_key": "sk-stored"})
        assert client.post("/api/providers/openai/models", json={}).status_code == 200
        assert calls[-1][1]["Authorization"] == "Bearer sk-stored"


def test_model_list_filters_gemini_to_generate_content(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [
                {"name": "models/gemini-text", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-only", "supportedGenerationMethods": ["embedContent"]},
            ]}

    monkeypatch.setattr(provider_models.requests, "get", lambda *a, **kw: Response())
    with TestClient(app) as client:
        register(client, "alice@example.com")
        r = client.post("/api/providers/gemini/models", json={"api_key": "temporary"})
        assert r.status_code == 200, r.text
        assert r.json() == {"models": ["gemini-text"]}


def test_invalid_model_and_missing_auth_do_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as client:
        assert client.put("/api/providers/openai/configuration", json={"model": "valid"}).status_code == 401
        assert client.post("/api/providers/openai/models", json={"api_key": "private"}).status_code == 401
        register(client, "alice@example.com")
        before = UserPaths(user_id=1).ensure().config_path.read_text(encoding="utf-8")
        assert client.put("/api/providers/openai/configuration", json={"model": "two words"}).status_code == 400
        assert client.put("/api/providers/unknown/configuration", json={"model": "one"}).status_code == 400
        assert UserPaths(user_id=1).config_path.read_text(encoding="utf-8") == before


def test_ollama_lists_only_server_local_models(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "llama-local:latest"}]}

    urls = []
    def fake_get(url, **kwargs):
        urls.append(url)
        return Response()

    monkeypatch.setattr(provider_models.requests, "get", fake_get)
    with TestClient(app) as client:
        register(client, "alice@example.com")
        text = client.get("/api/config").json()["text"]
        config = yaml.safe_load(text)
        config["llm"]["ollama"]["transport"] = "direct"
        assert client.put("/api/config", json={"text": yaml.safe_dump(config)}).status_code == 200
        r = client.post("/api/providers/ollama/models", json={})
        assert r.status_code == 200, r.text
        assert r.json() == {"models": ["llama-local:latest"]}
        assert urls == ["http://localhost:11434/api/tags"]

        config["llm"]["ollama"]["base_url"] = "http://example.com"
        assert client.put("/api/config", json={"text": yaml.safe_dump(config)}).status_code == 200
        blocked = client.post("/api/providers/ollama/models", json={})
        assert blocked.status_code == 502
        assert urls == ["http://localhost:11434/api/tags"]


def test_cloudflare_model_list_uses_account_and_token(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    account_id = "a" * 32
    pages = []

    class Response:
        status_code = 200

        def __init__(self, page):
            self.page = page

        def raise_for_status(self):
            pass

        def json(self):
            return {"result": [{"name": f"@cf/model-{self.page}"}],
                    "result_info": {"total_pages": 2}}

    def fake_get(url, *, headers, params, **kwargs):
        pages.append((url, headers, params.copy()))
        return Response(params.get("page", 1))

    monkeypatch.setattr(provider_models.requests, "get", fake_get)
    with TestClient(app) as client:
        register(client, "alice@example.com")
        assert client.put("/api/providers/cloudflare/configuration", json={
            "model": "@cf/model-1", "api_key": "private-token", "account_id": account_id,
        }).status_code == 200
        r = client.post("/api/providers/cloudflare/models", json={})
        assert r.status_code == 200, r.text
        assert r.json() == {"models": ["@cf/model-1", "@cf/model-2"]}
        assert len(pages) == 2
        assert all(account_id in call[0] for call in pages)
        assert all(call[1]["Authorization"] == "Bearer private-token" for call in pages)
        assert get_secret(1, "llm.cloudflare.api_token") == "private-token"
        assert "private-token" not in client.get("/api/providers").text


def test_ollama_worker_model_list_does_not_contact_hosted_localhost(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import local_ollama, provider_models

    owners = []

    def worker_models(user_id):
        owners.append(user_id)
        return ["llama-on-my-computer:latest"]

    def no_hosted_ollama(*args, **kwargs):
        raise requests.ConnectionError("No Ollama is installed on the hosted API server")

    monkeypatch.setattr(local_ollama, "worker_models", worker_models, raising=False)
    monkeypatch.setattr(provider_models.requests, "get", no_hosted_ollama)
    with TestClient(app) as client:
        owner_id = register(client, "worker-models@example.com")["id"]
        assert client.put("/api/onboarding/provider", json={"provider": "ollama"}).status_code == 200
        result = client.post("/api/providers/ollama/models", json={})
        assert result.status_code == 200, result.text
        assert result.json()["models"] == ["llama-on-my-computer:latest"]
        assert owners == [owner_id]


@pytest.mark.parametrize("name", ["openai", "claude", "gemini", "deepseek", "mistral", "nim", "groq", "cloudflare", "openrouter"])
def test_model_catalog_can_load_before_entering_credentials(name, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    def public_catalog(provider):
        assert provider == name
        return ["public-text-model"]

    monkeypatch.setattr(provider_models, "public_models", public_catalog, raising=False)
    with TestClient(app) as client:
        register(client, "catalog@example.com")
        result = client.post(f"/api/providers/{name}/models", json={})
        assert result.status_code == 200, result.text
        assert result.json()["models"] == ["public-text-model"]


def test_catalog_browsing_ignores_stored_keys_and_cloudflare_account_requirements(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import provider_models

    def never_use_credentials(*args, **kwargs):
        raise AssertionError("Catalog browsing must not send account credentials")

    monkeypatch.setattr(provider_models, "discover_models", never_use_credentials)
    monkeypatch.setattr(provider_models, "public_models", lambda name: [f"{name}-text-model"])
    with TestClient(app) as client:
        register(client, "catalog-key@example.com")
        assert client.put("/api/providers/openai/configuration", json={
            "model": "gpt-current", "api_key": "sk-stored-private",
        }).status_code == 200
        for name in ["openai", "cloudflare"]:
            result = client.post(f"/api/providers/{name}/models", json={"catalog": True})
            assert result.status_code == 200, result.text
            assert result.json() == {"models": [f"{name}-text-model"], "source": "catalog"}
        assert get_secret(1, "llm.openai.api_key") == "sk-stored-private"
