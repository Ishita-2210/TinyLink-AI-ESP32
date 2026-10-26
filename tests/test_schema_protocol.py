import copy
import json
import subprocess
import sys

import numpy as np
import pytest

from host.protocol import parse_line
from host.schema import FEATURES, NAMES, ROOT, vector
from ml.policy import label


def test_schema_generated_current():
    subprocess.run([sys.executable, "scripts/generate_schema.py", "--check"], cwd=ROOT, check=True)


def test_valid_vector_and_missing_policy(record):
    f = record["features"]
    assert vector(f).dtype == np.float32
    for i in (0, 1, 2, 5):
        altered = dict(f); altered[NAMES[i]] = None
        assert vector(altered)[i] == FEATURES[i]["missing"]


@pytest.mark.parametrize("name,value", [("rssi_mean_dbm", -101), ("rtt_mean_ms", 501), ("rtt_std_ms", -1),
    ("probe_failure_rate", None), ("probe_failure_rate", 1.1), ("disconnect_count", 0.5),
    ("success_age_ms", float("inf")), ("connection_uptime_s", float("nan")), ("rssi_mean_dbm", True),
    ("rtt_mean_ms", "10"), ("connection_uptime_s", None)])
def test_invalid_feature(record, name, value):
    f = dict(record["features"]); f[name] = value
    with pytest.raises(ValueError): vector(f)


def test_feature_order_independent_and_exact_names(record):
    assert np.array_equal(vector(record["features"]), vector(dict(reversed(list(record["features"].items())))))
    with pytest.raises(ValueError): vector({**record["features"], "unknown": 1})
    with pytest.raises(ValueError): vector({})


@pytest.mark.parametrize("index,value,expected", [(0, -75, 0), (0, -75.1, 1), (1, 80, 1), (2, 30, 1),
    (3, 0.1, 1), (3, 0.4, 2), (4, 1, 1), (4, 2, 2), (5, 5000, 2)])
def test_label_policy_boundaries(index, value, expected):
    f = dict(zip(NAMES, [-50, 5, 0, 0, 0, 0, 300])); f[NAMES[index]] = value
    assert label(f) == expected


def test_missing_outage_label():
    assert label(dict(zip(NAMES, [None, None, None, 1, 0, None, 0]))) == 2


def test_parser_roundtrip(record):
    assert parse_line(json.dumps(record)) == record


@pytest.mark.parametrize("key,value", [("schema_version", 99), ("protocol_version", True), ("source", "cloud"),
    ("state", "unknown"), ("prediction", "excellent"), ("features_valid", 1), ("uptime_ms", -1),
    ("model_id", "bad"), ("inference_us", None), ("probe_failures", 99)])
def test_parser_bad_field(record, key, value):
    record[key] = value
    with pytest.raises(ValueError): parse_line(json.dumps(record))


@pytest.mark.parametrize("payload", ["no JSON", "[]", "null", "{}", "x"*4097, b"\xff"])
def test_parser_malformed(payload):
    with pytest.raises(ValueError): parse_line(payload)


def test_parser_incomplete_and_warmup(record):
    missing = copy.deepcopy(record); del missing["features"][NAMES[0]]
    with pytest.raises(ValueError): parse_line(json.dumps(missing))
    record.update(features_valid=False, prediction=None, diagnostic="warming_up", features=dict.fromkeys(NAMES))
    assert parse_line(json.dumps(record))["prediction"] is None
    record["prediction"] = "Stable"
    with pytest.raises(ValueError): parse_line(json.dumps(record))


def test_parser_inconsistent_rtt(record):
    record["features"]["rtt_mean_ms"] = None
    with pytest.raises(ValueError): parse_line(json.dumps(record))
