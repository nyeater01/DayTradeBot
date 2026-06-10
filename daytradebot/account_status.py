from __future__ import annotations

from typing import Any

_ACTIVE = "ACTIVE"


def normalize_account_status(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value.strip():
        value = enum_value
    text = str(value).strip().upper()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    for prefix in ("ACCOUNTSTATUS", "ORDERSTATUS"):
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix) :].lstrip("._")
    return text


def is_active_account_status(value: Any) -> bool:
    return normalize_account_status(value) == _ACTIVE
