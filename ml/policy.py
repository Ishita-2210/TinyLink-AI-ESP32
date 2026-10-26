"""The declared target and oracle baseline, not the deployed trained model."""
from host.schema import vector


def label(features):
    rssi, mean, std, failure, disconnects, age, _ = vector(features)
    if failure >= 0.4 or disconnects >= 2 or age >= 5000:
        return 2
    if failure >= 0.1 or disconnects >= 1 or rssi < -75 or mean >= 80 or std >= 30:
        return 1
    return 0
