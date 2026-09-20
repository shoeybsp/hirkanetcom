"""Hirkanet API v2 - FastAPI pilot service.

Additive, not a replacement: the existing Flask app (api/app.py) keeps
running everything it already does (admin panel, client UI, session
auth). This service is for new, genuinely API-shaped features only - see
docs/architecture.md for the split rationale.

Phase 1 scope: health checks and the API-key auth dependency, wired end
to end and verified against a real issued key. Business routes (the
device-sync pilot endpoint) are Phase 2, deliberately not included here.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from api_v2.auth import get_current_user
from api_v2.models import User

app = FastAPI(title="Hirkanet API v2", version="0.1.0")


@app.get("/livez")
def livez():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    from sqlalchemy import text

    from api_v2.db import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="not_ready")


@app.get("/whoami")
def whoami(user: User = Depends(get_current_user)):
    """Temporary Phase-1 verification route: confirms the API-key auth
    dependency resolves to the correct User end to end. Not a permanent
    part of the API surface - safe to remove once Phase 2's real
    endpoint exists and is verified the same way.
    """
    return {"user_id": user.id, "username": user.username, "role": user.role}
