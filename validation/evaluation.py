"""Strict validation and normalization for policy evaluation requests."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Iterable, Mapping, Sequence

MAX_ITEMS_PER_FIELD = 50
MAX_VALUE_LENGTH = 128
MAX_BATCH_ROWS = 1000

_SERVICE_PATTERN = re.compile(
    r"^(?P<proto>tcp|udp)[-/](?P<start>\d{1,5})(?:-(?P<end>\d{1,5}))?$",
    re.IGNORECASE,
)


from .errors import ValidationError


class EvaluationInputError(ValidationError):
    """Raised when an evaluation request contains invalid or unsafe input."""


@dataclass(frozen=True)
class ValidatedEvaluationRequest:
    sources: list[str]
    destinations: list[str]
    services: list[str]


def _clean_values(values: Iterable[str] | None, field: str, errors: dict[str, list[str]]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()

    for raw in values or []:
        if not isinstance(raw, str):
            errors.setdefault(field, []).append("Every value must be text.")
            continue
        value = raw.strip()
        if not value:
            continue
        if len(value) > MAX_VALUE_LENGTH:
            errors.setdefault(field, []).append(
                f"'{value[:32]}…' exceeds the {MAX_VALUE_LENGTH}-character limit."
            )
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(value)

    if len(cleaned) > MAX_ITEMS_PER_FIELD:
        errors.setdefault(field, []).append(
            f"At most {MAX_ITEMS_PER_FIELD} values are allowed."
        )
        return cleaned[:MAX_ITEMS_PER_FIELD]
    return cleaned


def _normalize_address(
    value: str,
    known_addresses: set[str],
    field: str,
    errors: dict[str, list[str]],
) -> str | None:
    lowered = value.casefold()
    if lowered in known_addresses:
        return lowered

    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        errors.setdefault(field, []).append(
            f"'{value}' is neither a valid IPv4 address/CIDR nor a known FortiGate address object."
        )
        return None

    if network.version != 4:
        errors.setdefault(field, []).append(
            f"'{value}' is IPv6; this evaluator currently supports IPv4 only."
        )
        return None

    return str(network)


def _validate_port(port_text: str, original: str, field: str, errors: dict[str, list[str]]) -> int | None:
    try:
        port = int(port_text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        errors.setdefault(field, []).append(
            f"'{original}' contains a port outside the valid range 1-65535."
        )
        return None
    return port


def _normalize_service(
    value: str,
    known_services: set[str],
    field: str,
    errors: dict[str, list[str]],
) -> str | None:
    lowered = value.casefold()
    if lowered in known_services:
        return lowered

    if lowered.isdigit():
        port = _validate_port(lowered, value, field, errors)
        return str(port) if port is not None else None

    match = _SERVICE_PATTERN.fullmatch(lowered)
    if match:
        start = _validate_port(match.group("start"), value, field, errors)
        end_text = match.group("end")
        end = _validate_port(end_text, value, field, errors) if end_text else None
        if start is None or (end_text and end is None):
            return None
        if end is not None and start > end:
            errors.setdefault(field, []).append(
                f"'{value}' has a descending port range; the start must not exceed the end."
            )
            return None
        proto = match.group("proto").lower()
        return f"{proto}-{start}" if end is None else f"{proto}-{start}-{end}"

    errors.setdefault(field, []).append(
        f"'{value}' is neither a known FortiGate service nor a supported port expression "
        "(for example 443, tcp-443, udp/53, or tcp-8000-8080)."
    )
    return None


def validate_evaluation_request(
    sources: Iterable[str] | None,
    destinations: Iterable[str] | None,
    services: Iterable[str] | None,
    *,
    known_addresses: Iterable[str],
    known_services: Iterable[str],
    require_endpoints: bool = True,
) -> ValidatedEvaluationRequest:
    """Validate, normalize, and deduplicate a policy evaluation request.

    Address values must be known FortiGate object names or valid IPv4 addresses/CIDRs.
    Service values must be known FortiGate service names or supported port expressions.
    """

    errors: dict[str, list[str]] = {}
    source_values = _clean_values(sources, "sources", errors)
    destination_values = _clean_values(destinations, "destinations", errors)
    service_values = _clean_values(services, "services", errors)

    if require_endpoints and not source_values:
        errors.setdefault("sources", []).append("At least one source address is required.")
    if require_endpoints and not destination_values:
        errors.setdefault("destinations", []).append("At least one destination address is required.")

    address_names = {name.casefold() for name in known_addresses if name}
    service_names = {name.casefold() for name in known_services if name}

    normalized_sources = [
        normalized
        for value in source_values
        if (normalized := _normalize_address(value, address_names, "sources", errors)) is not None
    ]
    normalized_destinations = [
        normalized
        for value in destination_values
        if (normalized := _normalize_address(value, address_names, "destinations", errors)) is not None
    ]
    normalized_services = [
        normalized
        for value in service_values
        if (normalized := _normalize_service(value, service_names, "services", errors)) is not None
    ]

    if errors:
        raise EvaluationInputError(errors)

    return ValidatedEvaluationRequest(
        sources=normalized_sources,
        destinations=normalized_destinations,
        services=normalized_services,
    )
