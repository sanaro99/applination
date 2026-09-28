"""Run Applination model calls on this computer's Ollama installation.

Python 3.10+ and Ollama are the only requirements. Download this file from
Applination, run it, and paste the one-time connection key from Config.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import threading
import time
import tempfile
import stat
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_SITE = "https://applination.sanchitarora.me"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never forward the worker credential to another origin.


_opener = build_opener(_NoRedirect)
_local_opener = build_opener(_NoRedirect, ProxyHandler({}))
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _config_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "Applination" / "ollama-worker.json"


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """Windows encrypts the session for this OS user; never fall back to plaintext."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN, without CRYPTPROTECT_LOCAL_MACHINE.
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(buffer, 0, len(buffer))
        if output.data:
            ctypes.memset(output.data, 0, output.size)
            kernel.LocalFree(output.data)


def _load_session(path: Path, site: str) -> dict:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("version") != 2 or saved.get("site") != site:
            return {}  # Never reuse legacy plaintext keys.
        expires = datetime.fromisoformat(saved["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            return {}
        if os.name == "nt":
            token = _dpapi(base64.b64decode(saved["protected_token"], validate=True), decrypt=True).decode("utf-8")
        else:
            if stat.S_IMODE(path.stat().st_mode) & 0o077 or path.stat().st_uid != os.getuid():
                return {}
            token = saved["token"]
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            return {}
        return {"token": token, "expires_at": saved["expires_at"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _save_session(path: Path, site: str, token: str, expires_at: str) -> None:
    saved = {"version": 2, "site": site, "expires_at": expires_at}
    if os.name == "nt":
        saved["protected_token"] = base64.b64encode(_dpapi(token.encode("utf-8"))).decode("ascii")
    else:
        saved["token"] = token
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix="ollama-session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as config_file:
            json.dump(saved, config_file)
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _pair(site: str) -> dict:
    print(f"Connecting to {site}")
    print("Create a one-time pairing code in Applination Config. It expires in 5 minutes.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            code = getpass.getpass("Paste the pairing code (hidden): ").strip()
    except getpass.GetPassWarning:
        raise RuntimeError("Run this worker in an interactive terminal that can hide the pairing code.") from None
    if not code:
        raise RuntimeError("No pairing code entered")
    paired = _request(f"{site}/api/local-ollama/worker/connect", token=code, body={}, timeout=15)
    token = paired.get("token", "")
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise RuntimeError("Applination returned an invalid worker session")
    verification = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    print(f"Verification code: {verification}", flush=True)
    print("In Config, approve ONLY the worker with this matching code. Waiting for approval…", flush=True)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        approval = _request(f"{site}/api/local-ollama/worker/approval", token=token, timeout=15)
        if approval.get("approved") is True:
            expires = approval.get("expires_at")
            if not isinstance(expires, str):
                raise RuntimeError("Applination returned an invalid session expiration")
            return {"token": token, "expires_at": expires}
        time.sleep(5)
    raise RuntimeError("Approval expired. Create a new pairing code and try again.")


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
    # Identify the worker explicitly; edge integrity checks can reject Python's default client.
    headers = {"Accept": "application/json", "User-Agent": "Applination-Ollama-Worker/1.0"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        opener = _local_opener if urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"} else _opener
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Server response exceeds the worker size limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise RuntimeError("Server returned an invalid response")
            return result
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, TypeError):
            if detail.lstrip().startswith("<"):
                detail = "Applination is temporarily unavailable. Retry in a moment."
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _remote_model(name: str, metadata: dict) -> bool:
    tag = name.rsplit(":", 1)[-1].casefold()
    return bool(metadata.get("remote_host") or metadata.get("remote_model")
                or tag == "cloud" or tag.endswith("-cloud"))


def _local_models(ollama_url: str) -> set[str]:
    data = _request(f"{ollama_url}/api/tags", timeout=10)
    rows = data.get("models")
    if not isinstance(rows, list):
        raise RuntimeError("Ollama returned an invalid model list")
    return {row["name"] for row in rows if isinstance(row, dict)
            and isinstance(row.get("name"), str) and row["name"]
            and not _remote_model(row["name"], row)}


def _publish_models(site: str, token: str, ollama_url: str) -> None:
    _request(f"{site}/api/local-ollama/worker/models", token=token,
             body={"models": sorted(_local_models(ollama_url))}, timeout=15)


def _generate(ollama_url: str, payload: dict) -> str:
    model = str(payload["model"])
    if _remote_model(model, {}):
        raise RuntimeError("Ollama cloud models are not allowed by the local worker")
    installed = _local_models(ollama_url)
    if model not in installed and f"{model}:latest" not in installed:
        raise RuntimeError(f"Model {model!r} is not installed locally. Run: ollama pull {model}")
    # A copied/renamed cloud model can look local. Inspect it without sending the prompt.
    metadata = _request(f"{ollama_url}/api/show", body={"model": model}, timeout=10)
    if _remote_model(model, metadata):
        raise RuntimeError("This Ollama model is remote; the local worker will not send it prompts")
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
        result_url = f"{site}/api/local-ollama/worker/tasks/{task_id}/result"
        try:
            _request(result_url, token=token, body=result)
        except RuntimeError as exc:
            if not str(exc).startswith(("HTTP 413:", "HTTP 422:")):
                raise
            _request(result_url, token=token, body={
                "lease": lease, "error": "Local model response was rejected because of its format or size.",
            })
        print("Model request finished.", flush=True)
    finally:
        stop.set()
        watcher.join(timeout=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect your local Ollama to Applination")
    parser.add_argument("--site", default=DEFAULT_SITE, help="Applination site origin")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA, help="Local Ollama address")
    parser.add_argument("--reset", action="store_true", help="Pair and approve a new worker session")
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
    saved = _load_session(path, site) if not args.reset else {}
    token = saved.get("token", "")
    new_token = not token
    try:
        if not token:
            saved = _pair(site)
            token = saved["token"]
        _request(f"{site}/api/local-ollama/worker/ping", token=token, timeout=15)
        _request(f"{site}/api/local-ollama/worker/models", token=token,
                 body={"models": sorted(models)}, timeout=15)
    except (RuntimeError, URLError, TimeoutError, KeyboardInterrupt, EOFError) as exc:
        print(f"Could not connect to Applination: {exc}", file=sys.stderr)
        return 1
    if new_token:
        try:
            _save_session(path, site, token, saved["expires_at"])
        except OSError:
            print("Could not save a protected session. This session will only last while the worker is open.", file=sys.stderr)
    print("Connected. Keep this window open while Applination uses your model. Ctrl+C to stop.")
    print(f"Session expires at {saved['expires_at']}. Pair again after expiration.")
    next_catalog_refresh = time.monotonic() + 30
    while True:
        try:
            if time.monotonic() >= next_catalog_refresh:
                _publish_models(site, token, ollama_url)
                next_catalog_refresh = time.monotonic() + 30
            response = _request(f"{site}/api/local-ollama/worker/next", token=token, timeout=25)
            task = response.get("task")
            if task:
                _run_task(site, token, ollama_url, task)
        except KeyboardInterrupt:
            print("Stopped.")
            return 0
        except RuntimeError as exc:
            if str(exc).startswith("HTTP 401:"):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass  # The server has already invalidated this session.
                print("Session expired or revoked. Create a new pairing code in Config and run with --reset.", file=sys.stderr)
                return 1
            print(f"Connection problem: {exc}", file=sys.stderr)
            time.sleep(3)
        except (URLError, TimeoutError) as exc:
            print(f"Connection problem: {exc}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
