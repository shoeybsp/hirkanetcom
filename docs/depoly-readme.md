# Hirkanet Deployment Guide

This guide describes everything that must be prepared before starting Hirkanet. The application and PostgreSQL run in one Docker Compose project, while the Elastic observability stack runs in a separate optional Compose project.

## 1. Deployment layout

Hirkanet uses two independent Compose files:

| Stack | Compose file | Services |
|---|---|---|
| Application | `docker-compose.yml` | `db`, `migrate`, `app` |
| Observability | `docker-compose.elastic.yml` | Elasticsearch, Kibana, Logstash, Filebeat, certificate setup, Elastic initialization |

The normal application command starts only Hirkanet and PostgreSQL:

```bash
docker compose up -d --build
```

The Elastic stack is started separately:

```bash
docker compose -f docker-compose.elastic.yml up -d
```

## 2. Prerequisites

Install and verify:

- Docker Engine
- Docker Compose v2 (`docker compose`, not the legacy `docker-compose` command)
- OpenSSL
- A Linux host for the documented production setup
- Nginx, Caddy, Traefik, or another trusted HTTPS reverse proxy for production
- DNS control for `hirkanet.com` and `www.hirkanet.com`

Recommended minimum host capacity when both stacks run on one host:

- 4 CPU cores
- 8 GiB RAM
- 40 GiB free disk space, with additional capacity for PostgreSQL, Elastic indices, backups, uploads, and FortiGate snapshots

Verify Docker:

```bash
docker version
docker compose version
```

Run all commands from the project root, where `docker-compose.yml` is located:

```bash
pwd
ls -la docker-compose.yml docker-compose.elastic.yml .env.example secrets/
```

## 3. Create `.env`

The repository intentionally does not include a real `.env` file. Create it from the example:

```bash
cp .env.example .env
chmod 600 .env
```

Review and set at least:

```env
POSTGRES_DB=hirkanet
POSTGRES_USER=hirkanet
BOOTSTRAP_ADMIN_USERNAME=admin
APP_ENV=production
SERVICE_NAME=hirkanet
LOG_LEVEL=INFO
LOG_FORMAT=json
TZ=Europe/Riga

TRUST_PROXY_HEADERS=true
TRUSTED_HOSTS=hirkanet.com,www.hirkanet.com,localhost,127.0.0.1
```

For the optional Elastic stack, set a stack version that exists in the official Elastic registry and use the same version for Elasticsearch, Kibana, Logstash, and Filebeat:

```env
STACK_VERSION=9.3.8
ES_JAVA_OPTS=-Xms512m -Xmx512m
LS_JAVA_OPTS=-Xms256m -Xmx256m
```

Before deployment, verify the exact version exists under the official `docker.elastic.co` images. Do not mix Elastic component versions unless compatibility has been explicitly verified.

Do not put passwords or encryption keys in `.env`. Hirkanet uses mounted secret files.

## 4. Create required secret files

Compose mounts extensionless files from `secrets/`. The `.example` files are templates only and are not used at runtime.

### Application and PostgreSQL secrets

These are required before running `docker compose up`:

```text
secrets/postgres_password
secrets/flask_secret_key
secrets/bootstrap_admin_password
```

Create strong random values:

```bash
mkdir -p secrets
openssl rand -hex 32 > secrets/postgres_password
openssl rand -hex 32 > secrets/flask_secret_key
openssl rand -hex 32 > secrets/bootstrap_admin_password
```

The bootstrap administrator password must satisfy the application password policy. Store the generated value securely before starting the stack.

### Elastic secrets

These are required only when starting `docker-compose.elastic.yml`:

```text
secrets/elastic_password
secrets/kibana_password
secrets/logstash_password
secrets/kibana_security_encryption_key
secrets/kibana_saved_objects_encryption_key
secrets/kibana_reporting_encryption_key
```

Create them:

```bash
openssl rand -hex 32 > secrets/elastic_password
openssl rand -hex 32 > secrets/kibana_password
openssl rand -hex 32 > secrets/logstash_password
openssl rand -hex 32 > secrets/kibana_security_encryption_key
openssl rand -hex 32 > secrets/kibana_saved_objects_encryption_key
openssl rand -hex 32 > secrets/kibana_reporting_encryption_key
```

Restrict permissions:

```bash
chmod 700 secrets
chmod 600 secrets/postgres_password \
  secrets/flask_secret_key \
  secrets/bootstrap_admin_password \
  secrets/elastic_password \
  secrets/kibana_password \
  secrets/logstash_password \
  secrets/kibana_security_encryption_key \
  secrets/kibana_saved_objects_encryption_key \
  secrets/kibana_reporting_encryption_key
```

Verify that every required file exists and is non-empty:

```bash
for file in \
  postgres_password flask_secret_key bootstrap_admin_password \
  elastic_password kibana_password logstash_password \
  kibana_security_encryption_key kibana_saved_objects_encryption_key \
  kibana_reporting_encryption_key; do
  test -s "secrets/$file" || echo "Missing or empty: secrets/$file"
done
```

Never commit real secret files to Git, place them in a Docker image, or send them in support bundles.

## 5. Prepare writable directories

The application container has a read-only root filesystem. Only these host paths are writable:

```text
data/
uploads/
static/uploads/
```

Create the host-mounted ones before startup (application data now lives in
a Docker-managed named volume, `hirkanet_data`, not a host directory - see
below):

```bash
mkdir -p uploads static/uploads/blog backups/postgres
```

The application container runs as a non-root user with a fixed UID/GID of
`10001` (see the `app` user in the Dockerfile). `data/` in `docker-compose.yml`
is a **named volume** (`hirkanet_data:/app/data`), not a host bind mount:
Docker populates it from `/app/data` inside the built image the first time
it's created, and the Dockerfile explicitly creates that path with
`uid 10001` ownership (`RUN mkdir -p /app/data ... && chown -R app:app /app`)
so the volume always comes up writable regardless of what the host build
machine happens to contain. Nothing to `chown` on the host for `data/`.

`uploads/` and `static/uploads/` are still plain host bind mounts, so - like
before - their permissions come from the host filesystem and need explicit
ownership:

```bash
sudo chown -R 10001:10001 uploads static/uploads
```

Do not use `chmod 777`. If you rebuild the image against a different base
that assigns a different UID, `docker compose exec app id` will tell you the
UID/GID actually in use so you can adjust the `chown` above.

```bash
ls -ld uploads static/uploads backups
docker volume ls | grep hirkanet   # confirms hirkanet-app_hirkanet_data exists
```

Since `data/` is a named volume, it isn't visible as a folder in the project
directory on the host. To inspect its contents:

```bash
docker compose exec app ls -la /app/data
```

If you're migrating from an earlier bind-mounted `./data` setup, its
contents are **not** copied into the new named volume automatically - copy
them over explicitly (e.g. with a one-off container mounting both paths) if
you want to keep existing collected snapshots.

FortiGate data and uploads contain sensitive or persistent information and must be included in the host backup plan.

## 6. Validate configuration before starting

Validate the application Compose file:

```bash
docker compose config >/tmp/hirkanet-app-compose.rendered.yml
```

Validate the Elastic Compose file:

```bash
docker compose -f docker-compose.elastic.yml config \
  >/tmp/hirkanet-elastic-compose.rendered.yml
```

Check the resolved images:

```bash
docker compose -f docker-compose.elastic.yml config | grep 'image:'
```

Check that secrets resolve to existing paths:

```bash
docker compose config | grep -A3 'file:'
docker compose -f docker-compose.elastic.yml config | grep -A3 'file:'
```

## 7. Start the application and PostgreSQL

Start the application stack:

```bash
docker compose up -d --build
```

Startup order is controlled:

1. PostgreSQL starts and passes an authenticated health check.
2. The one-shot `migrate` service runs `flask db upgrade`.
3. The same service runs the idempotent `seed-defaults` command.
4. Gunicorn starts only after migration and seeding succeed.

Check status:

```bash
docker compose ps
```

Inspect startup logs:

```bash
docker compose logs --tail=200 db migrate app
```

The app is intentionally published only on loopback:

```text
127.0.0.1:5000
```

Local readiness checks:

```bash
curl --fail http://127.0.0.1:5000/livez
curl --fail http://127.0.0.1:5000/readyz
```

Do not expose port 5000 directly to the internet.

## 8. HTTPS and domain setup

Production access must use HTTPS. The intended canonical URL is:

```text
https://hirkanet.com
```

Required DNS records:

- `hirkanet.com` points to the server
- `www.hirkanet.com` points to the same server or aliases the apex domain

Required proxy behavior:

- Redirect all HTTP requests to HTTPS
- Redirect `https://www.hirkanet.com` to `https://hirkanet.com`
- Proxy the canonical HTTPS site to `http://127.0.0.1:5000`
- Set `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host`
- Permit only one trusted proxy hop, matching the application `ProxyFix` configuration

An Nginx example is provided at:

```text
deployment/nginx/hirkanet.conf
```

Read `HTTPS-DEPLOYMENT.md` before enabling HSTS. Confirm HTTPS and certificate renewal first, because an incorrect HSTS configuration can lock clients out.

Production firewall exposure should normally be limited to:

```text
TCP 22   administration, restricted by source
TCP 80   redirect and ACME validation
TCP 443  public application
```

PostgreSQL, Gunicorn port 5000, Elasticsearch, Logstash, and Kibana must not be publicly exposed.

## 9. Start the optional Elastic observability stack

Start it independently:

```bash
docker compose -f docker-compose.elastic.yml up -d
```

Follow startup logs:

```bash
docker compose -f docker-compose.elastic.yml logs -f \
  elastic-certs-setup elasticsearch elastic-init logstash kibana filebeat
```

Check status:

```bash
docker compose -f docker-compose.elastic.yml ps
```

Local endpoints:

```text
Elasticsearch: https://127.0.0.1:9200
Kibana:        https://127.0.0.1:5601
```

The Elastic stack creates and retains its own private CA. Normal startup must never replace an existing trust root. If CA material is incomplete, startup fails closed. Use the documented explicit rotation command only after reviewing `ELK-SETUP.md`:

```bash
./elk/rotate-elastic-ca.sh --confirm-trust-root-rotation
```

Filebeat discovers Hirkanet application and database logs through Docker metadata labels. The two Compose projects do not need a shared application network.

## 10. FortiGate collection setup

Before running the collector, create a FortiGate REST API administrator/token with the minimum required read permissions.

Set variables outside source control:

```bash
export FORTIGATE_HOST=192.0.2.10
export FORTIGATE_TOKEN='replace-with-real-token'
export FORTIGATE_VDOM=root
```

Run the collector from the project root or from an appropriately managed host environment:

```bash
python collectors/fortigate_collector.py
```

The collector publishes immutable, versioned snapshots under `data/snapshots/` and atomically updates `data/current.json`. Read `FORTIGATE-SNAPSHOTS.md` before changing retention or restoring a snapshot.

## 11. First-login and application checks

After startup:

1. Open `https://hirkanet.com` through the configured proxy.
2. Log in with `BOOTSTRAP_ADMIN_USERNAME` and the value stored in `secrets/bootstrap_admin_password`.
3. Change or rotate the bootstrap credentials according to your administrative policy.
4. Confirm the admin dashboard loads.
5. Confirm the default policy-evaluation service exists.
6. Confirm a client without a subscription cannot access a restricted service.
7. Run a representative policy evaluation against the active FortiGate snapshot.

Evaluation results are heuristic policy recommendations, not a complete FortiGate packet-flow simulation.

## 12. Required post-deployment operations

Run a verified PostgreSQL backup:

```bash
./scripts/postgres-backup.sh
```

Run storage monitoring:

```bash
./scripts/storage-monitor.py
```

Preview retention actions:

```bash
./scripts/storage-retention.py
```

Apply retention only after reviewing the preview:

```bash
./scripts/storage-retention.py --apply
```

Copy successful PostgreSQL backup sets and sensitive FortiGate snapshot backups to encrypted off-host storage.

## 13. Normal lifecycle commands

Application stack:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
docker compose down
```

Elastic stack:

```bash
docker compose -f docker-compose.elastic.yml up -d
docker compose -f docker-compose.elastic.yml ps
docker compose -f docker-compose.elastic.yml down
```

Do not run the following in production unless permanent data deletion is intended:

```bash
docker compose down -v
docker compose -f docker-compose.elastic.yml down -v
```

The `-v` option removes named volumes, including PostgreSQL or Elastic data.

## 14. Local development without Docker

Install dependencies in a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

When PostgreSQL environment variables are absent, the application may use its local SQLite development database. Migrations are still required:

```bash
python3 -m flask --app api.app db upgrade
python3 -m flask --app api.app seed-defaults
python3 api/app.py
```

The Flask development server and debugger must never be used in production. Production uses Gunicorn through Docker Compose.

## 15. Common startup failures

### `.env` not found

```text
env file .../.env not found
```

Fix:

```bash
cp .env.example .env
```

Then review every setting.

### Secret bind source does not exist

```text
invalid mount config ... secrets/postgres_password
```

Create the extensionless secret file and ensure it is non-empty:

```bash
openssl rand -hex 32 > secrets/postgres_password
chmod 600 secrets/postgres_password
```

### PostgreSQL variables default to blank

```text
POSTGRES_USER variable is not set
POSTGRES_DB variable is not set
```

Set both values in `.env` and rerun:

```bash
docker compose config
```

### Missing database table

```text
no such table: blog_posts
```

The schema has not been migrated. For local development:

```bash
python3 -m flask --app api.app db upgrade
python3 -m flask --app api.app seed-defaults
```

For Docker:

```bash
docker compose run --rm migrate
```

### Filebeat image cannot be pulled

Use the official registry path configured in `docker-compose.elastic.yml`:

```text
docker.elastic.co/beats/filebeat:<STACK_VERSION>
```

Verify that `STACK_VERSION` exists and is consistent across all Elastic components.

## 16. Final preflight checklist

Before declaring the deployment ready, confirm:

- [ ] `.env` exists and contains non-secret configuration.
- [ ] All required secret files exist, are non-empty, and have restrictive permissions.
- [ ] `docker compose config` succeeds for both Compose files.
- [ ] Writable directories exist with correct ownership.
- [ ] DNS resolves for both domains.
- [ ] HTTPS certificates are valid and auto-renewal is tested.
- [ ] Only ports 80/443 and restricted administration ports are public.
- [ ] `db`, `migrate`, and `app` complete or become healthy.
- [ ] `/livez` and `/readyz` succeed.
- [ ] Database migrations are at the latest revision.
- [ ] A verified PostgreSQL backup has completed.
- [ ] Off-host backup replication is configured.
- [ ] Storage monitoring is scheduled and alerts are routed externally.
- [ ] FortiGate snapshots publish atomically and `data/current.json` is valid.
- [ ] Elastic TLS and ILM checks succeed when the optional stack is enabled.
