"""Run reproducible local checks and save actual logs/measurements under build/."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

from host.schema import ROOT


def run(name, arguments, timeout):
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    output = result.stdout + result.stderr
    (ROOT / "build" / f"{name}.log").write_text(output, encoding="utf-8")
    print(output, end="", flush=True)
    if result.returncode: raise SystemExit(f"{name} failed with exit code {result.returncode}; see build/{name}.log")
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--firmware", action="store_true")
    a = p.parse_args()
    (ROOT / "build").mkdir(exist_ok=True)
    run("schema-check", ["scripts/generate_schema.py", "--check"], 30)
    tests = run("tests", ["-u", "-m", "pytest", "-ra", "-o", "faulthandler_timeout=60"], 600)
    report = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
              "hardware_tested": False, "tests": re.search(r"\d+ passed[^\n]*", tests).group(0)}
    if a.firmware:
        output = run("firmware-build", ["-m", "platformio", "run", "--project-dir", "firmware"], 900)
        for label in ("RAM", "Flash"):
            match = re.search(label + r":.*?used (\d+) bytes from (\d+) bytes", output)
            if match: report[label.lower() + "_bytes"] = {"used": int(match[1]), "capacity": int(match[2])}
        binary = ROOT / "firmware/.pio/build/esp32dev/firmware.bin"
        report["binary_file_bytes"] = binary.stat().st_size
    (ROOT / "build/verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
