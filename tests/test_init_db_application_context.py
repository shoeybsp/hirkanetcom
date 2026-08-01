from pathlib import Path


def test_init_db_does_not_rollback_scoped_session_outside_app_context():
    source = Path('models.py').read_text(encoding='utf-8')
    start = source.index('def init_db(app):')
    end = source.index('\ndef seed_defaults', start)
    init_db_source = source[start:end]

    assert 'db.session.rollback()' not in init_db_source
    assert 'with app.app_context()' in init_db_source
    assert 'with db.engine.connect() as connection' in init_db_source
    assert 'connection.execute(text("SELECT 1"))' in init_db_source
