"""Authoritative JSON schema and identical float32 preprocessing for ML/C++."""
import json
import hashlib
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_BYTES = (ROOT / "schema/features.json").read_bytes()
SCHEMA_HASH = hashlib.sha256(SCHEMA_BYTES).hexdigest()
SCHEMA = json.loads(SCHEMA_BYTES)
FEATURES = SCHEMA["features"]
NAMES = [f["name"] for f in FEATURES]
LABELS = SCHEMA["labels"]


def vector(features):
    if not isinstance(features, dict) or set(features) != set(NAMES):
        raise ValueError("feature names do not match schema")
    values = []
    for spec in FEATURES:
        value = features[spec["name"]]
        if value is None:
            if spec["missing"] is None:
                raise ValueError(f"{spec['name']} cannot be missing")
            value = spec["missing"]
        elif (isinstance(value, bool) or not isinstance(value, (int, float))
              or not math.isfinite(value) or not spec["min"] <= value <= spec["max"]):
            raise ValueError(f"invalid {spec['name']}")
        if spec["name"] == "disconnect_count" and value != int(value):
            raise ValueError("disconnect_count must be integral")
        values.append(value)
    return np.asarray(values, dtype=np.float32)
