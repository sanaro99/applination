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
