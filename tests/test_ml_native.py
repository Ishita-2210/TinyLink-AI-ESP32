import json
import copy
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from host.protocol import parse_line
from host.schema import FEATURES, NAMES, ROOT, vector
from ml.challenge import cases
from ml.model import export_header, fingerprint, load_model, predict, predict_vector
from ml.synthetic import generate, write_dataset
from ml.train import load_dataset, metrics, train
from scripts.native import compile_cpp


def test_synthetic_deterministic():
    assert list(generate(sessions=1, slots=30)) == list(generate(sessions=1, slots=30))
    assert list(generate(seed=2, sessions=1, slots=30)) != list(generate(seed=1, sessions=1, slots=30))


def test_training_reproducible_artifacts(tmp_path):
    data = tmp_path / "data.jsonl"
    write_dataset(data)
    report = train(data, tmp_path / "artifacts", tmp_path / "tree.h")
    assert load_model(tmp_path / "artifacts/tree.json") == load_model(ROOT / "ml/artifacts/tree.json")
    assert (tmp_path / "tree.h").read_text() == (ROOT / "firmware/include/model_generated.h").read_text()
    groups = [set(report["split"][key]) for key in ("train", "validation", "test")]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert report["real_data_windows"] == 0
    assert report["test_by_source"]["synthetic"]["model"]["accuracy"] > 0.8


def test_dataset_rejects_empty_missing_session_reset(tmp_path, record):
    data = tmp_path / "data.jsonl"; data.write_text("")
    with pytest.raises(ValueError, match="no complete"): load_dataset(data)
    del record["session_id"]; data.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="session_id"): load_dataset(data)
    record["session_id"] = "test"; data.write_text((json.dumps(record) + "\n")*2)
    with pytest.raises(ValueError, match="uptime reset"): load_dataset(data)
    data.write_text("[]\n")
    with pytest.raises(ValueError, match="record must be an object"): load_dataset(data)


def test_dataset_no_session_leakage(tmp_path, record):
    rows = []
    for sid in ("a", "b", "a"):
        rows.append(dict(record, session_id=sid))
    data = tmp_path / "bad.jsonl"; data.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match="contiguous"): load_dataset(data)
    data.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="independent sessions"): train(data, tmp_path / "out", tmp_path / "out.h")


def test_metrics_known_confusion():
    report = metrics([0, 1, 2, 2], [0, 2, 2, 1])
    assert report["accuracy"] == 0.5
    assert report["confusion_matrix"] == [[1,0,0], [0,0,1], [0,1,1]]
    assert report["per_class"]["Stable"]["recall"] == 1


def test_model_tamper_and_topology(tmp_path, model):
    model = copy.deepcopy(model)
    data = tmp_path / "model.json"
    model["model_id"] = "0"*16; data.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="fingerprint"): load_model(data)
    model["nodes"][0]["left"] = 0; model["model_id"] = fingerprint(model); data.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="topology"): load_model(data)
    model["nodes"] = [None]; model["model_id"] = fingerprint(model); data.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="tree size"): load_model(data)
    data.write_text("[]")
    with pytest.raises(ValueError, match="model must be an object"): load_model(data)


def test_exported_header_current(model):
    assert export_header(model) == (ROOT / "firmware/include/model_generated.h").read_text()


def equivalence_vectors(model):
    values = [r["features"] for r in generate()]
    values.extend(cases())
    rng = np.random.default_rng(123)
    for _ in range(5000):
        row = {}
        for f in FEATURES:
            value = float(rng.uniform(f["min"], f["max"]))
            if f["name"] == "disconnect_count": value = int(value)
            if f["missing"] is not None and rng.random() < 0.1: value = None
            row[f["name"]] = value
        values.append(row)
    for node in model["nodes"]:
        if "threshold" not in node: continue
        v = np.float32(node["threshold"])
        for point in (np.nextafter(v, np.float32(-np.inf)), v, np.nextafter(v, np.float32(np.inf))):
            if FEATURES[node["feature"]]["min"] <= point <= FEATURES[node["feature"]]["max"]:
                row = dict(zip(NAMES, [-50, 5, 0, 0, 0, 0, 300]))
                if node["feature"] == 4 and point != int(point): continue
                row[NAMES[node["feature"]]] = float(point); values.append(row)
    return values


def test_python_cpp_equivalence_random_missing_thresholds(runner, model, tmp_path):
    rows = equivalence_vectors(model)
    payload = "".join(" ".join("nan" if r[k] is None else str(r[k]) for k in NAMES) + "\n" for r in rows)
    actual = subprocess.run([str(runner)], input=payload, text=True, capture_output=True, check=True, timeout=30)
    got = [int(v) for v in actual.stdout.splitlines()]
    expected = [predict(model, row) for row in rows]
    assert got == expected
    print(f"Python/C++ equivalence: {len(rows)} vectors")


def test_cpp_invalid_input(runner):
    result = subprocess.run([str(runner)], input="-101 10 0 0 0 0 10\n-50 10 0 nan 0 0 10\n", text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == ["-1", "-1"]
    assert subprocess.run([str(runner)], input="not-a-number\n", text=True, capture_output=True).returncode == 2


def test_portable_firmware_assertions(tmp_path):
    target = tmp_path / ("core_tests.exe" if os.name == "nt" else "core_tests")
    compile_cpp(ROOT / "tests/cpp/core_test.cpp", target)
    result = subprocess.run([str(target)], text=True, capture_output=True, check=True, timeout=30)
    assert "assertions passed" in result.stdout


def test_cpp_serialization_roundtrip(runner):
    result = subprocess.run([str(runner), "--telemetry"], input="-50 5 0 0 0 0 300\nnan nan nan 1 0 nan 0\n", text=True, capture_output=True, check=True)
    records = [parse_line(line) for line in result.stdout.splitlines()]
    assert [r["prediction"] for r in records] == ["Stable", "Unstable"]
    assert all(r["source"] == "host_cpp" for r in records)
