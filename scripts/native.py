"""Build portable firmware tests using system C++ or the pinned Windows Zig compiler."""
import importlib.util
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def compiler():
    for name in ("g++", "clang++"):
        found = shutil.which(name)
        if found: return [found]
    if importlib.util.find_spec("ziglang") is not None:
        return [sys.executable, "-m", "ziglang", "c++"]
    raise RuntimeError("No native C++ compiler. Windows: pip install ziglang==0.14.1; Linux: install g++")


def compile_cpp(source, output):
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    command = compiler() + ["-std=c++17", "-O2", "-UNDEBUG", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware/include"), str(source), "-o", str(output)]
    # Zig cross-platform native compilation is CPU-bound on its first run.
    subprocess.run(command, check=True, cwd=ROOT, timeout=300)
    return output


def build_runner():
    output = ROOT / "build" / ("model_runner.exe" if os.name == "nt" else "model_runner")
    dependencies = [ROOT / "tests/cpp/model_runner.cpp", *sorted((ROOT / "firmware/include").glob("*.h"))]
    digest = hashlib.sha256(Path(__file__).read_bytes() + b"".join(p.read_bytes() for p in dependencies)).hexdigest()
    stamp = output.with_suffix(".sha256")
    if not output.exists() or not stamp.exists() or stamp.read_text() != digest:
        compile_cpp(dependencies[0], output)
        stamp.write_text(digest)
    return output


if __name__ == "__main__": print(build_runner())
