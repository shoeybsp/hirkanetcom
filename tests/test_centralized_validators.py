import io

import pytest
class FileStorage:
    def __init__(self, *, stream, filename):
        self.stream = stream
        self.filename = filename


from validation import ValidationError
from validation.admin import (
    validate_password_change,
    validate_service,
    validate_subscription_ids,
    validate_user,
)
from validation.uploads import validate_csv_upload


def test_user_validator_normalizes_and_checks_role():
    result = validate_user({"username": " Alice.Admin ", "password": "strong-password", "role": "admin"}, password_required=True)
    assert result.username == "alice.admin"
    assert result.role == "admin"
    with pytest.raises(ValidationError):
        validate_user({"username": "bad user", "password": "strong-password", "role": "owner"}, password_required=True)


def test_optional_password_is_still_validated_when_present():
    assert validate_user({"username": "alice", "password": "", "role": "client"}, password_required=False).password == ""
    with pytest.raises(ValidationError):
        validate_user({"username": "alice", "password": "short", "role": "client"}, password_required=False)


def test_service_length_validation():
    service = validate_service({"name": "Policy Evaluation", "service_type": "policy_evaluation", "is_active": "on"})
    assert service.is_active is True
    with pytest.raises(ValidationError):
        validate_service({"name": "x", "service_type": "Not Valid!"})


def test_subscription_ids_reject_non_integer_and_unknown_values():
    assert validate_subscription_ids(["1", "2", "2"], allowed_ids={1, 2}) == {1, 2}
    with pytest.raises(ValidationError):
        validate_subscription_ids(["1", "oops", "9"], allowed_ids={1, 2})


def test_password_change_is_consistent():
    current, new = validate_password_change({"current_password": "old", "new_password": "new-password-123", "confirm_password": "new-password-123"})
    assert (current, new) == ("old", "new-password-123")
    with pytest.raises(ValidationError):
        validate_password_change({"current_password": "", "new_password": "short", "confirm_password": "different"})


def test_csv_upload_validation():
    upload = FileStorage(stream=io.BytesIO(b"source,destination\n1.1.1.1,2.2.2.2"), filename="batch.csv")
    assert "source,destination" in validate_csv_upload(upload)
    with pytest.raises(ValidationError):
        validate_csv_upload(FileStorage(stream=io.BytesIO(b"x"), filename="batch.txt"))
