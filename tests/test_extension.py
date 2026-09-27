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
        from server.db import User

        monkeypatch.setattr(User, "model_dump", lambda *_args, **_kwargs: {})
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

        calls = []
        incomplete = ("I built a reliable data pipeline and learned how to connect the work "
                      "to the needs of the people using it. " * 3) + "The result was"
        def draft_with_retry(_user, _system, _prompt, *, task, max_tokens=1200):
            calls.append(max_tokens)
            return incomplete if len(calls) == 1 else "I built a reliable data pipeline and improved its accuracy."
        monkeypatch.setattr(chat, "_run_chain", draft_with_retry)
        completed = anonymous.post("/api/extension/data/generate-answer", headers=headers,
                                   json={"prompt": "What did you build?", "company": "Acme", "title": "Engineer"})
        assert completed.status_code == 200, completed.text
        assert completed.json()["content"] == "I built a reliable data pipeline and improved its accuracy."
        assert len(calls) == 2 and calls[1] > calls[0]
        monkeypatch.setattr(chat, "_run_chain", lambda *_args, **_kwargs: incomplete)
        still_partial = anonymous.post("/api/extension/data/generate-answer", headers=headers,
                                       json={"prompt": "What did you build?", "company": "Acme"})
        assert still_partial.status_code == 502

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


def test_open_page_generation_and_website_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app
    from server import single_job
    from server.db import Application, Run, RunStatus, session

    captured = []

    def start(body, user_id):
        captured.append(body)
        with session() as s:
            run = Run(user_id=user_id, status=RunStatus.queued)
            s.add(run)
            s.commit()
            s.refresh(run)
            return run.id

    monkeypatch.setattr(single_job, "start_generation", start)
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as extension:
        owner_id = register(owner, "owner@example.com")["id"]
        register(other, "other@example.com")
        code = extension.post("/api/extension/pair/start").json()
        owner.post("/api/extension/pair/approve", json={"user_code": code["user_code"]})
        token = extension.post("/api/extension/pair/complete", json={"device_code": code["device_code"]}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert other.get("/api/application-profile").json()["account"] == "other@example.com"
        assert owner.put("/api/application-profile", json={"extra": {"work_authorization": "Yes"}}).status_code == 200
        assert extension.get("/api/extension/data/profile", headers=headers).json()["extra"] == {"work_authorization": "Yes"}
        saved = owner.post("/api/application-profile/answers", json={"prompt": "Why us?", "content": "I like the team."}).json()
        assert extension.get("/api/extension/data/answers", headers=headers).json()[0]["id"] == saved["id"]
        assert other.delete(f"/api/application-profile/answers/{saved['id']}").status_code == 404

        job = {"url": "https://jobs.example/apply#form", "company": "Acme", "title": "Engineer",
               "description": "Build software for customers."}
        assert extension.post("/api/extension/data/generate-resume", json=job).status_code == 401
        started = extension.post("/api/extension/data/generate-resume", headers=headers, json=job)
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        assert captured[0].description == job["description"]
        assert captured[0].url == "https://jobs.example/apply"
        assert captured[0].source == "extension"
        assert extension.get(f"/api/extension/data/generate-resume/{run_id}", headers=headers).json()["status"] == "queued"

        folder = tmp_path / "resume-output"
        folder.mkdir()
        (folder / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
        with session() as s:
            run = s.get(Run, run_id)
            run.status = RunStatus.done
            app_row = Application(user_id=owner_id, run_id=run_id, company="Acme", title="Engineer",
                                  url="https://jobs.example/apply", source="extension",
                                  folder_path=str(folder), description=job["description"])
            s.add(run)
            s.add(app_row)
            s.commit()
            s.refresh(app_row)
            app_id = app_row.id
        ready = extension.get(f"/api/extension/data/generate-resume/{run_id}", headers=headers).json()
        assert ready["resume_id"] == f"app:{app_id}:resume"
        assert extension.get(f"/api/extension/data/documents/{ready['resume_id']}", headers=headers).content.startswith(b"%PDF-")
        tracked = extension.post("/api/extension/data/track", headers=headers,
                                 json={**job, "application_id": app_id, "submitted": True}).json()
        assert tracked == {"id": app_id, "status": "applied"}
        assert owner.delete(f"/api/application-profile/answers/{saved['id']}").status_code == 200
