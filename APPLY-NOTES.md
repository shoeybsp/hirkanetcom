# Housekeeping patch (supersedes hirkanet-permission-fix.zip and
# hirkanet-architecture-update.zip - use this one instead of those)

Four files, all drop-in replacements:

    Dockerfile               pinned uid/gid 10001 + explicit data/uploads/
                              static-uploads dir creation
    requirements.txt          + PyYAML==6.0.3 (missing test dependency)
    docs/architecture.md      rewritten to reflect current codebase +
                              the named-volume data mount
    docs/depoly-readme.md     corrected first-time setup instructions for
                              the named-volume data mount

## Apply

    cp Dockerfile /path/to/hirkanet/Dockerfile
    cp requirements.txt /path/to/hirkanet/requirements.txt
    cp docs/architecture.md /path/to/hirkanet/docs/architecture.md
    cp docs/depoly-readme.md /path/to/hirkanet/docs/depoly-readme.md

## What changed and why (chronological)

1. Dockerfile: pinned the container user to uid=10001, gid=10001 (was
   auto-assigned by the base image, unstable across rebuilds) - fixes
   "Sync Now" failing with a bind-mount permission error.
2. requirements.txt: added PyYAML, which several tests need to parse
   docker-compose.yml directly. It was missing entirely; only appeared to
   work in prior testing because an unrelated tool pulled it in as a
   transitive dependency. Verified broken from, and then fixed in, a
   genuinely clean venv.
3. Dockerfile: added explicit `mkdir -p /app/data /app/uploads
   /app/static/uploads` before the chown, so those paths reliably exist
   in the image with correct ownership on every build - needed once
   `data` became a named volume (see next point), since Docker only
   auto-populates a named volume's ownership from a path that already
   exists in the image.
4. docs/depoly-readme.md + architecture.md: updated to describe the real,
   current setup after `data` was switched from a host bind mount to the
   named volume `hirkanet_data:/app/data` in docker-compose.yml - data
   needs no host-side chown anymore; uploads/static-uploads still do.

## On your machine

    docker compose down
    sudo chown -R 10001:10001 ./uploads ./static/uploads
    docker compose up -d --build
    docker compose exec app id                 # uid=10001(app) gid=10001(app)
    docker volume ls | grep hirkanet            # hirkanet-app_hirkanet_data
    pip install -r requirements.txt             # if running tests locally, picks up PyYAML
