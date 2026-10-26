"""Strict bounded wire validation, tolerant stream processing."""
import json
import math

from host.schema import LABELS, NAMES, SCHEMA, vector

MAX_LINE = 4096
STATES = {"connected", "degraded", "disconnected", "recovering"}
SOURCES = {"esp32", "synthetic", "host_cpp"}


def _integer(record, name, maximum=2**64 - 1):
    v = record.get(name)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= maximum:
        raise ValueError(f"invalid {name}")


def parse_line(line):
    if len(line) > MAX_LINE:
        raise ValueError("oversized record")
    try:
        r = json.loads(line)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("malformed JSON") from exc
    if not isinstance(r, dict):
        raise ValueError("record must be an object")
    for key in ("protocol_version", "schema_version"):
        _integer(r, key)
        if r[key] != SCHEMA[key]:
            raise ValueError(f"incompatible {key}")
    if not isinstance(r.get("firmware_version"), str) or not r["firmware_version"]:
        raise ValueError("missing firmware_version")
    if r.get("source") not in SOURCES or r.get("state") not in STATES:
        raise ValueError("unknown source or connection state")
    model_id = r.get("model_id")
    if not isinstance(model_id, str) or len(model_id) != 16 or any(c not in "0123456789abcdef" for c in model_id):
        raise ValueError("invalid model_id")
    for key in ("uptime_ms", "sequence", "inference_us", "extraction_us", "probe_successes", "probe_failures",
                "disconnects_total", "reconnect_attempts", "reconnect_successes", "reconnect_failures"):
        _integer(r, key)
    valid = r.get("features_valid")
    if not isinstance(valid, bool) or not isinstance(r.get("diagnostic"), str):
        raise ValueError("missing validation status")
    features = r.get("features")
    if not isinstance(features, dict) or set(features) != set(NAMES):
        raise ValueError("feature schema mismatch")
    if valid:
        x = vector(features)
        successes, failures = r["probe_successes"], r["probe_failures"]
        if successes + failures != SCHEMA["window_samples"] or not math.isclose(float(x[3]), failures / SCHEMA["window_samples"], abs_tol=1e-6):
            raise ValueError("inconsistent probe counts")
        if (successes == 0) != (features["rtt_mean_ms"] is None) or (successes == 0) != (features["rtt_std_ms"] is None):
            raise ValueError("inconsistent RTT missingness")
        if r.get("prediction") not in LABELS or r["diagnostic"] != "ok":
            raise ValueError("invalid prediction or diagnostic")
    elif r.get("prediction") is not None or any(v is not None for v in features.values()):
        raise ValueError("invalid window must have null prediction/features")
    return r
