"""Gunicorn configuration.

By default, gunicorn logs nothing at all for incoming requests — its access
log is disabled unless explicitly turned on. That means without this file,
`docker logs` / `docker-compose logs` show only worker start/stop messages,
with zero record of the HTTP traffic the app actually served.

This config turns both the access log and error log on, sends them to
stdout/stderr (so the container runtime captures them like everything
else), and ties the verbosity to the same LOG_LEVEL env var the Flask app
itself uses, so one setting controls both.
"""

import os

bind = "0.0.0.0:5000"

accesslog = "-"  # "-" means stdout
errorlog = "-"  # "-" means stderr
loglevel = os.environ.get("LOG_LEVEL", "info").lower()

# LOG_FORMAT=json switches to structured JSON access logs (see
# gunicorn_logging.py) so a log shipper doesn't need a parsing pattern.
# Default stays human-readable for plain local/venv use.
if os.environ.get("LOG_FORMAT", "text").lower() == "json":
    logger_class = "gunicorn_logging.JsonAccessLogger"
else:
    # h=remote addr, r=request line, s=status, b=response size,
    # L=request duration in seconds
    access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(L)ss'
