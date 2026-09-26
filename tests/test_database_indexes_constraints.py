from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "versions" / "20260731_0003_indexes_and_check_constraints.py"


def test_models_define_database_check_constraints():
    models = (ROOT / "models.py").read_text(encoding="utf-8")
    for name in [
        "ck_users_role",
        "ck_services_service_type_not_blank",
        "ck_subscriptions_valid_date_range",
        "uq_subscriptions_user_service",
    ]:
        assert name in models


def test_models_define_query_indexes():
    models = (ROOT / "models.py").read_text(encoding="utf-8")
    for name in [
        "ix_services_type_active",
        "ix_subscriptions_user_active",
        "ix_subscriptions_service_active",
    ]:
        assert name in models


def test_migration_adds_constraints_and_indexes_after_fk_revision():
    migration = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "20260731_0002"' in migration
    assert "_validate_existing_data()" in migration
    assert "duplicate user/service pairs" in migration
    assert "op.create_check_constraint" in migration
    assert "op.create_unique_constraint" in migration
    assert "op.create_index" in migration


def test_migration_fails_closed_instead_of_rewriting_invalid_rows():
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "UPDATE users" not in migration
    assert "DELETE FROM subscriptions" not in migration
    assert "Correct the data and rerun flask db upgrade" in migration
