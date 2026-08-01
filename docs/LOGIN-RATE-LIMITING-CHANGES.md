# Login rate limiting and environment template

## Scope

This change adds database-backed login throttling and a safe `.env.example`.
No Elastic Stack files or settings were modified.

## Changed files

- `api/app.py`
- `models.py`
- `auth/rate_limit.py` (new)
- `migrations/versions/20260801_0004_login_rate_limits.py` (new)
- `tests/test_login_rate_limiting.py` (new)
- `templates/login.html`
- `.env.example` (new)

## Login rate limiting behavior

The login endpoint now evaluates two independent limits before checking a password:

1. Normalized username
2. Source IP address

Identifiers are stored as keyed HMAC-SHA256 digests. Raw usernames and IP addresses are not stored in the rate-limit table.

Default policy:

- Username: 5 failed attempts per 15-minute window
- Source IP: 20 failed attempts per 15-minute window
- Block duration: 15 minutes

When either limit is active, `/login` returns HTTP `429 Too Many Requests` and a `Retry-After` header. Failed attempts continue to return the existing generic authentication message, so the response does not reveal whether a username exists.

The username counter is removed after successful authentication. IP counters remain until expiration to prevent an attacker from resetting an address-wide limit by successfully authenticating one account.

Rate-limit rows are stored in PostgreSQL/SQLite, so limits are shared across Gunicorn workers and survive worker restarts.

## Configuration

The following variables are now supported:

- `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS`
- `LOGIN_RATE_LIMIT_IP_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `LOGIN_RATE_LIMIT_BLOCK_SECONDS`
- `LOGIN_RATE_LIMIT_RETENTION_SECONDS`

See `.env.example` for safe defaults.

## Deployment

Replace the changed files, then apply the migration before restarting the application:

```bash
flask --app api.app db upgrade
```

Run the focused regression test:

```bash
pytest -q tests/test_login_rate_limiting.py
```

Then restart or rebuild the application containers.

## Proxy requirement

IP-based limiting depends on `request.remote_addr`. Enable `TRUST_PROXY_HEADERS=true` only when the application is behind the documented single-hop trusted reverse proxy. Do not enable it when clients can connect directly to the Flask/Gunicorn port.

## Maintenance

Expired rows are small and indexed. The module exposes `cleanup_expired_login_limits()` for a future scheduled maintenance command. Rows older than `LOGIN_RATE_LIMIT_RETENTION_SECONDS` can be safely deleted.
