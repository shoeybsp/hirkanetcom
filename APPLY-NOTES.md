# Applying the multi-device changes

30 files: 21 modified, 9 new. No files are deleted or renamed.

## Apply

From the root of your git repo, with a clean working tree:

    git checkout -b multi-device-support
    unzip -o hirkanet-multidevice-overlay.zip -d .
    git status          # should show 21 modified, 9 untracked
    git diff            # review before committing

## New files (9)

    secret_crypto.py
    collectors/__init__.py
    collectors/sync_service.py
    migrations/versions/20260802_0005_device_inventory.py
    templates/admin/device_list.html
    templates/admin/device_form.html
    templates/admin/device_assignments.html
    tests/test_device_sync_service.py
    tests/test_device_selection_authorization.py

## Modified files (21)

    admin/routes.py                 device CRUD, sync, assignment routes
    client/access.py                get_assigned_devices, has_device_access
    client/routes.py                per-device engine cache + selection
    models.py                       Device, DeviceAssignment, sqlite FK pragma
    requirements.txt                + cryptography==43.0.3
    validation/admin.py             validate_device, assignment id validation
    validation/common.py            host_address, bounded_int
    templates/admin/*.html          10 files: "Devices" nav link only
    templates/admin/dashboard.html  nav link + device stat card
    templates/client/*.html         3 files: device selector / device label

## After applying

1. pip install -r requirements.txt        (adds cryptography)
2. Set DEVICE_CREDENTIAL_KEY in your environment / .env / secrets.
   Required in production; falls back to a dev-only key otherwise.
   Losing or changing this key makes stored device API keys undecryptable.
3. flask --app api.app db upgrade         (creates devices, device_assignments)
4. flask --app api.app seed-defaults      (registers existing data/ as
                                           "Default FortiGate"; idempotent)

## Notes

- SHA256SUMS in the repo root is now stale for any file it covers that
  changed here. Regenerate it if you use it for integrity verification.
- The migration is additive and reversible (`db downgrade 20260801_0004`).
- No existing snapshot files are moved. The pre-existing data/ directory is
  registered as a device in place.
