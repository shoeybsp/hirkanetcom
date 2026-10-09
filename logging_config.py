"""Central structured logging and request correlation."""
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from flask import g, has_request_context, request

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_REDACT_KEYS = {
    "password", "password_hash", "salt", "token", "authorization", "cookie",
    "secret", "csrf_token", "api_key", "auth_password", "set-cookie",
}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _safe_request_id(candidate):
    """Accept a caller-supplied X-Request-ID only if it is short and log-safe."""
    if candidate and _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


def _safe(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _safe(v)) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value

class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "message": record.getMessage(),
            "log": {"level": record.levelname.lower(), "logger": record.name},
            "service": {"name": os.getenv("SERVICE_NAME", "hirkanet")},
            "event": {"dataset": getattr(record, "event_dataset", "hirkanet.application")},
        }
        if has_request_context():
            event["request"] = {"id": getattr(g, "request_id", None)}
            event["http"] = {"request": {"method": request.method}}
            event["url"] = {"path": request.path}
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_") and key not in {"event_dataset"}:
                # Redact by the top-level field name too, not only keys nested
                # inside dict values.
                event[key] = "[REDACTED]" if key.lower() in _REDACT_KEYS else _safe(value)
        if record.exc_info:
            event["error"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stack_trace": self.formatException(record.exc_info),
            }
        return json.dumps(event, default=str, separators=(",", ":"))

def configure_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("LOG_FORMAT", "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("werkzeug").setLevel(level)

def install_request_logging(app):
    logger = logging.getLogger("hirkanet.http")
    @app.before_request
    def _start_request():
        g.request_id = _safe_request_id(request.headers.get("X-Request-ID"))
        g.request_started = time.perf_counter()
    @app.after_request
    def _finish_request(response):
        # An earlier before_request hook (e.g. CSRF protection, which is
        # registered before this logger) can abort the request before
        # _start_request runs, so these attributes may be missing.
        started = g.get("request_started", time.perf_counter())
        request_id = g.get("request_id") or _safe_request_id(None)
        g.request_id = request_id
        duration_ns = int((time.perf_counter() - started) * 1_000_000_000)
        response.headers["X-Request-ID"] = request_id
        logger.info("HTTP request completed", extra={
            "event_dataset": "hirkanet.http_access",
            "event_type": "access",
            "event_duration": duration_ns,
            "http_status_code": int(response.status_code),
            "user_id": str(getattr(getattr(__import__('flask_login'), 'current_user', None), 'id', '')) or None,
        })
        return response
