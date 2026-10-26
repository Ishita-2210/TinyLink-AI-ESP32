# Data and provenance

- `fixtures/synthetic.jsonl`: twelve selected deterministic snapshots, generated from seed 42 and classified by the native C++ implementation. Every row is `source=synthetic` and `prediction_origin=host_cpp_simulation`; never physical-device output. Original sequence numbers are retained, so replay correctly reports gaps between the selected snapshots.
- `fixtures/malformed.jsonl`: intentional invalid/noise lines for parser recovery demonstrations.
- `generated/`: ignored reproducible synthetic training data, seed 2210 by default. Run `python -m ml.synthetic --output data/generated/training.jsonl`. Eighteen sessions × 180 slots give 3078 complete ten-slot windows. Adjacent windows overlap; training separates entire sessions.
- `sessions/`: ignored real or replay recordings with host timestamps. Record each condition independently and retain source, session, firmware, protocol and model metadata. Never relabel synthetic rows as real.

Raw synthetic training windows have null `prediction` until a model is applied; they are dataset rows, not valid prediction telemetry. The training loader explicitly recognizes this source. `--model ml/artifacts/tree.json` produces clearly marked Python reference predictions for development. The end-to-end demo instead invokes the compiled C++ inference implementation.

No real Wi-Fi dataset was available during implementation. No accuracy on actual ESP32 measurements is claimed. Commit neither credentials nor large private recordings. CSV retains units through schema feature names, provenance and firmware/model identifiers; its column order is defined in `host/export.py`.
