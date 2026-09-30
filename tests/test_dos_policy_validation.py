"""Tests for DoS policy input validation."""

import pytest

from validation.dos_policy import (
    validate_dos_policy_list_params,
    DosPolicyValidationError,
)


# ---------------------------------------------------------------------------
# validate_dos_policy_list_params
# ---------------------------------------------------------------------------
class TestValidateDosPolicyListParams:
    def test_valid_defaults(self):
        result = validate_dos_policy_list_params()
        assert result == {}

    def test_valid_limit(self):
        result = validate_dos_policy_list_params(limit="50")
        assert result["limit"] == 50

    def test_valid_offset(self):
        result = validate_dos_policy_list_params(offset="10")
        assert result["offset"] == 10

    def test_valid_sort(self):
        result = validate_dos_policy_list_params(sort_by="name", sort_order="desc")
        assert result["sort_by"] == "name"
        assert result["sort_order"] == "desc"

    def test_valid_status(self):
        result = validate_dos_policy_list_params(status="enable")
        assert result["status"] == "enable"

    def test_valid_name(self):
        result = validate_dos_policy_list_params(name="test policy")
        assert result["name"] == "test policy"

    def test_invalid_limit(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(limit="abc")
        assert "limit" in exc_info.value.errors

    def test_limit_too_high(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(limit="9999")
        assert "limit" in exc_info.value.errors

    def test_limit_zero(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(limit="0")
        assert "limit" in exc_info.value.errors

    def test_invalid_offset(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(offset="-1")
        assert "offset" in exc_info.value.errors

    def test_invalid_sort_by(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(sort_by="invalid")
        assert "sort_by" in exc_info.value.errors

    def test_invalid_sort_order(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(sort_order="random")
        assert "sort_order" in exc_info.value.errors

    def test_invalid_status(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(status="pending")
        assert "status" in exc_info.value.errors

    def test_empty_name(self):
        with pytest.raises(DosPolicyValidationError) as exc_info:
            validate_dos_policy_list_params(name="")
        assert "name" in exc_info.value.errors
