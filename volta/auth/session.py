"""Session auth helpers."""

from __future__ import annotations

import hashlib
import secrets

from volta.config import config

SESSION_AUTH_KEY = "authenticated"
SESSION_USERNAME_KEY = "username"


def _digest_eq(a: str, b: str) -> bool:
    da = hashlib.sha256(a.encode("utf-8")).digest()
    db = hashlib.sha256(b.encode("utf-8")).digest()
    return secrets.compare_digest(da, db)


def verify_credentials(username: str | None, password: str | None) -> bool:
    """Check panel login/password against env config."""
    u = (username or "").strip()
    p = password or ""
    if not u:
        return False
    return _digest_eq(u, config.panel.login) and _digest_eq(p, config.panel.password)


def is_authenticated_session(session: dict) -> bool:
    """Return True if session dict has valid auth flag."""
    return bool(session.get(SESSION_AUTH_KEY))
