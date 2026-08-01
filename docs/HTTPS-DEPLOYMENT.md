# HTTPS Deployment for hirkanet.com

Hirkanet's application container is deliberately published only on the host loopback interface:

```text
127.0.0.1:5000 -> app:5000
```

It must not be exposed directly to the public internet. A host-level reverse proxy terminates TLS and serves both `hirkanet.com` and `www.hirkanet.com`.

## Canonical domain

`https://hirkanet.com` is the canonical public URL. Requests to either of these locations are redirected to it while preserving the path and query string:

- `http://hirkanet.com`
- `http://www.hirkanet.com`
- `https://www.hirkanet.com`

This avoids duplicate origins and keeps authentication cookies host-scoped to the canonical domain.

## DNS prerequisites

Create public DNS records for both names pointing to the reverse-proxy host:

```text
A     hirkanet.com       <server IPv4>
A     www.hirkanet.com   <server IPv4>
AAAA  hirkanet.com       <server IPv6>      # only when IPv6 is configured
AAAA  www.hirkanet.com   <server IPv6>      # only when IPv6 is configured
```

Do not publish port `5000`. Public ingress should be limited to TCP ports `80` and `443`.

## Application environment

The Compose configuration enables trusted proxy processing for one reverse-proxy hop:

```env
APP_ENV=production
TRUST_PROXY_HEADERS=true
TRUSTED_HOSTS=hirkanet.com,www.hirkanet.com,localhost,127.0.0.1
```

`ProxyFix` trusts exactly one value for `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Port`. Do not enable `TRUST_PROXY_HEADERS` when the application is directly reachable by untrusted clients, because clients could forge those headers.

In production Hirkanet also sets:

- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Lax`
- preferred external URL scheme `https`
- Flask trusted-host validation for the configured domain list

## Nginx deployment

A complete host-level configuration is provided at:

```text
deployment/nginx/hirkanet.conf
```

Install it into the Nginx configuration directory, validate it, and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

The configuration:

- redirects HTTP to HTTPS;
- redirects `www.hirkanet.com` to `hirkanet.com`;
- proxies only the canonical HTTPS virtual host to `127.0.0.1:5000`;
- supplies the forwarding headers expected by Hirkanet;
- enables HSTS after HTTPS is working;
- limits request bodies to 5 MB, matching the application upload limit.

## TLS certificate

The certificate must cover both names:

```text
hirkanet.com
www.hirkanet.com
```

For Certbot with the Nginx plugin:

```bash
sudo certbot --nginx -d hirkanet.com -d www.hirkanet.com
```

Confirm automated renewal:

```bash
sudo certbot renew --dry-run
```

Do not enable HSTS until both hostnames serve valid HTTPS and certificate renewal is confirmed. The supplied Nginx file includes HSTS, so comment out that header during initial certificate provisioning if necessary.

## Firewall and exposure

Recommended public exposure:

```text
80/tcp   reverse proxy only
443/tcp  reverse proxy only
```

Keep these services private or loopback-bound:

```text
5000/tcp Hirkanet/Gunicorn
5601/tcp Kibana
9200/tcp Elasticsearch
5432/tcp PostgreSQL
5044/tcp Logstash Beats input
```

## Verification

After deployment, verify:

```bash
curl -I http://hirkanet.com/
curl -I https://www.hirkanet.com/
curl -I https://hirkanet.com/
```

Expected behavior:

- both HTTP URLs redirect to `https://hirkanet.com/...`;
- the HTTPS `www` URL redirects to the apex domain;
- the apex HTTPS URL returns the Hirkanet response;
- responses include `Strict-Transport-Security` after HSTS is enabled;
- login cookies contain `Secure`, `HttpOnly`, and `SameSite=Lax`.

Also verify that direct public access to `:5000` is impossible.

## Alternative reverse proxies

Caddy, HAProxy, Traefik, or a managed load balancer may be used instead of Nginx, but they must provide the same contract:

1. terminate TLS for both domains;
2. redirect all traffic to `https://hirkanet.com`;
3. proxy to `127.0.0.1:5000`;
4. overwrite, rather than append untrusted, forwarded headers;
5. preserve the original host and client address;
6. perform certificate renewal automatically.
