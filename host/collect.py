"""Resilient serial/recording collector with bounded framing and explicit provenance."""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
import uuid

import serial
from serial.tools import list_ports

from host.protocol import MAX_LINE, parse_line


@dataclass
class Stats:
    accepted: int = 0
    rejected: int = 0
    state_changes: int = 0
    sequence_gaps: int = 0
    device_resets: int = 0
    serial_failures: int = 0


class Framer:
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, chunk):
        for byte in chunk:
            if byte == 10:
                if self.discarding:
                    yield None
                elif self.buffer:
                    yield bytes(self.buffer)
                self.buffer.clear(); self.discarding = False
            elif not self.discarding:
                if len(self.buffer) >= MAX_LINE:
                    self.buffer.clear(); self.discarding = True
                else: self.buffer.append(byte)


class Recorder:
    def __init__(self, output, callback=None, replay=False):
        self.path = Path(output)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse accidental recording overwrite. New path/session for each acquisition.
        self.stream = self.path.open("x", encoding="utf-8", newline="\n")
        self.stats = Stats()
        self.session = uuid.uuid4().hex
        self.callback = callback
        self.replay = replay
        self.previous = None

    def accept(self, line):
        try:
            if line is None: raise ValueError("oversized frame discarded")
            record = parse_line(line)
            if not self.replay and record["source"] != "esp32":
                raise ValueError("live serial requires ESP32 provenance")
        except (ValueError, TypeError) as exc:
            self.stats.rejected += 1
            if self.stats.rejected <= 5 or self.stats.rejected % 100 == 0:
                print(f"Rejected record #{self.stats.rejected}: {exc}", file=sys.stderr)
            return None
        if self.previous:
            old = self.previous
            same_session = not self.replay or old.get("session_id") == record.get("session_id")
            if same_session:
                self.stats.state_changes += record["state"] != old["state"]
                if record["sequence"] <= old["sequence"] or record["uptime_ms"] < old["uptime_ms"]:
                    self.session = uuid.uuid4().hex; self.stats.device_resets += 1
                else: self.stats.sequence_gaps += max(0, record["sequence"] - old["sequence"] - 1)
        if self.replay: record.setdefault("session_id", self.session)
        else: record["session_id"] = self.session
        record["host_timestamp"] = datetime.now(timezone.utc).isoformat()
        record["ingest_mode"] = "recorded_replay" if self.replay else "live_serial"
        self.stream.write(json.dumps(record, allow_nan=False) + "\n"); self.stream.flush()
        self.stats.accepted += 1; self.previous = record
        if self.callback: self.callback(record)
        return record

    def close(self):
        self.stream.close()
        self.path.with_suffix(self.path.suffix + ".stats.json").write_text(json.dumps(asdict(self.stats), indent=2) + "\n", encoding="utf-8")


def discover_port():
    ports = [p for p in list_ports.comports() if p.vid is not None]
    if len(ports) != 1:
        raise ValueError(f"found {len(ports)} USB serial candidates; use --list-ports then --port COMx")
    return ports[0].device


def collect_live(recorder, port, duration=0, stop=None):
    stop = stop or threading.Event()
    deadline = time.monotonic() + duration if duration else float("inf")
    errors = 0
    while not stop.is_set() and time.monotonic() < deadline:
        framer = Framer()
        try:
            with serial.Serial(port, 115200, timeout=0.25) as device:
                while not stop.is_set() and time.monotonic() < deadline:
                    chunk = device.read(min(max(device.in_waiting, 1), 4096))
                    if not chunk: continue
                    for line in framer.feed(chunk): recorder.accept(line)
        except (serial.SerialException, OSError) as exc:
            errors += 1; recorder.stats.serial_failures += 1
            print(f"Serial failure ({errors}/5): {exc}", file=sys.stderr)
            if errors >= 5: raise ValueError("serial connection failed five times; recording saved") from exc
            stop.wait(min(2**(errors - 1), 8))


def replay_file(path, recorder):
    framer = Framer()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(8192):
            for line in framer.feed(chunk): recorder.accept(line)
    if framer.buffer or framer.discarding:
        recorder.stats.rejected += 1
        print("Rejected incomplete final frame", file=sys.stderr)


def display(record):
    features = record["features"]
    print(f"[{record['source']}] {record['uptime_ms']/1000:8.1f}s {record['state']:12} "
          f"RSSI={features['rssi_mean_dbm']} dBm RTT={features['rtt_mean_ms']} ms "
          f"prediction={record['prediction']} ({record['diagnostic']})")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list-ports", action="store_true")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--port"); source.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--duration", type=float, default=0)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()
    if a.list_ports:
        for port in list_ports.comports(): print(f"{port.device}: {port.description} USB={port.vid is not None}")
        return
    if a.output is None or a.duration < 0: p.error("--output is required; duration must be nonnegative")
    if a.input and a.input.resolve() == a.output.resolve(): p.error("input and output must differ")
    recorder = None
    try:
        recorder = Recorder(a.output, callback=None if a.quiet else display, replay=a.input is not None)
        if a.input: replay_file(a.input, recorder)
        else: collect_live(recorder, a.port or discover_port(), a.duration)
    except KeyboardInterrupt: print("Recording stopped; saved complete records.")
    except (ValueError, OSError) as exc: p.exit(2, f"collector error: {exc}\n")
    finally:
        if recorder:
            recorder.close(); print(json.dumps(asdict(recorder.stats)))


if __name__ == "__main__": main()
