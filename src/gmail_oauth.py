"""Google OAuth plumbing for Gmail access (authorization-code flow).

Engine-side: knows nothing about config.yaml or the DB. The server
(``server/gmail_auth.py``) owns where client_id/client_secret and the token
blob are persisted. Scopes are read-only inbox access + send, so the same
credentials cover both inbox sync and the digest email.
"""
from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_auth_url(client_id: str, client_secret: str, redirect_uri: str, state: str) -> tuple[str, str]:
    """Return (consent-screen URL, PKCE code_verifier) for this client.

    The Flow auto-generates a code_verifier and encodes its challenge into the
    URL; the same verifier must be replayed into ``exchange_code`` below or
    Google rejects the token exchange with "Missing code verifier".
    """
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, flow.code_verifier


def exchange_code(
    client_id: str, client_secret: str, redirect_uri: str, code: str, code_verifier: str
) -> Credentials:
    """Exchange an authorization code for credentials (with a refresh token)."""
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_token_json(token_json: dict, client_id: str, client_secret: str) -> Credentials:
    """Rebuild Credentials from a stored token blob, refreshing if expired."""
    creds = Credentials(
        token=token_json.get("token"),
        refresh_token=token_json.get("refresh_token"),
        token_uri=token_json.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=token_json.get("scopes") or SCOPES,
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return creds


def credentials_to_token_json(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or SCOPES),
    }


def get_account_email(creds: Credentials) -> str:
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return str(profile.get("emailAddress") or "")
