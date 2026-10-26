"""Independent-feature challenge cases expose synthetic session shortcuts."""
from host.schema import NAMES


def cases():
    for rssi in (-90, -76, -75, -50):
        for mean in (5, 50, 80, 150):
            for std in (0, 29, 30, 60):
                for failure in (0, 0.1, 0.3, 0.4, 0.8):
                    for disconnects in (0, 1, 2):
                        yield dict(zip(NAMES, (rssi, mean, std, failure, disconnects, 0, 300)))
