"""Slice 2 — Catalogue must expose all 5 missing check modules.

The five modules were imported into `monitor/checks.py` but never
registered in CHECK_REGISTRY:
  - aide       (AideCheck)
  - http       (HTTP probes)
  - iostat     (per-device I/O latency)
  - smart      (SMART disk health)
  - ssl        (TLS certificate expiry)

Each entry must:
  - exist in CHECK_REGISTRY under the exact module key
  - carry label_he + description_he
  - carry rule_keys matching the keys read by the module's evaluate()
"""
from __future__ import annotations

from ipracticom_sweeper.catalogue import CHECK_REGISTRY


REQUIRED_KEYS = {"aide", "http", "iostat", "smart", "ssl"}

# rule_keys actually consumed by each module's evaluate() — must surface here
EXPECTED_RULE_KEYS = {
    "aide": ["critical_paths"],
    "http": ["slow_response_ms"],
    "iostat": ["await_warn_ms", "await_crit_ms", "util_warn_percent", "util_crit_percent"],
    "smart": ["reallocated_warn", "reallocated_crit", "temp_warn_c"],
    "ssl": ["warn_days", "crit_days"],
}


def test_all_five_missing_modules_present():
    keys = {e["key"] for e in CHECK_REGISTRY}
    missing = REQUIRED_KEYS - keys
    assert not missing, f"catalogue missing modules: {sorted(missing)}"


def test_each_entry_has_hebrew_label_and_description():
    by_key = {e["key"]: e for e in CHECK_REGISTRY}
    for k in REQUIRED_KEYS:
        assert k in by_key, f"{k} not in registry"
        entry = by_key[k]
        assert entry.get("label_he"), f"{k} missing label_he"
        assert entry.get("description_he"), f"{k} missing description_he"


def test_each_entry_exposes_consumed_rule_keys():
    by_key = {e["key"]: e for e in CHECK_REGISTRY}
    for k, expected in EXPECTED_RULE_KEYS.items():
        assert k in by_key, f"{k} not in registry"
        declared = {rk["name"] for rk in by_key[k]["rule_keys"]}
        missing = set(expected) - declared
        assert not missing, f"{k} missing rule_keys: {sorted(missing)}"
