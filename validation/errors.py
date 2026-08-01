from __future__ import annotations

from typing import Mapping, Sequence


class ValidationError(ValueError):
    """Structured validation failure suitable for forms, APIs, and logs."""

    def __init__(self, errors: Mapping[str, Sequence[str]]):
        self.errors = {field: list(messages) for field, messages in errors.items()}
        super().__init__(self.as_text())

    def as_text(self) -> str:
        return "; ".join(
            f"{field}: {message}"
            for field, messages in self.errors.items()
            for message in messages
        )
