# Archive and Container Image Distribution Audit

## Objective

Identify every person, system, registry, storage location, and communication channel that received or could retrieve a project archive or container image containing secrets or FortiGate operational data.

## Important limitation

The application repository cannot determine historical recipients by itself. Recipient attribution requires audit logs from the systems used to build, store, upload, share, download, email, message, or deploy the artifact.

## 1. Fingerprint the exposed artifacts

Run:

```bash
python scripts/audit_artifact_distribution.py \
  /path/to/hirkanet.com.zip \
  --search-root /srv \
  --search-root /home \
  --output artifact-distribution-audit.json
```

Record the SHA-256 hash, byte size, original filename, creation time, and known image digest/tag. Preserve the generated report as incident evidence.

## 2. Collect recipient evidence

Check each applicable source and export immutable logs before retention windows expire:

- Email sent items, attachment access logs, and secure-mail gateway logs
- Chat or collaboration uploads and download/member-access logs
- Cloud drive and object-storage sharing, access, and download logs
- CI/CD job artifacts, runners, caches, logs, and artifact-download events
- Container registry push, pull, token, repository, and retention logs
- Git hosting releases, packages, LFS objects, clones, forks, and access logs
- Reverse proxy, VPN, bastion, SFTP, SCP, SMB, NAS, and endpoint telemetry
- Backup systems, support portals, ticket attachments, and external contractors
- Local Docker hosts: image IDs, RepoDigests, tags, creation times, and running/stopped containers

## 3. Build the recipient register

For every event, record:

| Field | Required evidence |
|---|---|
| Recipient/person or service account | Account identity from authoritative logs |
| Organization/team | Employer or owning team |
| Artifact | Filename and SHA-256, or image digest |
| Channel | Email, drive, registry, CI, chat, removable media, etc. |
| Action | Uploaded, shared, downloaded, pulled, copied, or deployed |
| Timestamp and timezone | Original log timestamp |
| Source IP/device | When available |
| Current possession | Confirmed deleted, quarantined, unknown, or retained |
| Evidence reference | Export filename, event ID, ticket, or screenshot |
| Follow-up owner | Named incident owner |

Do not infer recipients from informal recollection when authoritative logs exist.

## 4. Containment actions

- Revoke public/shared links and artifact tokens.
- Delete CI artifacts, registry tags/manifests, release assets, and shared copies.
- Ask confirmed recipients to delete local copies and provide written confirmation.
- Quarantine endpoints where unauthorized copying is suspected.
- Rotate all secrets contained in or derivable from the artifact.
- Rebuild container images with a clean build context and new secrets.
- Invalidate active sessions after rotating the Flask secret key.
- Preserve relevant logs and evidence before deletion or account changes.

Deleting a tag is not sufficient if the registry still retains the manifest or layers. Verify garbage collection and digest unavailability.

## 5. Verification and closure

The audit is complete only when:

1. All known distribution channels have been checked.
2. Every identified recipient or service account has a disposition.
3. Secret rotation is complete and verified.
4. Old image digests and archives are no longer retrievable.
5. Residual unknowns, missing logs, and expired retention windows are documented.
6. An incident owner approves closure.

## Application authorization change

Policy-evaluation execution endpoints now require an active subscription to an active `policy_evaluation` service. Unauthorized authenticated requests receive HTTP 403 and produce a structured `subscription_authorization_denied` warning log.
