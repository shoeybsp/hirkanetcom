import csv
import io
import logging
import time
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
from engine.snapshot_store import active_snapshot_id
from validation.evaluation import EvaluationInputError, MAX_BATCH_ROWS
from validation import ValidationError
from validation.uploads import validate_csv_upload
from client.access import has_active_service_subscription, subscription_required

client_bp = Blueprint("client", __name__, url_prefix="/client")
logger = logging.getLogger(__name__)


# -- Helpers (from original app.py) -------------------------------------------

def clean_list(value):
    """Split a comma-delimited form field; semantic checks live in validation.evaluation."""
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def address_value(address):
    if address.get("group"):
        return ", ".join(
            member.get("name", member) if isinstance(member, dict) else member
            for member in address.get("group", [])
        )
    if "subnet" in address:
        return address["subnet"].replace(" ", "/")
    if "iprange" in address:
        return address["iprange"].replace(" ", " - ", 1)
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
    current_id = active_snapshot_id()
    if _engine is None or (current_id and _engine.snapshot_id != current_id):
        try:
            _engine = SecureTrackLite()
            logger.info(
                "FortiGate evaluation snapshot loaded",
                extra={"snapshot_id": _engine.snapshot_id},
            )
        except Exception:
            logger.exception("Failed to initialize SecureTrackLite engine")
            _engine = None
    return _engine


def evaluation_catalog(engine_inst):
    """Build the address and service catalogs used by the evaluator form."""
    if not engine_inst:
        return [], []
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
    services = sorted(
        (
            {"name": svc["name"], "value": service_value(svc)}
            for svc in engine_inst.services
            if svc.get("name")
        ),
        key=lambda svc: svc["name"].lower(),
    )
    return addresses, services


def render_policy_evaluation(engine_inst, *, validation_errors=None, form_values=None, status=200):
    addresses, services = evaluation_catalog(engine_inst)
    return render_template(
        "client/policy_evaluation.html",
        addresses=addresses,
        services=services,
        validation_errors=validation_errors or {},
        form_values=form_values or {},
    ), status


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
    if not has_active_service_subscription(current_user.id, "policy_evaluation"):
        flash("You do not have access to the Policy Evaluation service.", "error")
        return redirect(url_for("client.dashboard"))

    engine_inst = ensure_engine()
    return render_policy_evaluation(engine_inst)


@client_bp.route("/policy-evaluation/results", methods=["POST"])
@login_required
@subscription_required("policy_evaluation")
def policy_evaluation_results():
    """Evaluate policies and show results."""
    src = clean_list(request.form.get("src"))
    dst = clean_list(request.form.get("dst"))
    svc = clean_list(request.form.get("service"))

    eng = ensure_engine()
    if not eng:
        return "Engine not available; ensure data files exist.", 500

    try:
        validated = eng.validate_request(src, dst, svc)
    except EvaluationInputError as exc:
        logger.warning(
            "Policy evaluation input rejected",
            extra={
                "event_type": "policy_evaluation_validation_failure",
                "user_id": str(current_user.id),
                "validation_fields": sorted(exc.errors),
            },
        )
        return render_policy_evaluation(
            eng,
            validation_errors=exc.errors,
            form_values={"src": src, "dst": dst, "service": svc},
            status=400,
        )

    started=time.perf_counter()
    logger.info("Policy evaluation started", extra={"event_type":"policy_evaluation_started","user_id":str(current_user.id),"source_count":len(validated.sources),"destination_count":len(validated.destinations),"service_count":len(validated.services)})
    res = eng.evaluate(validated.sources, validated.destinations, validated.services)
    logger.info("Policy evaluation completed", extra={"event_type":"policy_evaluation_completed","user_id":str(current_user.id),"result_count":len(res),"event_duration":int((time.perf_counter()-started)*1_000_000_000)})
    best = res[0] if res else None

    return render_template(
        "client/results.html",
        results=res,
        best=best,
        is_batch=False,
        query_src=validated.sources,
        query_dst=validated.destinations,
        query_service=validated.services,
    )


@client_bp.route("/policy-evaluation/batch-results", methods=["POST"])
@login_required
@subscription_required("policy_evaluation")
def policy_evaluation_batch():
    """Accept a CSV file with source,destination,port lines and evaluate each."""
    eng = ensure_engine()
    if not eng:
        return "Engine not available; ensure data files exist.", 500

    try:
        csv_text = validate_csv_upload(request.files.get("csv_file"))
    except ValidationError as exc:
        return exc.as_text(), 400
    stream = io.StringIO(csv_text, newline=None)
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

    if len(rows) > MAX_BATCH_ROWS:
        return f"CSV contains {len(rows)} data rows; the maximum is {MAX_BATCH_ROWS}.", 413

    validated_rows = []
    row_errors = []
    first_data_line = 2 if has_header else 1
    for i, row in enumerate(rows):
        line_number = first_data_line + i
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) < 2 or len(row) > 3:
            row_errors.append(
                f"Line {line_number}: expected 2 or 3 columns (source,destination,service)."
            )
            continue

        src_val = row[0].strip()
        dst_val = row[1].strip()
        svc_val = row[2].strip() if len(row) == 3 else ""
        try:
            validated = eng.validate_request(
                [src_val],
                [dst_val],
                [svc_val] if svc_val else [],
            )
        except EvaluationInputError as exc:
            row_errors.append(f"Line {line_number}: {exc.as_text()}")
            continue
        validated_rows.append((line_number, validated))

    if row_errors:
        logger.warning(
            "Batch policy evaluation input rejected",
            extra={
                "event_type": "policy_evaluation_batch_validation_failure",
                "user_id": str(current_user.id),
                "invalid_row_count": len(row_errors),
            },
        )
        return render_template(
            "client/batch_validation_error.html",
            errors=row_errors[:50],
            omitted_error_count=max(0, len(row_errors) - 50),
        ), 400

    if not validated_rows:
        return "CSV contains no evaluable data rows.", 400

    batch_results = []
    for line_number, validated in validated_rows:
        res = eng.evaluate(validated.sources, validated.destinations, validated.services)
        top3 = res[:3]
        batch_results.append({
            "line": line_number,
            "source": ", ".join(validated.sources),
            "destination": ", ".join(validated.destinations),
            "port": ", ".join(validated.services),
            "suggestions": top3,
        })

    logger.info("Batch policy evaluation completed", extra={"event_type":"policy_evaluation_batch_completed","user_id":str(current_user.id),"input_rows":len(rows),"result_rows":len(batch_results)})
    return render_template(
        "client/batch_results.html",
        results=batch_results,
        has_header=has_header,
    )