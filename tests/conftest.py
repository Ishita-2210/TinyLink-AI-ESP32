import json

import pytest

from host.schema import ROOT
from ml.model import load_model
from ml.synthetic import generate
from scripts.native import build_runner


@pytest.fixture(scope="session")
def model():
    return load_model(ROOT / "ml/artifacts/tree.json")


@pytest.fixture
def record(model):
    return next(generate(seed=1, sessions=1, slots=20, model=model))


@pytest.fixture(scope="session")
def runner():
    return build_runner()
