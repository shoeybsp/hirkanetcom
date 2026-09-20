"""Authorization for the FastAPI service.

has_device_access here is a deliberate port of client/access.py's function
of the same name - same rule (both the assignment and the device must be
active), same two tables - just taking a plain Session instead of Flask's
db.session. This is the single source of truth this service reuses rather
than reinventing; if the rule ever changes, both copies need updating
together until/unless they're unified into one shared module.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from api_v2.models import Device, DeviceAssignment


def has_device_access(session: Session, user_id: int, device_id: int) -> bool:
    """Return whether a user may operate on a given device via the API."""
    stmt = (
        select(DeviceAssignment.id)
        .join(Device, DeviceAssignment.device_id == Device.id)
        .where(
            DeviceAssignment.user_id == user_id,
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.is_active.is_(True),
            Device.is_active.is_(True),
        )
    )
    return session.execute(stmt).first() is not None
