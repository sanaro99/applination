"""Rate limiting.

In-process (slowapi's default memory backend) because Applination runs as a
single container — there is no second worker to share counters with. If it ever
scales out, this needs a Redis storage backend or the limits silently become
per-process.

Signup and login are limited **per IP**: there is no user yet, and the thing
being defended is account creation and password guessing. Everything that spends
an LLM call is limited **per user**, because with BYOK the cost lands on that
user's own key and the thing being defended is the shared worker, not a bill.
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _user_or_ip(request: Request) -> str:
    """Rate-limit key: the authenticated user when there is one, else the IP.

    ``require_user`` stashes the id on request.state. The IP fallback matters
    for the unauthenticated routes and means a missing user can never turn into
    an *unlimited* key.

    The shared demo account is keyed by IP instead of by user. The per-user LLM
    limit exists to cap spend on the shared worker, and a demo call spends
    nothing: it is answered from a fixture. Keying it per user would let one
    visitor lock every other visitor out of an account they all share.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None and not getattr(request.state, "is_demo", False):
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


# Disabled in tests: the authz suite makes many rapid calls as the same user and
# would otherwise trip the per-user limit and 429 instead of asserting on 404s.
_ENABLED = os.environ.get("APPLINATION_DISABLE_RATE_LIMITS", "") != "1"

limiter = Limiter(key_func=_user_or_ip, enabled=_ENABLED)

# Per-IP, on the unauthenticated routes.
SIGNUP_LIMIT = "5/hour"
LOGIN_LIMIT = "10/minute"

# Per-user, on anything that makes an LLM call. Generous enough not to be felt
# in normal use; tight enough that one account cannot monopolise the worker.
LLM_LIMIT = "30/minute"
