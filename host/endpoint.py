"""Local LAN UDP echo endpoint; no internet endpoint or inference service."""
import argparse
import re
import socket
import time

PROBE = re.compile(rb"TL1:[0-9a-f]{8}:[0-9a-f]{8}")


def echo_once(sock):
    data, peer = sock.recvfrom(256)
    if PROBE.fullmatch(data):
        sock.sendto(data, peer)
        return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=3333)
    p.add_argument("--duration", type=float, default=0)
    a = p.parse_args()
    if not 1 <= a.port <= 65535 or a.duration < 0: p.error("invalid port/duration")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((a.bind, a.port)); sock.settimeout(0.25)
            print(f"UDP echo ready on {a.bind}:{a.port}. Ctrl+C to stop.", flush=True)
            deadline = time.monotonic() + a.duration if a.duration else float("inf")
            while time.monotonic() < deadline:
                try: echo_once(sock)
                except socket.timeout: pass
    except KeyboardInterrupt: pass
    except OSError as exc: p.exit(2, f"endpoint error: {exc}\n")


if __name__ == "__main__": main()
