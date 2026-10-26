"""Synthetic -> native C++ inference -> telemetry -> recorder -> CSV/PNG demo."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from host.collect import Recorder
from host.export import export_csv
from host.schema import LABELS, NAMES, ROOT
from ml.model import load_model, predict
from ml.synthetic import generate
from scripts.native import build_runner


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=Path("build/demo"))
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    runner = build_runner()
    model = load_model(ROOT / "ml/artifacts/tree.json")
    records = list(generate(seed=42, sessions=1, slots=240))
    payload = "".join(" ".join("nan" if r["features"][key] is None else str(r["features"][key]) for key in NAMES) + "\n" for r in records)
    result = subprocess.run([str(runner), "--telemetry"], input=payload, text=True, capture_output=True, check=True, timeout=30)
    wires = [json.loads(line) for line in result.stdout.splitlines()]
    if len(wires) != len(records): raise AssertionError("incomplete C++ replay")
    target = a.output_dir / "session.jsonl"
    recorder = Recorder(target, replay=True)
    try:
        # Deliberately exercise boot noise and incompatible telemetry recovery.
        recorder.accept(b"ESP32 boot noise")
        recorder.accept(b'{"protocol_version":99}')
        for raw, wire in zip(records, wires):
            if wire["prediction"] != LABELS[predict(model, raw["features"])]: raise AssertionError("C++ / Python mismatch")
            # C++ serializer supplied all feature fields/predictions; source remains synthetic.
            wire.update({key: raw[key] for key in ("source", "session_id", "uptime_ms", "sequence", "state", "disconnects_total", "reconnect_attempts", "reconnect_successes")})
            wire["prediction_origin"] = "host_cpp_simulation"
            wire["firmware_version"] = "host-cpp-simulation-1.0"
            if wire["state"] == "connected" and wire["prediction"] != "Stable": wire["state"] = "degraded"
            if recorder.accept(json.dumps(wire)) is None: raise AssertionError("demo telemetry rejected")
    finally: recorder.close()
    count, rejected = export_csv(target, a.output_dir / "session.csv")
    subprocess.run([sys.executable, "-m", "host.monitor", "--input", str(target), "--output", str(a.output_dir / "session.png")], check=True, timeout=60)
    print(json.dumps({"source": "synthetic", "inference": "native C++ (not physical ESP32)",
                      "collector": asdict(recorder.stats), "csv_rows": count, "csv_rejected": rejected}, indent=2))


if __name__ == "__main__": main()
