"""Summarize observed firmware timing from real serial sessions only."""
import argparse
import json
from pathlib import Path

import numpy as np

from host.protocol import parse_line


def summarize(path):
    records = [parse_line(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or any(r["source"] != "esp32" or r.get("ingest_mode") != "live_serial" for r in records):
        raise ValueError("benchmark requires a live_serial session with esp32 provenance; simulation is excluded")
    ready = [r for r in records if r["features_valid"]]
    if not ready: raise ValueError("no complete feature windows")
    report = {"source": "recorded ESP32 serial telemetry", "records": len(records), "complete_windows": len(ready),
              "model_ids": sorted({r["model_id"] for r in ready}),
              "note": "Microsecond timer resolution includes call overhead; zero means below resolution, not free inference.",
              "state_transitions": sum(a["state"] != b["state"] for a, b in zip(records, records[1:])),
              "timing": {}}
    for key in ("inference_us", "extraction_us"):
        values = np.array([r[key] for r in ready])
        report["timing"][key] = {"min": int(values.min()), "median": float(np.median(values)),
                                 "p95": float(np.percentile(values, 95)), "max": int(values.max())}
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    a = p.parse_args()
    try: print(json.dumps(summarize(a.input), indent=2))
    except (ValueError, OSError) as exc: p.exit(2, f"benchmark error: {exc}\n")
