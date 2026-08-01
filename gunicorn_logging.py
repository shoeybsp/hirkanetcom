from gunicorn.glogging import Logger


class JsonAccessLogger(Logger):
    """Gunicorn logger compatible with Hirkanet's structured logging.

    Hirkanet's Flask request middleware already emits structured HTTP access
    events, so Gunicorn's duplicate access logging is intentionally suppressed.
    Gunicorn startup, worker, and error logs continue to use the standard
    Gunicorn logging implementation inherited from ``Logger``.
    """

    def access(self, resp, req, environ, request_time):
        """Suppress duplicate Gunicorn access logs."""
        return
