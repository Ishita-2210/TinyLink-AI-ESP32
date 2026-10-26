import csv
import json
import socket
import threading

import pytest
import serial

from host.collect import Framer, Recorder, collect_live, replay_file
from host.endpoint import echo_once
from host.export import export_csv
from host.monitor import draw, read_records
from host.benchmark import summarize


def test_framer_fragmentation_oversize_recovery():
    f = Framer()
    assert list(f.feed(b'{"a":')) == []
    assert list(f.feed(b'1}\n')) == [b'{"a":1}']
    assert list(f.feed(b'x'*6000)) == []
    assert len(f.buffer) <= 4096
    assert list(f.feed(b'\n{}\n')) == [None, b'{}']


def test_recorder_replay_events_reset_export(tmp_path, record):
    source = tmp_path / "input.jsonl"
    first = dict(record, sequence=1, uptime_ms=10000, state="connected")
    second = dict(record, sequence=4, uptime_ms=11000, state="disconnected")
    third = dict(record, sequence=0, uptime_ms=500, state="recovering")
    source.write_text("boot\n" + json.dumps(first) + "\n{\"schema_version\":99}\n" + json.dumps(second) + "\n" + json.dumps(third) + "\n")
    target = tmp_path / "recording.jsonl"
    recorder = Recorder(target, replay=True)
    try: replay_file(source, recorder)
    finally: recorder.close()
    assert recorder.stats.accepted == 3 and recorder.stats.rejected == 2
    assert recorder.stats.state_changes == 2 and recorder.stats.sequence_gaps == 2 and recorder.stats.device_resets == 1
    assert export_csv(target, tmp_path / "session.csv") == (3, 0)
    rows = list(csv.DictReader((tmp_path / "session.csv").open()))
    assert rows[0]["source"] == "synthetic" and rows[0]["host_timestamp"]
    assert len(read_records(target)) == 3


def test_live_serial_chunks_and_provenance(tmp_path, record, monkeypatch):
    stop = threading.Event()
    record["source"] = "esp32"  # Mock transport fixture only, never a hardware measurement.
    payload = json.dumps(record).encode() + b"\n"
    chunks = [payload[:50], payload[50:]]
    class FakeSerial:
        in_waiting = 500
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n):
            if chunks: return chunks.pop(0)
            stop.set(); return b""
    monkeypatch.setattr(serial, "Serial", FakeSerial)
    recorder = Recorder(tmp_path / "live.jsonl")
    try: collect_live(recorder, "mock-port", stop=stop)
    finally: recorder.close()
    assert recorder.stats.accepted == 1
    assert recorder.previous["ingest_mode"] == "live_serial"


def test_live_rejects_synthetic(tmp_path, record):
    recorder = Recorder(tmp_path / "live.jsonl")
    try: assert recorder.accept(json.dumps(record)) is None
    finally: recorder.close()
    assert recorder.stats.rejected == 1


def test_serial_failure_bounded_retry(tmp_path, monkeypatch):
    class Stop:
        def is_set(self): return False
        def wait(self, seconds): pass
    def fail(*args, **kwargs): raise serial.SerialException("mock unplug")
    monkeypatch.setattr(serial, "Serial", fail)
    recorder = Recorder(tmp_path / "failed.jsonl")
    try:
        with pytest.raises(ValueError, match="five times"): collect_live(recorder, "mock", stop=Stop())
    finally: recorder.close()
    assert recorder.stats.serial_failures == 5


def test_recording_refuses_overwrite(tmp_path):
    target = tmp_path / "existing.jsonl"; target.write_text("keep")
    with pytest.raises(FileExistsError): Recorder(target)
    assert target.read_text() == "keep"


def test_incomplete_frame_rejected(tmp_path):
    source = tmp_path / "partial.jsonl"; source.write_text("partial frame")
    recorder = Recorder(tmp_path / "output.jsonl", replay=True)
    try: replay_file(source, recorder)
    finally: recorder.close()
    assert recorder.stats.rejected == 1


def test_udp_endpoint_loopback():
    # Actual host UDP sockets; no ESP32 or router claim.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        server.bind(("127.0.0.1", 0)); server.settimeout(2); client.settimeout(2)
        for payload, expected in ((b"bad", False), (b"TL1:12345678:00000001", True)):
            client.sendto(payload, server.getsockname())
            assert echo_once(server) is expected
            if expected: assert client.recvfrom(256)[0] == payload


def test_headless_monitor_labels_provenance(tmp_path, record):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1)
    draw(fig, axes, [record], "recorded data")
    fig.savefig(tmp_path / "plot.png")
    assert "synthetic" in fig._suptitle.get_text()
    plt.close(fig)


def test_benchmark_refuses_simulation(tmp_path, record):
    path = tmp_path / "synthetic.jsonl"; path.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="simulation is excluded"): summarize(path)


def test_benchmark_mock_timing_summary(tmp_path, record):
    path = tmp_path / "mock.jsonl"
    # Explicit mock fixture; not recorded as a hardware benchmark artifact.
    records = [dict(record, source="esp32", ingest_mode="live_serial", inference_us=i, extraction_us=i*2) for i in (1, 3, 5)]
    path.write_text("\n".join(json.dumps(r) for r in records))
    report = summarize(path)
    assert report["timing"]["inference_us"]["median"] == 3
    assert report["timing"]["extraction_us"]["max"] == 10
