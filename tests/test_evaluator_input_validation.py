import pytest

from engine.input_validation import (
    EvaluationInputError,
    MAX_ITEMS_PER_FIELD,
    validate_evaluation_request,
)

KNOWN_ADDRESSES = {"branch-net", "database-host"}
KNOWN_SERVICES = {"https", "dns", "web-services"}


def validate(src, dst, services=None):
    return validate_evaluation_request(
        src,
        dst,
        services or [],
        known_addresses=KNOWN_ADDRESSES,
        known_services=KNOWN_SERVICES,
    )


def test_accepts_and_normalizes_known_objects_ipv4_and_services():
    result = validate(
        ["BRANCH-NET", "192.0.2.10"],
        ["198.51.100.0/24"],
        ["HTTPS", "udp/53", "8000"],
    )
    assert result.sources == ["branch-net", "192.0.2.10/32"]
    assert result.destinations == ["198.51.100.0/24"]
    assert result.services == ["https", "udp-53", "8000"]


def test_rejects_unknown_or_malformed_addresses():
    with pytest.raises(EvaluationInputError) as exc_info:
        validate(["unknown-object"], ["192.168.999.1"])
    assert "known FortiGate address object" in exc_info.value.as_text()


def test_rejects_ipv6_until_engine_support_is_complete():
    with pytest.raises(EvaluationInputError) as exc_info:
        validate(["2001:db8::1"], ["192.0.2.1"])
    assert "IPv6" in exc_info.value.as_text()


@pytest.mark.parametrize("service", ["tcp-0", "udp-65536", "tcp-9000-8000", "unknown-service"])
def test_rejects_invalid_service_values(service):
    with pytest.raises(EvaluationInputError):
        validate(["192.0.2.1"], ["198.51.100.1"], [service])


def test_requires_source_and_destination():
    with pytest.raises(EvaluationInputError) as exc_info:
        validate([], [], ["https"])
    assert set(exc_info.value.errors) >= {"sources", "destinations"}


def test_rejects_excessive_item_counts():
    sources = [f"192.0.2.{i % 255}" for i in range(MAX_ITEMS_PER_FIELD + 1)]
    with pytest.raises(EvaluationInputError) as exc_info:
        validate(sources, ["198.51.100.1"])
    assert "At most" in exc_info.value.as_text()


def test_deduplicates_values_case_insensitively():
    result = validate(["BRANCH-NET", "branch-net"], ["database-host"], ["HTTPS", "https"])
    assert result.sources == ["branch-net"]
    assert result.services == ["https"]
