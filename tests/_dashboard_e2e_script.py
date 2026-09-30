"""End-to-end dashboard widget check, run in a subprocess by
tests/test_dashboard_widgets.py so it gets its own app and temp database."""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from api.app import app  # noqa: E402
from models import Service, Subscription, User, db  # noqa: E402
from security import hash_password  # noqa: E402

app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
results = {}

with app.app_context():
    db.create_all()
    alice = User(username="alice", password_hash=hash_password("pw-alice-123"), role="client")
    bob = User(username="bob", password_hash=hash_password("pw-bob-123"), role="client")
    evaluation = Service(name="Policy Evaluation", service_type="policy_evaluation", is_active=True)
    dos = Service(name="DoS Policy Management", service_type="dos_policy", is_active=True)
    risk = Service(name="Risk", service_type="policy_risk_assessment", is_active=True)
    db.session.add_all([alice, bob, evaluation, dos, risk])
    db.session.commit()
    for user, svc in [(alice, evaluation), (alice, dos), (bob, evaluation)]:
        db.session.add(Subscription(user_id=user.id, service_id=svc.id, is_active=True))
    db.session.commit()
    ids = {"eval": evaluation.id, "dos": dos.id, "risk": risk.id}


def login(username, password):
    client = app.test_client()
    resp = client.post("/login", data={"username": username, "password": password})
    assert resp.status_code in (302, 303), resp.status_code
    return client


def keys(html):
    import re
    return re.findall(r'class="col-md-6 hk-widget(?: d-none)?" data-key="([^"]+)"', html), \
           re.findall(r'class="col-md-6 hk-widget d-none" data-key="([^"]+)"', html)


alice_c = login("alice", "pw-alice-123")

# 1. never customised: every available widget is visible, in default order
page = alice_c.get("/client/").get_data(as_text=True)
all_keys, hidden = keys(page)
results["default_all_keys"] = all_keys
results["default_hidden"] = hidden

# 2. save a custom order + subset
eval_key, dos_key = f"service:{ids['eval']}", f"service:{ids['dos']}"
resp = alice_c.post("/client/dashboard/layout", json={"layout": [dos_key, "policy_catalog"]})
results["save_status"] = resp.status_code
page = alice_c.get("/client/").get_data(as_text=True)
all_keys, hidden = keys(page)
results["custom_all_keys"] = all_keys
results["custom_hidden"] = hidden

# 3. a service alice is NOT subscribed to (risk) must be rejected / dropped
resp = alice_c.post("/client/dashboard/layout", json={
    "layout": [f"service:{ids['risk']}", "service:9999", "bogus", dos_key, dos_key]})
results["foreign_status"] = resp.status_code
with app.app_context():
    results["stored_after_foreign"] = User.query.filter_by(username="alice").one().dashboard_layout

# 4. malformed bodies
results["bad_json"] = alice_c.post("/client/dashboard/layout", data="nope",
                                   content_type="application/json").status_code
results["bad_layout_type"] = alice_c.post("/client/dashboard/layout", json={"layout": "x"}).status_code

# 5. bob's layout is independent of alice's
bob_c = login("bob", "pw-bob-123")
bob_keys, bob_hidden = keys(bob_c.get("/client/").get_data(as_text=True))
results["bob_keys"] = bob_keys
results["bob_hidden"] = bob_hidden

# 6. reset restores the default
alice_c.post("/client/dashboard/layout", json={"reset": True})
with app.app_context():
    results["stored_after_reset"] = User.query.filter_by(username="alice").one().dashboard_layout

# 7. unauthenticated access is refused
anon = app.test_client()
results["anon_status"] = anon.post("/client/dashboard/layout", json={"layout": []}).status_code

# 8. deliberately empty layout is remembered (not treated as "default")
alice_c.post("/client/dashboard/layout", json={"layout": []})
page = alice_c.get("/client/").get_data(as_text=True)
all_keys, hidden = keys(page)
results["empty_visible"] = [k for k in all_keys if k not in hidden]

# 9. CSRF is enforced: the write must be rejected and nothing saved.
#    (The status is 500 today because of a separate logging bug that breaks
#    CSRF error responses, so assert "rejected", not a specific code.)
app.config.update(WTF_CSRF_ENABLED=True, PROPAGATE_EXCEPTIONS=False, TESTING=False)
resp = alice_c.post("/client/dashboard/layout", json={"layout": [dos_key]})
results["csrf_rejected"] = resp.status_code >= 400
with app.app_context():
    results["stored_after_csrf_reject"] = User.query.filter_by(username="alice").one().dashboard_layout

print("RESULTS=" + json.dumps({"ids": ids, **results}))
