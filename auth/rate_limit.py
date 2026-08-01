"""Database-backed login throttling shared across application workers."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from flask import current_app

from database_transactions import commit_transaction
from models import LoginRateLimit, db


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0
    scope: str | None = None


def _positive_int(config_name: str, default: int) -> int:
    value = int(current_app.config.get(config_name, default))
    return max(1, value)


def _identifier_hash(scope: str, value: str) -> str:
    """Return a keyed digest so usernames and IP addresses are not stored raw."""
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    normalized = f"{scope}:{value.strip().lower()}".encode("utf-8")
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()


def _policy(scope: str) -> tuple[int, int, int]:
    if scope == "username":
        return (
            _positive_int("LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS", 5),
            _positive_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 900),
            _positive_int("LOGIN_RATE_LIMIT_BLOCK_SECONDS", 900),
        )
    if scope == "ip":
        return (
            _positive_int("LOGIN_RATE_LIMIT_IP_ATTEMPTS", 20),
            _positive_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 900),
            _positive_int("LOGIN_RATE_LIMIT_BLOCK_SECONDS", 900),
        )
    raise ValueError(f"Unsupported login rate-limit scope: {scope}")


def _get_row(scope: str, value: str, *, lock: bool = False):
    query = LoginRateLimit.query.filter_by(
        scope=scope,
        identifier_hash=_identifier_hash(scope, value),
    )
    if lock and db.engine.dialect.name != "sqlite":
        query = query.with_for_update()
    return query.first()


def check_login_allowed(username: str, source_ip: str, *, now: int | None = None) -> RateLimitDecision:
    """Check active blocks without incrementing counters."""
    current_time = int(time.time() if now is None else now)
    longest_retry = 0
    blocked_scope = None

    for scope, value in (("username", username), ("ip", source_ip)):
        row = _get_row(scope, value)
        if row and row.blocked_until_epoch > current_time:
            retry = row.blocked_until_epoch - current_time
            if retry > longest_retry:
                longest_retry = retry
                blocked_scope = scope

    return RateLimitDecision(
        allowed=longest_retry == 0,
        retry_after=longest_retry,
        scope=blocked_scope,
    )


def record_login_failure(username: str, source_ip: str, *, now: int | None = None) -> RateLimitDecision:
    """Increment username and IP counters and return any newly active block."""
    current_time = int(time.time() if now is None else now)
    longest_retry = 0
    blocked_scope = None

    for scope, value in (("username", username), ("ip", source_ip)):
        maximum_attempts, window_seconds, block_seconds = _policy(scope)
        row = _get_row(scope, value, lock=True)

        if row is None:
            row = LoginRateLimit(
                scope=scope,
                identifier_hash=_identifier_hash(scope, value),
                window_started_epoch=current_time,
                failed_attempts=0,
                blocked_until_epoch=0,
                updated_at_epoch=current_time,
            )
            db.session.add(row)

        if current_time - row.window_started_epoch >= window_seconds:
            row.window_started_epoch = current_time
            row.failed_attempts = 0
            row.blocked_until_epoch = 0

        row.failed_attempts += 1
        row.updated_at_epoch = current_time

        if row.failed_attempts >= maximum_attempts:
            row.blocked_until_epoch = max(
                row.blocked_until_epoch,
                current_time + block_seconds,
            )
            retry = row.blocked_until_epoch - current_time
            if retry > longest_retry:
                longest_retry = retry
                blocked_scope = scope

    commit_transaction("record failed login rate-limit counters")
    return RateLimitDecision(
        allowed=longest_retry == 0,
        retry_after=longest_retry,
        scope=blocked_scope,
    )


def clear_login_failures(username: str) -> None:
    """Clear the account-specific counter after successful authentication."""
    row = _get_row("username", username, lock=True)
    if row is not None:
        db.session.delete(row)
        commit_transaction("clear successful login rate-limit counter")


def cleanup_expired_login_limits(*, now: int | None = None) -> int:
    """Delete stale rows; suitable for a periodic maintenance command."""
    current_time = int(time.time() if now is None else now)
    retention_seconds = int(os.getenv("LOGIN_RATE_LIMIT_RETENTION_SECONDS", "86400"))
    deleted = LoginRateLimit.query.filter(
        LoginRateLimit.updated_at_epoch < current_time - max(retention_seconds, 3600)
    ).delete(synchronize_session=False)
    if deleted:
        commit_transaction("clean expired login rate-limit counters")
    return int(deleted)
