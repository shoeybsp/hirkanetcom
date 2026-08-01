from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_json_user_store_is_removed():
    assert not (PROJECT_ROOT / "auth" / "user_store.py").exists()
    assert not (PROJECT_ROOT / "data" / "users.json").exists()


def test_auth_package_does_not_export_file_backed_store():
    source = (PROJECT_ROOT / "auth" / "__init__.py").read_text(encoding="utf-8")
    forbidden = ("UserStore", "user_store", "users.json")
    assert not any(token in source for token in forbidden)


def test_no_source_reference_to_legacy_user_store():
    forbidden = ("auth.user_store", "from .user_store", '"users.json"', "'users.json'")
    offenders = []

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".md", ".yml", ".yaml", ".html"}:
            continue
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
