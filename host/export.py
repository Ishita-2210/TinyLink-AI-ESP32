"""Validate a recorded session and flatten its actual telemetry to CSV."""
import argparse
import csv
from pathlib import Path

from host.protocol import parse_line
from host.schema import NAMES

FIELDS = ["host_timestamp", "session_id", "ingest_mode", "source", "firmware_version", "protocol_version", "schema_version",
          "model_id", "sequence", "uptime_ms", "state", "prediction", "features_valid", "diagnostic", "inference_us",
          "extraction_us", "disconnects_total", "reconnect_attempts", "reconnect_successes", "reconnect_failures"] + NAMES


def export_csv(source, target):
    count = rejected = 0
    target = Path(target); target.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open(encoding="utf-8") as stream, target.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS); writer.writeheader()
        for line in stream:
            try: record = parse_line(line)
            except ValueError: rejected += 1; continue
            row = {field: record.get(field) for field in FIELDS if field not in NAMES}
            row.update(record["features"]); writer.writerow(row); count += 1
    return count, rejected


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try: print("Exported, rejected:", export_csv(a.input, a.output))
    except OSError as exc: p.exit(2, f"export error: {exc}\n")
