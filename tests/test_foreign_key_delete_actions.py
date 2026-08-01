from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_models_define_database_delete_actions():
    models = (ROOT / "models.py").read_text(encoding="utf-8")
    assert 'ForeignKey("users.id", ondelete="CASCADE")' in models
    assert 'ForeignKey("services.id", ondelete="CASCADE")' in models
    assert 'ForeignKey("blog_categories.id", ondelete="SET NULL")' in models
    assert 'ForeignKey("users.id", ondelete="SET NULL")' in models


def test_owned_relationships_use_delete_orphan_and_passive_deletes():
    models = (ROOT / "models.py").read_text(encoding="utf-8")
    assert models.count('cascade="all, delete-orphan"') >= 2
    assert models.count("passive_deletes=True") >= 3


def test_migration_applies_all_delete_actions():
    migration = (
        ROOT / "migrations" / "versions" / "20260731_0002_foreign_key_delete_actions.py"
    ).read_text(encoding="utf-8")
    assert migration.count('"CASCADE"') >= 2
    assert migration.count('"SET NULL"') >= 2
    assert 'down_revision = "20260731_0001"' in migration


def test_routes_rely_on_database_constraints_not_manual_cleanup():
    routes = (ROOT / "admin" / "routes.py").read_text(encoding="utf-8")
    assert "Subscription.query.filter_by(user_id=user.id).delete()" not in routes
    assert "Subscription.query.filter_by(service_id=svc.id).delete()" not in routes
    assert 'BlogPost.query.filter_by(category_id=cat.id).update({"category_id": None})' not in routes
