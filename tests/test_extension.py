"""Extension pairing, credential scope, tenant isolation, and application state."""
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

import server.db as db
from .conftest import make_engine, register


def test_signed_in_user_can_download_installable_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server.extension import EXTENSION_PACKAGE_FILES

    with TestClient(app) as client, TestClient(app) as anonymous:
        assert anonymous.get("/api/extension/download").status_code == 401
        register(client, "tester@example.com")
        response = client.get("/api/extension/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-disposition"].startswith("attachment; filename=")
        with zipfile.ZipFile(BytesIO(response.content)) as bundle:
            assert set(bundle.namelist()) == {
                *(f"applination-extension/{name}" for name in EXTENSION_PACKAGE_FILES),
                "applination-extension/INSTALL.txt",
            }
            manifest = json.loads(bundle.read("applination-extension/manifest.json"))
            assert manifest["manifest_version"] == 3
            assert "Load unpacked" in bundle.read("applination-extension/INSTALL.txt").decode()


def test_pairing_and_scoped_access(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as anonymous:
        register(owner, "owner@example.com")
        register(other, "other@example.com")
        started = anonymous.post("/api/extension/pair/start").json()
        device = {"device_code": started["device_code"]}
        assert anonymous.post("/api/extension/pair/complete", json=device).json() == {"status": "pending"}
        assert anonymous.post("/api/extension/pair/approve", json={"user_code": started["user_code"]}).status_code == 401
        assert owner.post("/api/extension/pair/approve", json={"user_code": started["user_code"]}).status_code == 200
        token = anonymous.post("/api/extension/pair/complete", json=device).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        grants = owner.get("/api/extension/pair/grants").json()
        assert len(grants) == 1
        assert other.delete(f"/api/extension/pair/grants/{grants[0]['id']}").status_code == 404
        assert anonymous.get("/api/extension/data/profile", headers=headers).json()["account"] == "owner@example.com"
        assert anonymous.get("/api/applications", headers=headers).status_code == 401
        assert anonymous.post("/api/extension/pair/complete", json=device).status_code == 404
        assert anonymous.get("/api/extension/data/profile").status_code == 401

        assert anonymous.put("/api/extension/data/profile", headers=headers,
                             json={"extra": {"work_authorization": "Yes"}}).status_code == 200
        assert anonymous.get("/api/extension/data/profile", headers=headers).json()["extra"]["work_authorization"] == "Yes"
        assert other.get("/api/extension/data/profile").status_code == 401

        from server import chat
        monkeypatch.setattr(chat, "_run_chain", lambda *_args, **_kwargs: "A grounded draft")
        generated = anonymous.post("/api/extension/data/generate-answer", headers=headers,
                                   json={"prompt": "Why this role?", "company": "Acme", "title": "Engineer"})
        assert generated.status_code == 200, generated.text
        assert generated.json() == {"content": "A grounded draft"}

        payload = {"url": "https://boards.example/jobs/123?posting=abc#apply", "company": "Acme", "title": "Engineer"}
        first = anonymous.post("/api/extension/data/track", headers=headers, json=payload).json()
        assert first["status"] == "generated"
        second = anonymous.post("/api/extension/data/track", headers=headers,
                                json={**payload, "submitted": True}).json()
        assert second == {"id": first["id"], "status": "applied"}
        assert owner.get("/api/applications").json()[0]["status"] == "applied"
        assert other.get("/api/applications").json() == []

        uploaded = anonymous.post("/api/extension/data/documents?kind=resume", headers=headers,
                                  files={"file": ("resume.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
        assert uploaded.status_code == 200
        document_id = uploaded.json()["id"]
        assert anonymous.get(f"/api/extension/data/documents/{document_id}", headers=headers).content.startswith(b"%PDF-")
        assert other.get(f"/api/extension/data/documents/{document_id}").status_code == 401

        other_pair = anonymous.post("/api/extension/pair/start").json()
        assert other.post("/api/extension/pair/approve", json={"user_code": other_pair["user_code"]}).status_code == 200
        other_token = anonymous.post("/api/extension/pair/complete", json={"device_code": other_pair["device_code"]}).json()["token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert anonymous.get(f"/api/extension/data/documents/{document_id}", headers=other_headers).status_code == 404
        assert anonymous.get("/api/extension/data/profile", headers=other_headers).json()["account"] == "other@example.com"

        assert anonymous.post("/api/extension/data/disconnect", headers=headers).status_code == 200
        assert anonymous.get("/api/extension/data/profile", headers=headers).status_code == 401
