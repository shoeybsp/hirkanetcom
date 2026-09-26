"""Policy search and filtering endpoints."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from client.access import has_device_access, get_assigned_devices
from collectors.sync_service import resolve_device_data_root
from services.policy_search import PolicySearchService
from validation.policies import validate_policy_search_params, PolicySearchError

policy_api_bp = Blueprint("policy_api", __name__, url_prefix="/api/v1")
logger = logging.getLogger(__name__)


def _get_policy_service_for_device(device_id: int) -> PolicySearchService | None:
    """Return a PolicySearchService for the given device, or None if unavailable."""
    devices = get_assigned_devices(current_user.id)
    device = next((d for d in devices if d.id == device_id and d.is_active), None)
    if device is None:
        return None
    data_root = str(resolve_device_data_root(device))
    try:
        return PolicySearchService(data_root)
    except Exception:
        logger.exception(
            "Failed to load policy search service",
            extra={"device_id": device_id},
        )
        return None


@policy_api_bp.route("/policies", methods=["GET"])
@login_required
def list_policies():
    """List policies across all assigned devices with optional filtering.

    Query Parameters:
        device_id: Filter to a specific device
        name: Search by policy name (substring)
        action: Filter by action (accept/deny)
        status: Filter by status (enable/disable)
        service: Filter by service name (substring)
        srcaddr: Filter by source address name (substring)
        dstaddr: Filter by destination address name (substring)
        srcintf: Filter by source interface (substring)
        dstintf: Filter by destination interface (substring)
        logtraffic: Filter by log traffic setting (substring)
        limit: Max results per page (default 100, max 500)
        offset: Pagination offset (default 0)
        sort_by: Sort field (policyid/name/action, default policyid)
        sort_order: Sort direction (asc/desc, default asc)
    """
    try:
        validated = validate_policy_search_params(
            action=request.args.get("action"),
            status=request.args.get("status"),
            limit=request.args.get("limit"),
            offset=request.args.get("offset"),
            sort_by=request.args.get("sort_by"),
            sort_order=request.args.get("sort_order"),
            device_id=request.args.get("device_id"),
        )
    except PolicySearchError as exc:
        return jsonify({"error": "validation_failed", "details": exc.errors}), 400

    # Determine which device(s) to search
    devices = get_assigned_devices(current_user.id)
    device_id = validated.get("device_id")

    if device_id:
        # Verify device access
        if not has_device_access(current_user.id, device_id):
            logger.warning(
                "Policy search device access denied",
                extra={
                    "event_type": "policy_search_device_denied",
                    "user_id": str(current_user.id),
                    "requested_device_id": str(device_id),
                },
            )
            return jsonify({"error": "access_denied", "message": "You do not have access to this device."}), 403

        # Search single device
        svc = _get_policy_service_for_device(device_id)
        if svc is None:
            return jsonify({"error": "device_unavailable", "message": "No policy data available for this device."}), 404

        result = svc.search(
            name=request.args.get("name"),
            action=validated.get("action"),
            status=validated.get("status"),
            service=request.args.get("service"),
            srcaddr=request.args.get("srcaddr"),
            dstaddr=request.args.get("dstaddr"),
            srcintf=request.args.get("srcintf"),
            dstintf=request.args.get("dstintf"),
            logtraffic=request.args.get("logtraffic"),
            limit=validated.get("limit", 100),
            offset=validated.get("offset", 0),
            sort_by=validated.get("sort_by", "policyid"),
            sort_order=validated.get("sort_order", "asc"),
        )
        return jsonify({
            "data": result.data,
            "pagination": {
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
                "has_more": result.has_more,
            },
            "filters_applied": result.filters_applied,
            "device_id": device_id,
        })

    # Search across all assigned devices
    all_policies = []
    device_map: dict[int, str] = {}
    for device in devices:
        svc = _get_policy_service_for_device(device.id)
        if svc is None:
            continue
        device_result = svc.search(
            name=request.args.get("name"),
            action=validated.get("action"),
            status=validated.get("status"),
            service=request.args.get("service"),
            srcaddr=request.args.get("srcaddr"),
            dstaddr=request.args.get("dstaddr"),
            srcintf=request.args.get("srcintf"),
            dstintf=request.args.get("dstintf"),
            logtraffic=request.args.get("logtraffic"),
            limit=500,  # collect up to 500 per device for merging
            offset=0,
            sort_by=validated.get("sort_by", "policyid"),
            sort_order=validated.get("sort_order", "asc"),
        )
        for policy in device_result.data:
            policy["_device_id"] = device.id
            policy["_device_name"] = device.name
        all_policies.extend(device_result.data)
        device_map[device.id] = device.name

    # Re-sort merged results
    sort_by = validated.get("sort_by", "policyid")
    sort_order = validated.get("sort_order", "asc")
    reverse = sort_order == "desc"
    if sort_by in ("policyid", "name", "action"):
        all_policies.sort(key=lambda p: p.get(sort_by, ""), reverse=reverse)

    # Paginate merged results
    total = len(all_policies)
    limit = validated.get("limit", 100)
    offset = validated.get("offset", 0)
    page = all_policies[offset: offset + limit]
    has_more = (offset + limit) < total

    return jsonify({
        "data": page,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        },
        "filters_applied": {
            **{k: v for k, v in (validated.items() if isinstance(validated, dict) else []) if k not in ("limit", "offset", "sort_by", "sort_order", "device_id")},
        },
        "devices_searched": device_map,
    })


@policy_api_bp.route("/policies/<int:policy_id>", methods=["GET"])
@login_required
def get_policy(policy_id: int):
    """Get a specific policy by ID from any assigned device.

    Query Parameters:
        device_id: Required device context to resolve the policy
    """
    device_id = request.args.get("device_id", type=int)
    if not device_id:
        return jsonify({"error": "missing_parameter", "message": "device_id is required."}), 400

    if not has_device_access(current_user.id, device_id):
        return jsonify({"error": "access_denied", "message": "You do not have access to this device."}), 403

    svc = _get_policy_service_for_device(device_id)
    if svc is None:
        return jsonify({"error": "device_unavailable", "message": "No policy data available for this device."}), 404

    # Search by exact policyid
    result = svc.search(
        limit=1,
        offset=0,
        sort_by="policyid",
        sort_order="asc",
    )

    # Find exact match (search does substring on name, but we want exact policyid)
    for policy in svc._policies:
        if policy.get("policyid") == policy_id:
            return jsonify({"data": policy, "device_id": device_id})

    return jsonify({"error": "not_found", "message": f"Policy {policy_id} not found on this device."}), 404
