"""Inbox parsing, classification normalization, and matching — no network/LLM."""
from __future__ import annotations
from datetime import datetime
from email.message import EmailMessage

from src.inbox import InboxEmail, _extract_body, _parse_message, classify_email
from server import inbox as ib


# --------------------------- email parsing ---------------------------
def _raw(subject: str, body: str, sender: str = "Recruiter <jobs@acme.com>") -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["Subject"] = subject
    m["Message-ID"] = "<abc@acme.com>"
    m.set_content(body)
    return m.as_bytes()


def test_parse_message_extracts_headers_and_body():
    e = _parse_message("7", _raw("Your application", "Thanks for applying!"))
    assert e.from_email == "jobs@acme.com"
    assert e.subject == "Your application"
    assert e.domain == "acme.com"
    assert "Thanks for applying" in e.body
    assert e.message_id == "<abc@acme.com>"


def test_extract_body_prefers_plain_and_strips_html():
    m = EmailMessage()
    m.set_content("plain version")
    m.add_alternative("<p>html <b>version</b></p>", subtype="html")
    assert "plain version" in _extract_body(m)

    only_html = EmailMessage()
    only_html.set_content("<p>Hello <b>there</b></p>", subtype="html")
    assert "Hello there" in _extract_body(only_html)


# --------------------------- classification --------------------------
class _StubProvider:
    name = "stub"

    def __init__(self, payload):
        self.payload = payload

    def json_call(self, system, user, max_tokens=300, schema=None):
        return self.payload


_MSG = InboxEmail(uid="1", message_id="<a@x>", from_name="Acme", from_email="jobs@acme.com",
                  subject="hi", date=None, body="b")


def test_classify_normalizes_and_parses_date():
    res = classify_email(
        [_StubProvider({"category": "interview", "confidence": 0.9,
                        "summary": "call", "interview_date": "2026-06-20T15:00"})],
        _MSG, company="Acme", title="SWE")
    assert res["category"] == "interview"
    assert res["confidence"] == 0.9
    assert res["interview_date"] == datetime(2026, 6, 20, 15, 0)


def test_classify_clamps_and_defaults_unknown_category():
    res = classify_email([_StubProvider({"category": "nope", "confidence": 5})],
                         _MSG, company="A", title="B")
    assert res["category"] == "other"
    assert res["confidence"] == 1.0


def test_classify_survives_provider_failure():
    class _Boom:
        name = "boom"
        def json_call(self, *a, **k):
            raise RuntimeError("down")
    res = classify_email([_Boom()], _MSG, company="A", title="B")
    assert res["category"] == "other" and res["confidence"] == 0.0


# --------------------------- company matching ------------------------
def test_company_tokens_drops_stopwords():
    toks = ib._company_tokens("Acme Technologies, Inc")
    assert "acme" in toks
    assert "inc" not in toks and "technologies" not in toks


def test_email_matches_on_domain_subject_or_body():
    toks = ib._company_tokens("Acme Inc")
    norm = "acme inc"
    by_domain = InboxEmail("1", "<a>", "Talent", "no-reply@acme.com", "hello", None, "x")
    by_subject = InboxEmail("2", "<b>", "Talent", "x@x.com", "Acme application", None, "x")
    in_body = InboxEmail("3", "<c>", "Talent", "x@x.com", "hi", None, "regarding acme inc role")
    unrelated = InboxEmail("4", "<d>", "News", "x@news.com", "weekly", None, "nothing here")
    assert ib._email_matches_app(by_domain, toks, norm)
    assert ib._email_matches_app(by_subject, toks, norm)
    assert ib._email_matches_app(in_body, toks, norm)
    assert not ib._email_matches_app(unrelated, toks, norm)
