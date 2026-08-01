# Split Docker Compose deployment

Hirkanet now uses two independent Compose projects.

## 1. Application stack

File: `docker-compose.yml`

Services:

- `db`
- `migrate` (one-shot Alembic upgrade and idempotent seed)
- `app`

Start it with:

```bash
docker compose up -d --build
```

Inspect it with:

```bash
docker compose ps
docker compose logs -f app db
docker compose logs migrate
```

Stop it with:

```bash
docker compose down
```

This operation does not stop or remove the Elastic stack.

## 2. Observability stack

File: `docker-compose.elastic.yml`

Services:

- `elastic-certs-setup`
- `elasticsearch`
- `elastic-init`
- `logstash`
- `kibana`
- `filebeat`

Start it independently with:

```bash
docker compose -f docker-compose.elastic.yml up -d
```

Inspect it with:

```bash
docker compose -f docker-compose.elastic.yml ps
docker compose -f docker-compose.elastic.yml logs -f
```

Stop it with:

```bash
docker compose -f docker-compose.elastic.yml down
```

## Log collection between projects

The two projects do not share a Docker network. Filebeat reads Docker JSON logs from the host and uses Docker metadata labels to select Hirkanet application and database containers:

- `hirkanet_log_role=application`
- `hirkanet_log_role=database`

Therefore:

- the application does not need direct network access to Logstash;
- the database does not need direct network access to the Elastic stack;
- Filebeat can start before or after the application stack;
- both stacks must run on the same Docker host for this Filebeat configuration.

## Recommended startup order

```bash
docker compose up -d --build
docker compose -f docker-compose.elastic.yml up -d
```

The `app` service starts only after the one-shot `migrate` service completes successfully. Database schema changes are managed by Flask-Migrate/Alembic; see `DATABASE-MIGRATIONS.md`.

The stacks can be restarted and upgraded independently.

## Configuration validation

```bash
docker compose config
docker compose -f docker-compose.elastic.yml config
```

## Destructive cleanup

Application data only:

```bash
docker compose down -v
```

Elastic data only:

```bash
docker compose -f docker-compose.elastic.yml down -v
```

Do not use `-v` unless deleting the corresponding persistent data is intentional.
