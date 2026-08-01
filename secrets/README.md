# Runtime secrets

Create the following extensionless files before starting Docker Compose:

- `postgres_password`
- `flask_secret_key`
- `bootstrap_admin_password`
- `elastic_password`
- `kibana_password`
- `logstash_password`
- `kibana_security_encryption_key`
- `kibana_saved_objects_encryption_key`
- `kibana_reporting_encryption_key`

Copy each matching `.example` file, replace its placeholder, and restrict access:

```bash
chmod 700 secrets
chmod 600 secrets/*
```

The three Kibana encryption keys and the Flask secret key should each contain at least 32 random characters. The bootstrap admin password is only used when creating the initial administrator.
