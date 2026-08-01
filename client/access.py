"""Authorization helpers for subscription-backed client services."""

import logging
from functools import wraps

from flask import abort, request
from flask_login import current_user

from models import Service, Subscription, db

logger = logging.getLogger(__name__)


def has_active_service_subscription(user_id: int, service_type: str) -> bool:
    """Return whether a user has an active subscription to an active service."""
    return (
        db.session.query(Subscription.id)
        .join(Service, Subscription.service_id == Service.id)
        .filter(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
            Service.service_type == service_type,
            Service.is_active.is_(True),
        )
        .first()
        is not None
    )


def subscription_required(service_type: str):
    """Require an active subscription for the decorated authenticated route."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not has_active_service_subscription(current_user.id, service_type):
                logger.warning(
                    "Subscription-protected service access denied",
                    extra={
                        "event_type": "subscription_authorization_denied",
                        "user_id": str(current_user.id),
                        "service_type": service_type,
                        "request_method": request.method,
                        "request_path": request.path,
                    },
                )
                abort(403, description="An active subscription is required for this service.")

            return view(*args, **kwargs)

        return wrapped

    return decorator
