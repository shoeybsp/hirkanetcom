# Multi-Vendor, Multi-Device Device Inventory Architecture Plan

## Context

Hirkanet currently supports only FortiGate firewalls. The goal is to evolve the device inventory to support **multiple vendors** (Palo Alto, Cisco ASA, Check Point, etc.) while maintaining the existing FortiGate functionality. This plan analyzes the current architecture, identifies what's vendor-specific vs vendor-agnostic, and proposes a clean extension path.

---

## Current Architecture Analysis

### Data Flow
```
Device (DB) → Collector (vendor-specific) → Snapshot (standard JSON) → Evaluator (mostly generic)
```

### What's Vendor-Specific Today
| Component | File | Vendor Coupling |
|-----------|------|-----------------|
| Collector | `collectors/fortigate_collector.py` | **Hard** — FortiGate REST API paths (`/api/v2/cmdb/`), auth (Bearer token), VDOM concept |
| Sync Service | `collectors/sync_service.py` | **Moderate** — calls collector functions directly, error mapping is FortiGate-aware |
| Device Model | `models.py` | **Light** — `device_type` field exists but only `'fortigate'` is defined; `api_key`/`auth_username`/`auth_password` are generic enough |
| Snapshot Format | `engine/snapshot_store.py` | **None** — loads standard JSON files (`policies.json`, `addresses.json`, etc.) |
| Evaluator | `engine/evaluator.py` | **Mostly none** — works on normalized JSON; FortiGate-specific names in docstrings only |
| CIDR Tools | `engine/cidr_tools.py` | **None** — pure IP/network math |
| Interface Selector | `engine/interface_selector.py` | **None** — works on generic route objects |
| Admin UI | `templates/admin/device_*.html` | **Light** — forms reference FortiGate fields but are generic enough |

### What's Already Good
1. **Snapshot format is vendor-agnostic** — policies, addresses, services, routes, interfaces as JSON lists
2. **Evaluator is generic** — `SecureTrackLite` works on normalized data, not raw vendor output
3. **Device model has `device_type`** — extensible by design
4. **Per-device isolation** — each device has its own `data_dir` and engine cache
5. **Authorization is device-level** — `DeviceAssignment` works regardless of vendor

---

## Proposed Multi-Vendor Architecture

### 1. Collector Abstraction (Strategy Pattern)

Create a base collector interface that all vendors implement:

```
collectors/
├── __init__.py
├── base.py                  # Abstract base collector
├── fortigate_collector.py   # Existing (refactored)
├── paloalto_collector.py    # New: Palo Alto Panorama/NGFW
├── ciscoasa_collector.py    # New: Cisco ASA/FTD
├── checkpoint_collector.py  # New: Check Point mgmt server
└── sync_service.py          # Vendor-agnostic orchestrator
```

**`collectors/base.py`** — Abstract interface:
```python
from abc import ABC, abstractmethod

class BaseCollector(ABC):
    """Base class for all vendor collectors.
    
    Subclasses must implement collect() to return a standardized
    dataset dict with keys: policies, addresses, services, routes, interfaces.
    """
    
    @abstractmethod
    def collect(self, session, device_config) -> dict:
        """Collect policy data from the device.
        
        Args:
            session: Authenticated HTTP session
            device_config: Dict with connection details (host, scheme, timeout, etc.)
        
        Returns:
            Dict with keys: policies, addresses, services, routes, interfaces
            Each value is a list of normalized dicts.
        """
        pass
    
    @abstractmethod
    def build_session(self, credentials: dict):
        """Create an authenticated session for this vendor's API."""
        pass
```

**Normalization contract** — All collectors output the same schema:
```json
{
  "policies": [{"name": "...", "srcaddr": [...], "dstaddr": [...], "service": [...], "action": "accept", "status": "enable", "srcintf": [...], "dstintf": [...]}],
  "addresses": [{"name": "...", "subnet": "10.0.0.0/24"}],
  "services": [{"name": "...", "protocol": "tcp", "tcp-portrange": "443"}],
  "routes": [{"dst": "0.0.0.0/0", "interface": "port1"}],
  "interfaces": [{"name": "...", "ip": "10.0.0.1/24"}]
}
```

### 2. Device Model Extension

Extend `models.py` to support vendor-specific configuration:

```python
class Device(db.Model):
    # Existing fields stay unchanged
    device_type = db.Column(db.String(50), nullable=False, default="fortigate")
    
    # New: JSON field for vendor-specific config
    vendor_config = db.Column(db.JSON, nullable=True, default=dict)
    # Examples:
    # FortiGate: {"vdom": "root"}
    # Palo Alto: {"vsys": "vsys1", " panorama_serial": "..."}
    # Cisco ASA: {"context": "system"}
    # Check Point: {"domain": "CMA", "management_server": "..."}
```

**Migration**: Add `vendor_config` JSON column to `devices` table.

### 3. Collector Registry

Create a registry that maps `device_type` to collector class:

```python
# collectors/__init__.py
COLLECTOR_REGISTRY = {
    "fortigate": "collectors.fortigate_collector.FortiGateCollector",
    "paloalto": "collectors.paloalto_collector.PaloAltoCollector",
    "ciscoasa": "collectors.ciscoasa_collector.CiscoASACollector",
    "checkpoint": "collectors.checkpoint_collector.CheckPointCollector",
}

def get_collector(device_type: str) -> BaseCollector:
    """Return the collector instance for a device type."""
    import importlib
    path = COLLECTOR_REGISTRY.get(device_type)
    if not path:
        raise ValueError(f"Unsupported device type: {device_type}")
    module_path, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()
```

### 4. Sync Service Refactor

Update `sync_service.py` to be vendor-agnostic:

```python
def run_device_sync(device) -> dict:
    """Collect a fresh snapshot for any supported device type."""
    from collectors import get_collector
    
    collector = get_collector(device.device_type)
    session = collector.build_session(decrypt_credentials(device))
    
    with collector_lock(output_dir):
        dataset = collector.collect(session, build_device_config(device))
        snapshot_id, snapshot_dir, manifest = publish_snapshot(output_dir, dataset, ...)
        prune_snapshots(output_dir, snapshot_id, device.keep_snapshots)
```

### 5. Evaluator (No Changes Needed)

The evaluator already works on normalized JSON. The only change needed:
- Remove "FortiGate" from docstrings/class names (cosmetic)
- The evaluator doesn't know or care which vendor produced the data

### 6. Admin UI Updates

Add vendor-specific form fields dynamically:

```html
<!-- In device_create.html / device_edit.html -->
<select name="device_type" id="device_type">
    <option value="fortigate">FortiGate</option>
    <option value="paloalto">Palo Alto</option>
    <option value="ciscoasa">Cisco ASA</option>
    <option value="checkpoint">Check Point</option>
</select>

<!-- Dynamic fields based on vendor -->
<div id="vendor-fields">
    <!-- FortiGate -->
    <div class="vendor-field" data-vendor="fortigate">
        <label>VDOM</label>
        <input name="vendor_vdom" value="root">
    </div>
    <!-- Palo Alto -->
    <div class="vendor-field" data-vendor="paloalto" style="display:none">
        <label>Vsys</label>
        <input name="vendor_vsys" value="vsys1">
    </div>
    <!-- etc. -->
</div>
```

### 7. Client UI (No Changes Needed)

The client dashboard already:
- Lists assigned devices regardless of type
- Uses `ensure_engine()` which loads any snapshot
- Shows address/service catalogs from the evaluator

---

## Implementation Steps

### Phase 1: Collector Abstraction (Core)
1. Create `collectors/base.py` with `BaseCollector` ABC
2. Refactor `fortigate_collector.py` to implement `BaseCollector`
3. Create `collectors/__init__.py` with `COLLECTOR_REGISTRY` and `get_collector()`
4. Update `sync_service.py` to use the registry

### Phase 2: Model & Migration
5. Add `vendor_config` JSON column to `Device` model
6. Create Alembic migration for the new column
7. Update admin validation to handle `vendor_config`

### Phase 3: Admin UI
8. Update `device_create.html` and `device_edit.html` with dynamic vendor fields
9. Add JavaScript to show/hide vendor-specific fields based on `device_type` selection

### Phase 4: New Vendor Collectors
10. Implement `PaloAltoCollector` (Palo Alto REST API)
11. Implement `CiscoASACollector` (Cisco REST API / FTD)
12. Implement `CheckPointCollector` (Check Point Management API)

### Phase 5: Testing
13. Unit tests for `BaseCollector` interface contract
14. Unit tests for each collector's normalization logic
15. Integration tests for multi-vendor sync flow

---

## Key Files to Modify
- `collectors/base.py` (new)
- `collectors/__init__.py` (new)
- `collectors/fortigate_collector.py` (refactor)
- `collectors/sync_service.py` (vendor-agnostic)
- `models.py` (add `vendor_config`)
- `admin/routes.py` (vendor config handling)
- `templates/admin/device_create.html` (dynamic fields)
- `templates/admin/device_edit.html` (dynamic fields)

## Key Files Unchanged
- `engine/evaluator.py` (already generic)
- `engine/snapshot_store.py` (already generic)
- `engine/cidr_tools.py` (already generic)
- `engine/interface_selector.py` (already generic)
- `client/routes.py` (already generic)
- `client/access.py` (already generic)

---

## Verification
1. Existing FortiGate devices continue to work after refactor
2. Admin can create/edit devices with vendor-specific config
3. Sync works for each supported vendor
4. Client evaluation works regardless of device type
5. Unit tests pass for all collectors
6. New vendors can be added by implementing `BaseCollector` and registering in `COLLECTOR_REGISTRY`
