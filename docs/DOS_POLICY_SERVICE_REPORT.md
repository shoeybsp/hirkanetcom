# DoS Policy Service — Bug & Code Quality Report

**Date:** 2026-09-30
**Scope:** All files implementing the DoS Policy Management service — the service layer, validation, API client, audit engine, routes, templates, and tests.

---

## CRITICAL Bugs

### 1. `_clean_payload()` never returns a value
**File:** `services/dos_policy.py:55-119`
**Severity:** CRITICAL — all create and update operations are broken

The `_clean_payload()` function builds a cleaned `payload` dict but has **no `return` statement**. It falls off the end and implicitly returns `None`. This function is called by:

- `create_policy()` at line 227: `cleaned = _clean_payload(None, policy_data)` → `cleaned` is `None`
- `update_policy()` at line 247: `cleaned = _clean_payload(self.get_policy(policy_id), policy_data)` → `cleaned` is `None`

Both then pass `None` to the FortiGate API client, which would either crash or silently send no payload.

**Fix:** Add `return payload` at the end of `_clean_payload()` (after the anomaly cleaning block, around line 119).

---

## HIGH Bugs

### 2. Double `svc.close()` in edit POST error path
**File:** `client/routes.py:1052-1071`
**Severity:** HIGH — resource leak or RuntimeError depending on session state

In `dos_policy_edit()` POST, when `svc.update_policy()` raises `DosPolicyServiceError`:

```python
except DosPolicyServiceError as exc:
    ...
    existing = svc.get_policy(policy_id)  # <-- may call close internally on failure
    svc.close()                           # <-- explicit close
    ...
finally:
    svc.close()                           # <-- called again unconditionally
```

The `FortiGateClient.close()` closes the underlying `requests.Session`. Calling `close()` on an already-closed session can raise or silently fail. Compare with `dos_policy_delete()` (line 1094-1102) which has the same pattern.

The same issue exists in `dos_policy_create()` POST (lines 975-991) where the `finally` block always runs even after a successful call in the `try` — though that one is harmless on success.

**Fix:** Remove the explicit `svc.close()` from the `except` blocks and rely solely on the `finally` block, or guard `close()` with an `_closed` flag.

---

### 3. `audit_single()` crashes on non-integer policy IDs
**File:** `engine/dos_policy_auditor.py:161-167`
**Severity:** HIGH — unhandled ValueError

```python
def audit_single(self, policy_id: int) -> DosPolicyAuditResult | None:
    for policy in self._policies:
        pid = policy.get("id")
        if pid is not None and int(pid) == policy_id:
```

If `pid` is a non-numeric string (which FortiGate may return from certain firmware versions), `int(pid)` raises `ValueError` — uncaught. This would crash the audit endpoint for that device.

**Fix:** Wrap in try/except or compare with string coercion.

---

### 4. Sidebar DoS link visible without subscription on DoS pages
**File:** `templates/client/dos_policies.html:65-68` and `templates/client/dos_policy_form.html:45-48`
**Severity:** HIGH — authorization inconsistency

The DoS Policies sidebar link is hardcoded as always visible in the DoS policy templates. It does NOT check `subscribed_services` like the dashboard does (`{% if 'dos_policy' in subscribed_services %}`). A user with the sidebar visible on these pages could attempt to navigate to DoS policy routes they shouldn't access. While the `@subscription_required("dos_policy")` decorator catches this server-side, showing the link to unsubscribed users is misleading and inconsistent with the pattern used in `dashboard.html`.

**Fix:** Pass `subscribed_services` to these templates and wrap the sidebar link in the same conditional, or (simpler) extract the sidebar into a shared partial that always checks the subscription.

---

## MEDIUM Issues

### 5. `_clean_payload()` called but result never used for audit path
**File:** `services/dos_policy.py:284-301`
**Severity:** LOW (functionally correct, just redundant)

The `audit_policies()` method fetches policies from FortiGate and passes raw dicts to the auditor. This is fine. But the auditor itself does not normalize `anomaly` from dict→list form when the FortiGate returns anomalies as a dict (which some firmware versions do). The auditor at `dos_policy_auditor.py:197-199` does handle this:

```python
anomalies = policy.get("anomaly", [])
if isinstance(anomalies, dict):
    anomalies = list(anomalies.values()) if anomalies else []
```

This is correct. No action needed.

---

### 6. `quarantine-expiry` has no format validation
**File:** `validation/dos_policy.py:370-372`
**Severity:** MEDIUM — may send invalid values to FortiGate

```python
quarantine_expiry = anomaly.get("quarantine-expiry")
if quarantine_expiry is not None and quarantine_expiry != "":
    result["quarantine-expiry"] = str(quarantine_expiry).strip()
```

Any string is accepted. FortiGate expects a duration format like `"5m"`, `"1h"`, `"30s"`. Sending `"abc"` would result in a confusing API error from the device.

**Fix:** Add a regex check for the expected format (e.g., `r"^\d+[smhd]?$"`).

---

### 7. Address/service lists default to `[{"name": "all"}]` when empty
**File:** `services/dos_policy.py:96-97`
**Severity:** MEDIUM — may be unintentional

```python
def _normalise_name_list(items):
    ...
    return result or [{"name": "all"}]
```

When a user submits an empty srcaddr/dstaddr/service field, it becomes an empty list, which is then normalized to `[{"name": "all"}]`. This means **all create/update operations with empty address fields will set the policy to match all traffic**, which may not be what the user intended. FortiGate DoS policies may actually require at least one address, but silently defaulting to "all" is risky.

**Fix:** Consider returning an empty list `[]` and letting FortiGate reject the request, or at minimum document this behavior.

---

### 8. `_check_response_status` only checks two nesting patterns
**File:** `engine/fortigate_client.py:277-297`
**Severity:** MEDIUM — some error responses silently pass

FortiGate firmware can return errors in multiple JSON structures. The current check only covers:
1. `body["status"]["code"]` (top-level)
2. `body["result"]["status"]["code"]` (nested)

If the error is at a different nesting depth (e.g., `body["result"]["status"]["code"]` wrapped inside `body["result"]["data"]`), it would be missed, causing the caller to treat a failed update as successful.

**Fix:** Consider a more exhaustive check or at minimum log a warning when the response format doesn't match expected patterns.

---

### 9. `delete` route does not read `device_id` from query params
**File:** `client/routes.py:1083`
**Severity:** MEDIUM — UX issue

```python
device_id = request.form.get("device_id", type=int)
```

The delete form in the template sends `device_id` as a hidden form field, so this works for POST. However, the `finally: svc.close()` also has the double-close issue (line 1099-1102):

```python
except DosPolicyServiceError as exc:
    ...
    svc.close()       # close in except
    return redirect(...)
finally:
    svc.close()       # close again unconditionally
```

Same pattern as bug #2.

---

## LOW / Code Quality Issues

### 10. `_clean_payload()` is a module-level function but accesses `KNOWN_ANOMALY_NAMES`
**File:** `services/dos_policy.py:53`
**Severity:** LOW — works but fragile

```python
from validation.dos_policy import KNOWN_ANOMALY_NAMES
```

This import is placed inside the module body at an unusual position (between the whitelist sets and the function). It works, but the import placement makes the dependency less visible. Consider moving it to the top of the file with other imports.

---

### 11. Test coverage gap: no integration test for form submission flow
**File:** `tests/test_dos_policy_service.py`
**Severity:** LOW — incomplete coverage

The existing tests mock the API client and test service methods in isolation. There are no tests that verify:
- The route-level flow (form → validation → service → FortiGate)
- The `_clean_payload()` function in isolation (which would have caught bug #1)
- The double-close scenario

---

### 12. `_extract_results` returns `list | dict | None` — callers assume list
**File:** `engine/fortigate_client.py:207-218`
**Severity:** LOW

`_extract_results()` can return a `dict`, but `list_dos_policies()` (line 240) does:

```python
policies = list(raw) if isinstance(raw, list) else []
```

This silently discards dict-shaped responses. `get_dos_policy()` handles both, but there's an asymmetry.

---

### 13. No rate limiting on DoS policy CRUD endpoints
**File:** `client/routes.py:739-1105`
**Severity:** LOW — security hardening

The DoS policy create, edit, and delete routes have no rate limiting. An attacker with a valid session could spam the FortiGate API through these endpoints, potentially causing a DoS on the device itself. The login endpoint has rate limiting (`auth/rate_limit.py`), but the client service endpoints do not.

---

## Summary

| Severity | Count | Key Items |
|----------|-------|-----------|
| CRITICAL | 1 | `_clean_payload()` missing return — all create/update broken |
| HIGH | 3 | Double-close in edit/delete, `audit_single` crash, sidebar visibility |
| MEDIUM | 4 | No quarantine-expiry validation, empty→all normalization, limited response check, delete double-close |
| LOW | 4 | Import placement, test coverage, type asymmetry, no rate limiting |

**Recommended priority:** Fix #1 immediately (service is non-functional for mutations), then #2 (resource leak), then #3 and #4.
