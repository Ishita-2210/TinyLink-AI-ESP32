# Executed validation — 27 October 2026

## Host and cross-build evidence

Windows, Python 3.13.3, pinned dependencies, Zig 0.14.1 native C++17 compiler. `python -m scripts.verify --firmware` completed successfully: **65 passed, zero failed** (4.47 s for that recorded pytest run). The native assertions explicitly compile with `-UNDEBUG`; disabled assertions are a compile error. Python/native C++ inference agrees on **9071 vectors**: 3078 synthetic session windows, 960 independent-feature combinations, 5000 random/missing vectors and 33 valid neighbors of trained split thresholds. JSON export also agrees with sklearn on every development window. Source/header/model contract drift is rejected.

The final build targets **esp32dev**, PlatformIO Core 6.1.18, Espressif platform 8.0.0, Arduino-ESP32 3.3.12, Xtensa GCC 14.2.0+20260121. **945720 bytes** linked flash usage out of the 1310720-byte application partition; **49864 bytes** static RAM out of 327680. `.bin` file: **956976 bytes**, using different accounting from the linker report. These are credential-free build measurements; runtime heap/stack are not measured.

The seed-42 C++ demonstration produced **231 accepted records**, deliberately rejected **2 malformed messages**, recorded **9 state transitions**, no sequence gaps/resets, and exported **231 CSV rows** plus a PNG. Actual host loopback UDP sockets, simulated serial disconnects/retries, bounded framing, reboot/session handling, headless plotting and CSV export were tested. Serial transport tests use mocks, not a USB ESP32. Raw execution logs and `verification.json` are under ignored `build/`; reproducible commands are in the README.

## Model evidence (synthetic only)

Model `ab8dbd39bad830ec`: **25 nodes**, depth **5**. Artifact JSON **2569 bytes**, generated C++ header **1882 bytes**; these text sizes are not inference machine-code size. Training uses 12 entire sessions, validation 3, and test 3. Test set: **513 windows**. The report includes each held-out session separately and has **zero real-data windows**.

| Class | Precision | Recall | F1 | Test support |
| --- | ---: | ---: | ---: | ---: |
| Stable | 0.98246 | 0.98246 | 0.98246 | 57 |
| Degrading | 0.99618 | 0.99618 | 0.99618 | 262 |
| Unstable | 1.00000 | 1.00000 | 1.00000 | 194 |

Overall synthetic accuracy: **99.6101%**; macro-F1 **0.99288**. Confusion matrix (rows true, columns predicted; Stable/Degrading/Unstable): `[[56,1,0],[1,261,0],[0,0,194]]`. Majority baseline accuracy: **51.0721%**; exact labeling-policy oracle: **100%**.

The independent-feature stress grid scores **85.4167% accuracy**, macro-F1 **0.67622** on **960** artificial combinations. This grid is deliberately broader than the correlated synthetic recording distribution, and some combinations do not correspond to realistic sampled RTT windows. It is a limitation diagnostic, not a real-network benchmark or additional model-selection split. The compact tree can disagree with policy near thresholds and on unusual independent feature combinations; it is not guaranteed to implement the policy exactly.

These results measure **current-window policy approximation on deterministic simulation**. They do not demonstrate future outage prediction or real RF performance. No real data was available. See the machine-readable [evaluation](../ml/artifacts/evaluation.json) for full baselines, candidates and per-session metrics.

## Pending evidence

No physical ESP32 was connected, identified or flashed. Device inference/extraction latency, heap/stack, actual serial reliability, AP disconnect/reconnect latency and real classification metrics are **pending**. Timer instrumentation and a provenance-checked timing summary tool are implemented for later collection. [Hardware procedure](hardware-validation.md) gives exact remaining steps.

The repository and workflow are published at [Ishita-2210/TinyLink-AI-ESP32](https://github.com/Ishita-2210/TinyLink-AI-ESP32). See [Actions](https://github.com/Ishita-2210/TinyLink-AI-ESP32/actions) for actual hosted runs; the measurements above describe local Windows validation. The desktop frontend screenshot uses synthetic telemetry, and no hosted live device demo is claimed.
