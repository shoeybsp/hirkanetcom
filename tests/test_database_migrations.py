from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_flask_migrate_dependency_and_environment_exist():
    requirements = (ROOT / "requirements.txt").read_text()
    assert "Flask-Migrate==" in requirements
    assert (ROOT / "migrations" / "env.py").is_file()
    assert (ROOT / "migrations" / "versions" / "20260731_0001_initial_schema.py").is_file()


def test_application_startup_does_not_create_schema_implicitly():
    models = (ROOT / "models.py").read_text()
    app = (ROOT / "api" / "app.py").read_text()
    assert "db.create_all()" not in models
    assert "Migrate(app, db" in app
    assert '@app.cli.command("seed-defaults")' in app


def test_compose_runs_migrations_before_gunicorn():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    migrate = services["migrate"]
    command = " ".join(migrate["command"])
    assert "flask --app api.app db upgrade" in command
    assert "flask --app api.app seed-defaults" in command
    assert migrate["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["app"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


def test_baseline_migration_is_non_destructive_for_existing_tables():
    revision = (ROOT / "migrations" / "versions" / "20260731_0001_initial_schema.py").read_text()
    assert 'if "users" not in tables' in revision
    assert 'if "services" not in tables' in revision
    assert 'if "subscriptions" not in tables' in revision
    assert 'if "blog_categories" not in tables' in revision
    assert 'if "blog_posts" not in tables' in revision


def test_migration_documentation_covers_backup_and_revision_workflow():
    guide = (ROOT / "DATABASE-MIGRATIONS.md").read_text()
    for expected in [
        "pg_dump",
        "flask --app api.app db migrate",
        "flask --app api.app db upgrade",
        "flask --app api.app db current",
        "Existing installations",
    ]:
        assert expected in guide
