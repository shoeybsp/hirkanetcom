import json, logging
from types import SimpleNamespace
from logging_config import JsonFormatter
from security import hash_password, verify_password

def test_password_hash_and_verify():
    user=SimpleNamespace(password_hash=hash_password("a-strong-password"),salt="")
    assert verify_password(user,"a-strong-password")
    assert not verify_password(user,"wrong")

def test_json_formatter_redacts_secret_fields():
    record=logging.LogRecord("test",logging.INFO,__file__,1,"hello",(),None)
    record.token="secret"
    data=json.loads(JsonFormatter().format(record))
    assert data["token"] == "[REDACTED]"
    assert data["message"] == "hello"
