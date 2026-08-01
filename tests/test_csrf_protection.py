import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_enables_global_csrf_protection():
    source = (PROJECT_ROOT / "api" / "app.py").read_text(encoding="utf-8")
    assert "from flask_wtf.csrf import CSRFProtect, CSRFError" in source
    assert "csrf = CSRFProtect(app)" in source
    assert "@app.errorhandler(CSRFError)" in source


def test_logout_route_is_post_only():
    source = (PROJECT_ROOT / "api" / "app.py").read_text(encoding="utf-8")
    assert '@app.route("/logout", methods=["POST"])' in source
    assert '@app.route("/logout", methods=["GET", "POST"])' not in source


def test_every_post_form_template_contains_csrf_token():
    missing = []
    for template in (PROJECT_ROOT / "templates").rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        for match in re.finditer(r"<form\b[^>]*method=[\"']POST[\"'][^>]*>", text, re.I):
            closing = text.find("</form>", match.end())
            body = text[match.end():closing if closing != -1 else len(text)]
            if "csrf_token" not in body and "form.hidden_tag()" not in body:
                missing.append(str(template.relative_to(PROJECT_ROOT)))
    assert missing == []


def test_no_logout_get_links_remain():
    offenders = []
    pattern = re.compile(r'<a\b[^>]*href="\{\{\s*url_for\([\"\']logout[\"\']\)\s*\}\}"', re.I)
    for template in (PROJECT_ROOT / "templates").rglob("*.html"):
        if pattern.search(template.read_text(encoding="utf-8")):
            offenders.append(str(template.relative_to(PROJECT_ROOT)))
    assert offenders == []


def test_modified_python_files_parse():
    for path in [PROJECT_ROOT / "api" / "app.py"]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
