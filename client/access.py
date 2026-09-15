"""Authorization helpers for subscription-backed client services."""

import logging
from functools import wraps

from flask import abort, request
from flask_login import current_user

from models import Device, DeviceAssignment, Service, Subscription, db

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


def get_assigned_devices(user_id: int) -> list[Device]:
    """Return the active devices a client has been granted access to.

    A device only shows up here if both the assignment and the device
    itself are active - an admin deactivating a device (e.g. while it's
    being decommissioned) immediately hides it from clients without
    needing to also touch every individual assignment.
    """
    return (
        db.session.query(Device)
        .join(DeviceAssignment, DeviceAssignment.device_id == Device.id)
        .filter(
            DeviceAssignment.user_id == user_id,
            DeviceAssignment.is_active.is_(True),
            Device.is_active.is_(True),
        )
        .order_by(Device.name)
        .all()
    )


def has_device_access(user_id: int, device_id: int) -> bool:
    """Return whether a user may evaluate policies against a given device."""
    return (
        db.session.query(DeviceAssignment.id)
        .join(Device, DeviceAssignment.device_id == Device.id)
        .filter(
            DeviceAssignment.user_id == user_id,
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.is_active.is_(True),
            Device.is_active.is_(True),
        )
        .first()
        is not None
    )
