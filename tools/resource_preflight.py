#!/usr/bin/env python3
"""Offline, read-only TPU profile preflight; never queries or starts Kaggle.

Accepts at most one explicitly supplied Companion SessionSnapshot JSON. No
network, JAX, subprocess, model inference, real TPU or device probing. Output
is a strict redacted projection, not a hardware readiness certificate.
"""

import argparse
import json
import math
from pathlib import Path
import sys


MAX_SNAPSHOT_BYTES = 256 * 1024
PROFILES = {
    "qwen38-27b": {
        "served_id": "qwen3.8-27b",
        "engine_kind": "pinned_vllm_tpu",
        "engine_version": "0.28.0",
    },
    "glm53-flash": {
        "served_id": "glm-5.3-flash",
        "engine_kind": "custom_jax_pallas",
        "engine_version": None,
    },
}
PHASES = frozenset({
    "idle", "verifying", "queued", "provisioning", "starting",
    "loadingWeights", "compiling", "healthy", "ready",
    "stopping", "stopped", "failed",
})
KAGGLE_STATUSES = frozenset({
    "queued", "running", "complete", "error", "cancelled",
    "notfound", "unavailable", "unknown",
})


def _field(snapshot, key, validator, origin="input_snapshot_unverified"):
    if key not in snapshot:
        return {"value": None, "source": "not_provided"}
    value = snapshot[key]
    if value is None:
        return {"value": None, "source": "unavailable_in_snapshot"}
    if not validator(value):
        return {"value": None, "source": "invalid_or_unknown"}
    return {"value": value, "source": origin}


def _nonnegative_integer(value):
    return type(value) is int and 0 <= value <= 10**12


def _nonnegative_number(value):
    # math.isfinite() converts Python ints to float; a very large JSON integer
    # raises OverflowError during conversion instead of failing validation.
    if type(value) is int:
        return 0 <= value <= 10**12
    return type(value) is float and math.isfinite(value) and 0 <= value <= 10**12


def _boolean(value):
    return type(value) is bool


def _phase(value):
    return isinstance(value, str) and value in PHASES


def _status(value):
    return isinstance(value, str) and value in KAGGLE_STATUSES


def _endpoint_present(snapshot):
    if "endpoint" not in snapshot:
        return {"value": None, "source": "not_provided"}
    value = snapshot["endpoint"]
    if value is None:
        return {"value": False, "source": "input_snapshot_derived_unverified"}
    if not isinstance(value, str):
        return {"value": None, "source": "invalid_or_unknown"}
    # Never echo the original URL, hostname, credentials or other input.
    return {"value": bool(value.strip()), "source": "input_snapshot_derived_unverified"}


def build_preflight(profile_id, snapshot=None):
    """Build a sanitized schema-v1 report from a caller-provided snapshot."""
    if profile_id not in PROFILES:
        raise ValueError("Unsupported TPU profile")
    if snapshot is None:
        snapshot = {}
        supplied = False
    else:
        if not isinstance(snapshot, dict):
            raise ValueError("Expected one JSON object of Companion snapshot fields")
        supplied = True
        if snapshot.get("model") is not None and snapshot["model"] != profile_id:
            raise ValueError("Snapshot model and requested profile do not match")

    profile = PROFILES[profile_id]
    # SessionSnapshot::snapshot in Rust may use a settings fallback for these
    # fields; provenance cannot be recovered from the serialized JSON alone.
    configured = {
        "context_tokens": _field(snapshot, "maxModelLen", _nonnegative_integer,
                                 "companion_effective_or_settings_fallback"),
        "keepalive_min": _field(snapshot, "keepaliveMin", _nonnegative_integer,
                                "companion_effective_or_settings_fallback"),
        "text_only": _field(snapshot, "textOnly", _boolean,
                            "companion_effective_or_settings_fallback"),
    }
    if profile_id == "qwen38-27b":
        configured["mtp_tokens"] = _field(
            snapshot, "mtpTokens", _nonnegative_integer,
            "companion_effective_or_settings_fallback")

    report = {
        "schema_version": 1,
        "scope": "self_hosted_tpu",
        "mode": "offline_read_only",
        "model": {
            "profile": profile_id,
            "served_id": profile["served_id"],
            "engine_kind": profile["engine_kind"],
            "engine_version_configured": profile["engine_version"],
            "target_hardware": "Kaggle TPU v5e-8",
            "target_device_count": 8,
            "target_source": "project_profile_not_hardware_measurement",
        },
        "session": {
            "phase": _field(snapshot, "phase", _phase),
            "kaggle_status": _field(snapshot, "kaggleStatus", _status),
            "endpoint_present": _endpoint_present(snapshot),
            "endpoint_live_claim": _field(snapshot, "endpointLive", _boolean),
            "has_api_key": _field(snapshot, "hasApiKey", _boolean),
            "ready_at": _field(snapshot, "readyAt", _nonnegative_integer),
            "ready_at_estimated": _field(snapshot, "readyAtEstimated", _boolean),
            "uptime_secs": _field(snapshot, "uptimeSecs", _nonnegative_integer),
            "remaining_secs": _field(snapshot, "remainingSecs", _nonnegative_integer),
            "remaining_estimated": _field(snapshot, "remainingEstimated", _boolean),
        },
        "configured": configured,
        "observed": {
            "decode_tokens_per_second": _field(
                snapshot, "decodeTokS", _nonnegative_number,
                "companion_event_unverified"),
            "accelerator": {
                "status": "unobserved",
                "device_count": None,
                "device_kind": None,
                "hbm_used_bytes": None,
                "source": "no_structured_device_probe_in_companion_snapshot",
            },
            "disk": {
                "status": "unobserved",
                "available_bytes": None,
                "source": "not_collected_from_remote_kernel",
            },
        },
        "checks": {
            "authenticated_models_probe": "not_run",
            "openai_sse": "not_checked",
            "anthropic_messages": "not_checked",
            "tools": "not_checked",
            "inference_requests_sent": 0,
            "mutating_actions": 0,
        },
        "readiness": "inconclusive",
        "reason_codes": [
            "ACCELERATOR_NOT_OBSERVED",
            "REMOTE_DISK_NOT_OBSERVED",
            "LIVE_TPU_ACCEPTANCE_DEFERRED",
        ],
        "provenance": {
            "snapshot_supplied": supplied,
            "snapshot_trust": "user_supplied_unverified" if supplied else "none",
            "hardware_verified": False,
            "inference_verified": False,
        },
    }
    return report


def load_snapshot(path):
    """Read only an explicitly named, bounded JSON file; never auto-discover."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("Invalid or oversized snapshot")
    with path.open("rb") as source:
        raw = source.read(MAX_SNAPSHOT_BYTES + 1)
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds size limit")
    # Reject non-JSON floating values rather than serializing NaN as invalid JSON.
    return json.loads(raw.decode("utf-8-sig"),
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--snapshot-file", type=Path,
                        help="Optional existing Companion SessionSnapshot JSON; never uploaded")
    args = parser.parse_args(argv)
    try:
        snapshot = load_snapshot(args.snapshot_file) if args.snapshot_file else None
        report = build_preflight(args.profile, snapshot)
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, UnicodeError, ValueError, RecursionError):
        # Deliberately do not print file paths, input fields or exception text.
        print("PREFLIGHT FAILED: invalid or unsupported snapshot", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
