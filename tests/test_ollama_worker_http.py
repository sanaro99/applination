"""Exercise the worker's urllib transport through a browser-integrity check."""
import io
import json
from email.message import Message
from urllib.error import HTTPError
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

import pytest

import local_ollama_worker as worker


@pytest.mark.parametrize("path,body", [
    ("/api/local-ollama/worker/ping", None),
    ("/api/local-ollama/worker/models", {"models": ["llama3.2:latest"]}),
])
def test_worker_identifies_itself_to_browser_integrity_check(monkeypatch, path, body):
    requests = []

    class IntegrityCheck(BaseHandler):
        # Run before urllib's network handlers while retaining its header handling.
        handler_order = 400

        def https_open(self, request):
            requests.append(request)
            user_agent = request.get_header("User-agent", "")
            if not user_agent.startswith("Applination-Ollama-Worker/"):
                raise HTTPError(
                    request.full_url, 403, "Forbidden", Message(),
                    io.BytesIO(b"The site owner has blocked access based on your browser's signature."),
                )
            response = addinfourl(io.BytesIO(b'{"ok": true}'), Message(), request.full_url, 200)
            response.msg = "OK"
            return response

    monkeypatch.setattr(worker, "_opener", build_opener(worker._NoRedirect, IntegrityCheck()))
    result = worker._request(
        f"https://applination.example{path}", token="test-worker-credential", body=body,
    )

    assert result == {"ok": True}
    assert len(requests) == 1
    request = requests[0]
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Authorization") == "Bearer test-worker-credential"
    assert request.get_method() == ("GET" if body is None else "POST")
    if body is not None:
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == body


def test_redirect_never_forwards_the_worker_credential(monkeypatch):
    requests = []

    class Redirect(BaseHandler):
        handler_order = 400

        def https_open(self, request):
            requests.append(request.full_url)
            headers = Message()
            headers["Location"] = "https://attacker.example/collect"
            response = addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
            response.msg = "Found"
            return response

    monkeypatch.setattr(worker, "_opener", build_opener(worker._NoRedirect, Redirect()))
    with pytest.raises(RuntimeError, match="HTTP 302"):
        worker._request("https://applination.example/api/local-ollama/worker/ping", token="private-worker-credential")
    assert requests == ["https://applination.example/api/local-ollama/worker/ping"]


def test_local_prompts_use_the_separate_loopback_transport(monkeypatch):
    requests = []

    class LocalTransport:
        def open(self, request, timeout):
            requests.append(request)
            return io.BytesIO(b'{"message": {"content": "local answer"}}')

    class RemoteTransport:
        def open(self, *args, **kwargs):
            raise AssertionError("Local prompt reached the external transport")

    monkeypatch.setattr(worker, "_local_opener", LocalTransport())
    monkeypatch.setattr(worker, "_opener", RemoteTransport())
    result = worker._request("http://127.0.0.1:11434/api/chat", body={"prompt": "private résumé"})
    assert result["message"]["content"] == "local answer"
    assert requests[0].get_header("Authorization") is None
    assert json.loads(requests[0].data) == {"prompt": "private résumé"}


def test_oversized_server_response_is_not_parsed(monkeypatch):
    class OversizedTransport:
        def open(self, *args, **kwargs):
            return io.BytesIO(b" " * (worker.MAX_RESPONSE_BYTES + 1))

    monkeypatch.setattr(worker, "_opener", OversizedTransport())
    with pytest.raises(RuntimeError, match="size limit"):
        worker._request("https://applination.example/api/local-ollama/worker/ping")
