"""Train/validate/test on distinct ordered sessions and export the chosen tree."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.tree import DecisionTreeClassifier

from host.protocol import parse_line
from host.schema import LABELS, NAMES, SCHEMA, SCHEMA_HASH, vector
from ml.model import export_header, fingerprint, predict_vector
from ml.policy import label
from ml.challenge import cases


def load_dataset(path):
    rows, session_source, order, last_ms = [], {}, [], {}
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
                if not isinstance(record, dict): raise ValueError("dataset record must be an object")
                # Unpredicted raw synthetic windows are training data, not wire telemetry.
                if record.get("source") == "synthetic" and record.get("prediction") is None:
                    candidate = dict(record, prediction="Stable")
                else: candidate = record
                record_checked = parse_line(json.dumps(candidate))
                if not record_checked["features_valid"]: continue
                session = record.get("session_id")
                if not isinstance(session, str) or not session:
                    raise ValueError("session_id required; collect one recording per session")
                source = record["source"]
                if source not in {"esp32", "synthetic"}: raise ValueError("training requires esp32 or synthetic provenance")
                if session in session_source and session_source[session] != source: raise ValueError("mixed session provenance")
                if session not in session_source: order.append(session)
                elif session != order[-1]: raise ValueError("session rows must be contiguous in acquisition order")
                if record["uptime_ms"] <= last_ms.get(session, -1): raise ValueError("uptime reset or duplicate; start a new session")
                session_source[session] = source; last_ms[session] = record["uptime_ms"]
                rows.append(record)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not rows: raise ValueError("dataset has no complete windows")
    return rows, order


def metrics(y, prediction):
    return {"accuracy": float(accuracy_score(y, prediction)),
            "macro_f1": float(f1_score(y, prediction, labels=[0, 1, 2], average="macro", zero_division=0)),
            "per_class": classification_report(y, prediction, labels=[0, 1, 2], target_names=LABELS, output_dict=True, zero_division=0),
            "confusion_matrix": confusion_matrix(y, prediction, labels=[0, 1, 2]).tolist()}


def train(path, output, header):
    rows, sessions = load_dataset(path)
    if len(sessions) < 6: raise ValueError("need >=6 independent sessions for train/validation/test")
    n_hold = max(1, len(sessions) // 6)
    train_ids, val_ids, test_ids = sessions[:-2*n_hold], sessions[-2*n_hold:-n_hold], sessions[-n_hold:]
    x = np.array([vector(r["features"]) for r in rows], dtype=np.float32)
    y = np.array([label(r["features"]) for r in rows])
    masks = {name: np.array([r["session_id"] in ids for r in rows])
             for name, ids in (("train", train_ids), ("validation", val_ids), ("test", test_ids))}
    if set(y[masks["train"]]) != {0, 1, 2}: raise ValueError("training must contain all three classes")
    candidates = []
    for depth in range(2, 9):
        tree = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=5, random_state=2210)
        tree.fit(x[masks["train"]], y[masks["train"]])
        score = f1_score(y[masks["validation"]], tree.predict(x[masks["validation"]]), labels=[0, 1, 2], average="macro", zero_division=0)
        candidates.append((tree, float(score)))
    best = max(score for _, score in candidates)
    tree, score = min((c for c in candidates if c[1] >= best - 0.01), key=lambda c: c[0].tree_.node_count)
    nodes = []
    for i in range(tree.tree_.node_count):
        if tree.tree_.children_left[i] == -1:
            nodes.append({"prediction": int(tree.classes_[np.argmax(tree.tree_.value[i][0])])})
        else:
            nodes.append({"feature": int(tree.tree_.feature[i]), "threshold": float(tree.tree_.threshold[i]),
                          "left": int(tree.tree_.children_left[i]), "right": int(tree.tree_.children_right[i])})
    model = {"schema_version": SCHEMA["schema_version"], "schema_sha256": SCHEMA_HASH, "features": NAMES, "labels": LABELS,
             "target": "current-window policy v1 approximation", "nodes": nodes,
             "training_sessions": train_ids, "training_sources": sorted({r["source"] for r, keep in zip(rows, masks["train"]) if keep})}
    model["model_id"] = fingerprint(model)
    exported = np.array([predict_vector(model, v) for v in x])
    if not np.array_equal(exported, tree.predict(x)): raise AssertionError("JSON export disagrees with sklearn")
    majority = Counter(y[masks["train"]]).most_common(1)[0][0]
    report = {"model_id": model["model_id"], "target": model["target"], "physical_hardware_tested": False,
              "real_data_windows": sum(r["source"] == "esp32" for r in rows), "total_windows": len(rows),
              "split": {"train": train_ids, "validation": val_ids, "test": test_ids},
              "selected_depth": tree.get_depth(), "nodes": len(nodes), "validation_macro_f1": score,
              "candidates": [{"depth": t.get_depth(), "nodes": t.tree_.node_count, "validation_macro_f1": v} for t, v in candidates],
              "test_by_source": {}, "test_by_session": {}}
    for source in sorted({r["source"] for r in rows}):
        keep = masks["test"] & np.array([r["source"] == source for r in rows])
        if not np.any(keep): continue
        report["test_by_source"][source] = {"windows": int(keep.sum()), "model": metrics(y[keep], exported[keep]),
                                          "majority_baseline": metrics(y[keep], np.full(keep.sum(), majority)),
                                          "policy_oracle": metrics(y[keep], y[keep])}
    challenge = list(cases())
    report["independent_feature_challenge"] = metrics([label(f) for f in challenge], [predict_vector(model, vector(f)) for f in challenge])
    for session in test_ids:
        keep = np.array([r["session_id"] == session for r in rows])
        report["test_by_session"][session] = metrics(y[keep], exported[keep])
    output, header = Path(output), Path(header)
    output.mkdir(parents=True, exist_ok=True); header.parent.mkdir(parents=True, exist_ok=True)
    (output / "tree.json").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    header.write_text(export_header(model), encoding="utf-8", newline="\n")
    report["artifact_json_bytes"] = (output / "tree.json").stat().st_size
    report["generated_header_bytes"] = header.stat().st_size
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("ml/artifacts"))
    p.add_argument("--header", type=Path, default=Path("firmware/include/model_generated.h"))
    a = p.parse_args()
    try:
        result = train(a.data, a.output, a.header)
    except ValueError as exc: p.exit(2, f"training error: {exc}\n")
    print(json.dumps(result, indent=2))
