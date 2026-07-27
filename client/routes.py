import csv
import io
import sys
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
)
from flask_login import login_required, current_user
from models import db, Service, Subscription
from engine.evaluator import SecureTrackLite

client_bp = Blueprint("client", __name__, url_prefix="/client")


# -- Helpers (from original app.py) -------------------------------------------

def clean_list(s):
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def address_value(address):
    if address.get("group"):
        return ", ".join(
            member.get("name", member) if isinstance(member, dict) else member
            for member in address.get("group", [])
        )
    if "subnet" in address:
        return address["subnet"].replace(" ", "/")
    if "iprange" in address:
        return address["iprange"].split()[0] + "/32"
    if address.get("type") == "all":
        return "0.0.0.0/0"
    return ""


def service_value(service):
    if service.get("group"):
        return "Group"
    protocol = service.get("protocol", "")
    tcp_port = service.get("tcp-portrange", "")
    udp_port = service.get("udp-portrange", "")
    if protocol and tcp_port:
        return f"{protocol}/{tcp_port}"
    if protocol and udp_port:
        return f"{protocol}/{udp_port}"
    return protocol


# -- Engine (lazy) ------------------------------------------------------------

_engine = None


def ensure_engine():
    global _engine
    if _engine is None:
        try:
            _engine = SecureTrackLite()
        except Exception as e:
            print("Failed to initialize SecureTrackLite engine:", e, file=sys.stderr)
            _engine = None
    return _engine


# =============================================================================
# Client Dashboard
# =============================================================================


def get_subscribed_services():
    """Return the list of services the current user is subscribed to."""
    subs = (
        db.session.query(Service)
        .join(Subscription, Subscription.service_id == Service.id)
        .filter(
            Subscription.user_id == current_user.id,
            Subscription.is_active == True,
            Service.is_active == True,
        )
        .all()
    )
    return subs


@client_bp.route("/")
@login_required
def dashboard():
    """Client dashboard showing available services based on subscriptions."""
    services = get_subscribed_services()
    return render_template("client/dashboard.html", services=services)


# =============================================================================
# Policy Evaluation Service (for subscribed clients)
# =============================================================================


@client_bp.route("/policy-evaluation")
@login_required
def policy_evaluation():
    """Policy evaluation page - requires subscription to policy_evaluation service."""
    # Check subscription
    subscribed = (
        db.session.query(Subscription)
        .join(Service)
        .filter(
            Subscription.user_id == current_user.id,
            Service.service_type == "policy_evaluation",
            Subscription.is_active == True,
            Service.is_active == True,
        )
        .first()
    )
    if not subscribed:
        flash("You do not have access to the Policy Evaluation service.", "error")
        return redirect(url_for("client.dashboard"))

    engine_inst = ensure_engine()
    if not engine_inst:
        return render_template("client/policy_evaluation.html", addresses=[], services=[])

    addresses = sorted(
        (
            {
                "name": address["name"],
                "value": address_value(address),
                "type": address.get("type", "address"),
            }
            for address in engine_inst.addresses
            if address.get("name") and address_value(address)
        ),
        key=lambda address: address["name"].lower(),
    )
    services_list = sorted(
        (
            {
                "name": svc["name"],
                "value": service_value(svc),
            }
            for svc in engine_inst.services
            if svc.get("name")
        ),
        key=lambda svc: svc["name"].lower(),
    )
    return render_template(
        "client/policy_evaluation.html",
        addresses=addresses,
        services=services_list,
    )


@client_bp.route("/policy-evaluation/results", methods=["POST"])
@login_required
def policy_evaluation_results():
    """Evaluate policies and show results."""
    src = clean_list(request.form.get("src"))
    dst = clean_list(request.form.get("dst"))
    svc = clean_list(request.form.get("service"))

    eng = ensure_engine()
    if not eng:
        return "Engine not available; ensure data files exist.", 500

    res = eng.evaluate(src, dst, svc)
    best = res[0] if res else None

    return render_template(
        "client/results.html",
        results=res,
        best=best,
        is_batch=False,
        query_src=src,
        query_dst=dst,
        query_service=svc,
    )


@client_bp.route("/policy-evaluation/batch-results", methods=["POST"])
@login_required
def policy_evaluation_batch():
    """Accept a CSV file with source,destination,port lines and evaluate each."""
    eng = ensure_engine()
    if not eng:
        return "Engine not available; ensure data files exist.", 500

    if "csv_file" not in request.files:
        return "No CSV file uploaded.", 400

    file = request.files["csv_file"]
    if file.filename == "":
        return "No file selected.", 400

    stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
    reader = csv.reader(stream)

    rows = list(reader)
    if not rows:
        return "CSV file is empty.", 400

    header_keywords = {"source", "src", "destination", "dst", "dest", "port", "service", "svc"}
    has_header = any(
        any(kw in col.lower().strip() for kw in header_keywords)
        for col in rows[0]
    )

    if has_header:
        rows = rows[1:]

    batch_results = []
    for i, row in enumerate(rows):
        if len(row) < 2:
            continue
        src_val = row[0].strip()
        dst_val = row[1].strip()
        svc_val = row[2].strip() if len(row) > 2 else ""

        if not src_val or not dst_val:
            continue

        res = eng.evaluate([src_val], [dst_val], [svc_val] if svc_val else [])
        top3 = res[:3]

        batch_results.append({
            "line": i + 1,
            "source": src_val,
            "destination": dst_val,
            "port": svc_val,
            "suggestions": top3,
        })

    return render_template(
        "client/batch_results.html",
        results=batch_results,
        has_header=has_header,
    )