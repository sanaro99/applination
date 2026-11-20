"""Job postings are public, attacker-writable text. Nothing from one may turn
into a live spreadsheet formula in the tracker or the CSV export."""
from __future__ import annotations

import csv
import io

from openpyxl import load_workbook

from src.excel_writer import build_tracker

EVIL = '=HYPERLINK("https://evil.example","Click")'


def test_tracker_stores_formula_like_text_as_text(tmp_path):
    out = tmp_path / "apps.xlsx"
    build_tracker([{"company": EVIL, "title": "+cmd|' /C calc'!A0", "match_reason": "=1+1",
                    "url": "https://example.com"}], out, "2026-11-20")
    ws = load_workbook(out).active
    for col in (3, 4, 15):
        cell = ws.cell(row=2, column=col)
        assert cell.data_type == "s", (col, cell.data_type)
    assert ws.cell(row=2, column=3).value == EVIL


def test_csv_export_neutralises_formulas(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server.db as db
    from .conftest import make_engine, register

    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as client:
        user = register(client, "csv@example.com")
        with db.session() as s:
            s.add(db.Application(user_id=user["id"], company=EVIL, title="@SUM(A1)", location="Remote",
                                 source="manual", url="https://example.com", folder_path=""))
            s.commit()
        res = client.post("/api/applications/export")
        assert res.status_code == 200, res.text
        rows = list(csv.reader(io.StringIO(res.text)))
        assert rows[1][0] == "'" + EVIL
        assert rows[1][1] == "'@SUM(A1)"
        assert rows[1][2] == "Remote"
