"""Lightweight matplotlib monitor. Displays wire predictions without recomputing them."""
import argparse
from collections import deque
from pathlib import Path
import queue
import threading

from host.collect import Recorder, collect_live, discover_port
from host.protocol import parse_line


def read_records(path):
    records, rejected = [], 0
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            try: records.append(parse_line(line))
            except ValueError: rejected += 1
    print(f"Loaded {len(records)} records, rejected {rejected}.")
    if not records: raise ValueError("no valid records to display")
    return records


def draw(fig, axes, records, mode):
    for ax in axes: ax.clear()
    if not records:
        fig.suptitle(f"TinyLink AI | {mode} | waiting for telemetry")
        return
    t = [r["uptime_ms"] / 1000 for r in records]
    rssi = [r["features"]["rssi_mean_dbm"] for r in records]
    latency = [r["features"]["rtt_mean_ms"] for r in records]
    axes[0].plot(t, rssi, color="#168c7a", linewidth=1.5)
    axes[1].plot(t, latency, color="#ec943a", linewidth=1.5)
    axes[0].set_ylabel("RSSI (dBm)"); axes[1].set_ylabel("UDP RTT mean (ms)")
    axes[1].set_xlabel("Device uptime (s)")
    events = 0
    for old, current in zip(records, list(records)[1:]):
        if old["state"] != current["state"] or old["disconnects_total"] != current["disconnects_total"]:
            events += 1
            for ax in axes: ax.axvline(current["uptime_ms"]/1000, color="#b65e70", linestyle=":", alpha=0.5)
    for ax in axes: ax.grid(alpha=0.2)
    last = records[-1]
    sources = ", ".join(sorted({r["source"] for r in records}))
    fig.suptitle(f"TinyLink AI | {mode} | source: {sources}\n{last['state']} | prediction: {last['prediction']} | "
                 f"{last['diagnostic']} | transitions: {events} | disconnects: {last['disconnects_total']}")
    fig.tight_layout(rect=(0, 0, 1, 0.90))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path); group.add_argument("--port")
    p.add_argument("--save-session", type=Path)
    p.add_argument("--output", type=Path, help="Render recorded data to PNG without a display")
    a = p.parse_args()
    if a.port and (not a.save_session or a.output): p.error("live mode requires --save-session and an interactive display")
    if a.output:
        import matplotlib
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    try:
        if a.input:
            draw(fig, axes, read_records(a.input), "recorded data")
            if a.output:
                a.output.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(a.output, dpi=130); print(f"Saved {a.output}")
            else: plt.show()
        else:
            from matplotlib.animation import FuncAnimation
            incoming = queue.Queue(maxsize=256)
            recent = deque(maxlen=180)
            stop = threading.Event()
            failures = []
            def push(record):
                if incoming.full(): incoming.get_nowait()
                incoming.put_nowait(record)
            recorder = Recorder(a.save_session, callback=push)
            def worker():
                try: collect_live(recorder, discover_port() if a.port == "auto" else a.port, stop=stop)
                except (ValueError, OSError) as exc: failures.append(str(exc))
                finally: recorder.close()
            thread = threading.Thread(target=worker, daemon=True); thread.start()
            def update(_):
                while not incoming.empty(): recent.append(incoming.get_nowait())
                draw(fig, axes, list(recent), "live serial" + (f" | ERROR: {failures[-1]}" if failures else ""))
            animation = FuncAnimation(fig, update, interval=1000, cache_frame_data=False)
            try: plt.show()
            finally: stop.set(); thread.join(timeout=3)
    except (ValueError, OSError) as exc: p.exit(2, f"monitor error: {exc}\n")
    finally: plt.close(fig)


if __name__ == "__main__": main()
