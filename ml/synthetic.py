"""Seeded synthetic development sessions; no hardware claims."""
import argparse
from collections import deque
import json
from pathlib import Path

import numpy as np

from host.schema import LABELS, NAMES, SCHEMA
from ml.model import load_model, predict


def generate(seed=2210, sessions=18, slots=180, model=None):
    rng = np.random.default_rng(seed)
    for session in range(sessions):
        window = deque(maxlen=SCHEMA["window_samples"])
        last_success = None
        connected_since = 0
        previous_link = False
        disconnects = attempts = outcomes = 0
        regime = 0
        for slot in range(slots):
            if slot % 20 == 0:
                regime = int(rng.integers(0, 8))
                base_latency = float(rng.uniform(3, 65))
            linked = regime != 5 and (regime != 7 or slot % 4 != 0)
            now = slot * 1000
            if linked and not previous_link:
                connected_since = now; attempts += 1; outcomes += 1
            event = int(previous_link and not linked)
            disconnects += event
            previous_link = linked
            # Mix healthy, weak, variable latency, endpoint failure and AP outage.
            rssi = float(np.clip(rng.normal(-82 if regime == 1 else -54, 5), -100, -20)) if linked else None
            success = linked and rng.random() >= [0.005, 0.005, 0.005, 0.005, 0.7, 1, 0.2, 0.005][regime]
            center = 125 if regime == 2 else 65 if regime == 3 else base_latency
            spread = 55 if regime == 3 else 5
            rtt = float(np.clip(rng.normal(center, spread), 0.1, 500)) if success else None
            if success: last_success = now
            window.append((rssi, rtt, event))
            if len(window) != SCHEMA["window_samples"]: continue
            rs = [s[0] for s in window if s[0] is not None]
            ts = [s[1] for s in window if s[1] is not None]
            values = [float(np.mean(rs)) if rs else None, float(np.mean(ts)) if ts else None,
                      float(np.std(ts)) if ts else None, (len(window) - len(ts)) / len(window),
                      sum(s[2] for s in window), min(60000, now - last_success) if last_success is not None else None,
                      (now - connected_since) / 1000 if linked else 0]
            features = dict(zip(NAMES, values))
            # Raw synthetic windows explicitly have no model prediction until host C++ replay.
            prediction = LABELS[predict(model, features)] if model else None
            record = {"protocol_version": 1, "schema_version": 1, "firmware_version": "synthetic-1.0",
                      "source": "synthetic", "session_id": f"synthetic-{seed}-{session:03}", "sequence": slot - 9,
                      "model_id": model["model_id"] if model else "0000000000000000", "uptime_ms": now,
                      "state": ("degraded" if prediction in LABELS[1:] else "connected") if linked else "disconnected",
                      "features_valid": True, "diagnostic": "ok", "features": features, "prediction": prediction,
                      "prediction_origin": "python_reference" if model else "unpredicted_training_window",
                      "inference_us": 0, "extraction_us": 0, "probe_successes": len(ts), "probe_failures": len(window) - len(ts),
                      "disconnects_total": disconnects, "reconnect_attempts": attempts,
                      "reconnect_successes": outcomes, "reconnect_failures": 0}
            yield record


def write_dataset(path, **kwargs):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for record in generate(**kwargs): out.write(json.dumps(record, allow_nan=False) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=2210)
    p.add_argument("--sessions", type=int, default=18)
    p.add_argument("--slots", type=int, default=180)
    p.add_argument("--model", type=Path)
    a = p.parse_args()
    if a.sessions < 1 or a.slots < 10: p.error("need at least one session and ten slots")
    write_dataset(a.output, seed=a.seed, sessions=a.sessions, slots=a.slots, model=load_model(a.model) if a.model else None)
    print(f"Synthetic data: {a.output}; no physical ESP32 measurements")
