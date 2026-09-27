"""Run Applination model calls on this computer's Ollama installation.

Python 3.10+ and Ollama are the only requirements. Download this file from
Applination, run it, and paste the one-time connection key from Config.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_SITE = "https://applination.sanchitarora.me"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never forward the worker credential to another origin.


_opener = build_opener(_NoRedirect)


def _config_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "Applination" / "ollama-worker.json"


def _check_site(site: str) -> str:
    parsed = urlsplit(site.rstrip("/"))
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("The Applination address must use HTTPS (except localhost development).")
    if (not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Use the Applination site origin, without a path or credentials.")
    return site.rstrip("/")


def _request(url: str, *, token: str = "", body: dict | None = None,
             timeout: int = 30) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with _opener.open(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, TypeError):
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _local_models(ollama_url: str) -> set[str]:
    data = _request(f"{ollama_url}/api/tags", timeout=10)
    return {str(row.get("name", "")) for row in data.get("models", [])}


def _generate(ollama_url: str, payload: dict) -> str:
    model = str(payload["model"])
    installed = _local_models(ollama_url)
    if model not in installed and f"{model}:latest" not in installed:
        raise RuntimeError(f"Model {model!r} is not installed locally. Run: ollama pull {model}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": payload["system"]},
            {"role": "user", "content": payload["user"]},
        ],
        "stream": False,
        "options": {"num_predict": int(payload["max_tokens"]), "temperature": 0.4},
    }
    if payload.get("format_json"):
        body["format"] = "json"
    answer = _request(f"{ollama_url}/api/chat", body=body, timeout=600)
    return str((answer.get("message") or {}).get("content") or "").strip()


def _heartbeat(site: str, token: str, task_id: str, lease: str,
               stop: threading.Event) -> None:
    while not stop.wait(20):
        try:
            _request(f"{site}/api/local-ollama/worker/tasks/{task_id}/heartbeat",
                     token=token, body={"lease": lease})
        except (RuntimeError, URLError, TimeoutError) as exc:
            print(f"Connection heartbeat failed: {exc}", file=sys.stderr)


def _run_task(site: str, token: str, ollama_url: str, task: dict) -> None:
    task_id, lease = task["id"], task["lease"]
    stop = threading.Event()
    watcher = threading.Thread(target=_heartbeat, args=(site, token, task_id, lease, stop), daemon=True)
    watcher.start()
    try:
        print(f"Running {task['payload']['model']} locally…", flush=True)
        try:
            content = _generate(ollama_url, task["payload"])
            result = {"lease": lease, "content": content}
        except Exception as exc:
            result = {"lease": lease, "error": str(exc)[:1000]}
        _request(f"{site}/api/local-ollama/worker/tasks/{task_id}/result",
                 token=token, body=result)
        print("Model request finished.", flush=True)
    finally:
        stop.set()
        watcher.join(timeout=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect your local Ollama to Applination")
    parser.add_argument("--site", default=DEFAULT_SITE, help="Applination site origin")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA, help="Local Ollama address")
    parser.add_argument("--reset", action="store_true", help="Paste a new connection key")
    args = parser.parse_args()
    try:
        site = _check_site(args.site)
        ollama_url = args.ollama_url.rstrip("/")
        parsed = urlsplit(ollama_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise ValueError("The worker only connects to Ollama on this computer (localhost).")
        models = _local_models(ollama_url)
        print(f"Ollama is running. {len(models)} local model(s) installed.")
    except (ValueError, RuntimeError, URLError, TimeoutError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1

    path = _config_path()
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    token = saved.get("token", "") if saved.get("site") == site and not args.reset else ""
    new_token = not token
    if not token:
        print("Create a local Ollama connection key in Applination Config.")
        token = input("Paste the connection key: ").strip()
        if not token:
            return 1
    try:
        _request(f"{site}/api/local-ollama/worker/ping", token=token, timeout=15)
    except (RuntimeError, URLError, TimeoutError) as exc:
        print(f"Could not connect to Applination: {exc}", file=sys.stderr)
        return 1
    if new_token:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as config_file:
            json.dump({"site": site, "token": token}, config_file)
    print("Connected. Keep this window open while Applination uses your model. Ctrl+C to stop.")
    while True:
        try:
            response = _request(f"{site}/api/local-ollama/worker/next", token=token, timeout=25)
            task = response.get("task")
            if task:
                _run_task(site, token, ollama_url, task)
        except KeyboardInterrupt:
            print("Stopped.")
            return 0
        except RuntimeError as exc:
            if str(exc).startswith("HTTP 401:"):
                print("Connection revoked. Create a new key in Applination Config and run this file with --reset.", file=sys.stderr)
                return 1
            print(f"Connection problem: {exc}", file=sys.stderr)
            time.sleep(3)
        except (URLError, TimeoutError) as exc:
            print(f"Connection problem: {exc}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
