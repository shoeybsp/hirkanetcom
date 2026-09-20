"""API-key authentication for the FastAPI service.

Every protected route depends on get_current_user, which resolves the
X-API-Key header to an existing User row via the api_keys table - the
same User identity the Flask session-based UI uses, so authorization
(has_device_access) never has to reconcile two different notions of
"who is calling."
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from api_keys import hash_api_key
from api_v2.db import get_session
from api_v2.models import ApiKey, User


def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: Session = Depends(get_session),
) -> User:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header")

    key_hash = hash_api_key(x_api_key)
    api_key = session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if api_key is None or not api_key.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    user = session.get(User, api_key.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    api_key.last_used_at = datetime.now(timezone.utc)
    session.commit()

    return user
