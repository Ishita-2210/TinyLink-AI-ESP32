# Labeling policy v1 (defined before training)

This version classifies the **current** ten-slot observation window. It does not predict a future outage. It is an interpretable policy approximation experiment: a real trained decision tree compresses the policy into embedded branches. High synthetic accuracy measures implementation fidelity, not generalization to physical Wi-Fi networks.

Each slot occurs every 1000 ms and sends at most one 500 ms deadline UDP echo to a laptop on the same LAN. Disconnected slots count as failures of endpoint reachability. The window slides by one slot. Require ten fresh slots before inference; warmup or invalid windows produce a null prediction.

Policy, applied in this order after shared missing-value substitution:

1. **Unstable**: failure fraction >= 0.4, or at least two disconnects, or success age >= 5000 ms.
2. **Degrading**: failure fraction >= 0.1, or at least one disconnect, or RSSI < -75 dBm, or mean RTT >= 80 ms, or RTT standard deviation >= 30 ms.
3. **Stable**: otherwise.

These are explicit demonstration service objectives, not universal Wi-Fi standards. Missing RSSI maps to -127 dBm, no successful RTT to 1000 ms/500 ms standard deviation, and no success age to 60000 ms. Other missing values are invalid. Missing optional values are represented as JSON null, never as fabricated measurements. Exact policy evaluation is the oracle baseline; a training-set majority class is the trivial baseline. The small tree need not beat the policy that defines its labels.

Synthetic sessions sample changing channel/endpoint conditions, including outages, using a fixed seed. They are not evidence of interference detection, throughput, or future prediction. Hold out whole sessions in acquisition order; never split adjacent overlapping windows between train and test. Report source-stratified precision/recall/F1, confusion matrices, baseline comparisons and session IDs. Never combine synthetic and real results into an unlabeled score.

Real recording workflow: collect separate sessions under normal conditions, naturally weak signal, endpoint pause, and a permitted AP power cycle. These scenarios test distinct failure causes. Labels are derived from the same policy unless an independently annotated outcome is introduced under a new target/schema version. Before claiming future prediction, collect many independent real sessions and label subsequent non-overlapping outcome windows, purge boundary windows, and test on later held-out sessions/APs. Current features must never include that future window.
