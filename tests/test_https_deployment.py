from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_app_remains_loopback_only_in_compose():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert compose["services"]["app"]["ports"] == ["127.0.0.1:5000:5000"]


def test_proxy_and_trusted_hosts_are_explicit():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    environment = compose["services"]["app"]["environment"]
    assert "TRUST_PROXY_HEADERS" in environment
    assert "TRUSTED_HOSTS" in environment
    assert "hirkanet.com" in environment["TRUSTED_HOSTS"]
    assert "www.hirkanet.com" in environment["TRUSTED_HOSTS"]


def test_flask_uses_one_hop_proxy_fix_and_trusted_hosts():
    source = (ROOT / "api" / "app.py").read_text()
    assert "ProxyFix" in source
    assert "x_for=1" in source
    assert "x_proto=1" in source
    assert "x_host=1" in source
    assert "x_port=1" in source
    assert "TRUSTED_HOSTS=trusted_hosts" in source
    assert 'PREFERRED_URL_SCHEME="https" if env == "production" else "http"' in source


def test_nginx_canonicalizes_both_domains_and_proxies_loopback():
    config = (ROOT / "deployment" / "nginx" / "hirkanet.conf").read_text()
    assert "server_name hirkanet.com www.hirkanet.com;" in config
    assert "server_name www.hirkanet.com;" in config
    assert "server_name hirkanet.com;" in config
    assert "return 301 https://hirkanet.com$request_uri;" in config
    assert "server 127.0.0.1:5000;" in config
    assert "proxy_set_header X-Forwarded-Proto https;" in config
    assert "Strict-Transport-Security" in config


def test_https_documentation_covers_operational_requirements():
    guide = (ROOT / "HTTPS-DEPLOYMENT.md").read_text()
    required = [
        "https://hirkanet.com",
        "www.hirkanet.com",
        "DNS prerequisites",
        "certbot renew --dry-run",
        "Do not publish port `5000`",
        "TRUST_PROXY_HEADERS=true",
        "direct public access to `:5000` is impossible",
    ]
    for text in required:
        assert text in guide
