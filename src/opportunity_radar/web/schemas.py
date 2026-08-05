"""CSRF helper for state-changing dashboard actions (spec §24).

Single local user: a deterministic HMAC of the app secret is sufficient to
stop cross-site request forgery from other pages the browser has open.
"""

from __future__ import annotations

import hashlib
import hmac

from opportunity_radar.config import get_settings


def csrf_token() -> str:
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, b"opportunity-radar-csrf", hashlib.sha256).hexdigest()[:32]


def check_csrf(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token or "", csrf_token())
