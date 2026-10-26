# Telemetry and feature contract

`schema/features.json` is the only feature definition. `host.schema` loads it directly. `scripts/generate_schema.py` produces firmware constants and its SHA-256 digest. The trained JSON artifact embeds that digest, feature names and labels; Python refuses mismatches. A C++ compile-time assertion refuses a model exported against different schema contents. Bump the schema version for breaking semantic changes, regenerate and retrain together.

One UTF-8 JSON object per newline at 115200 baud. Maximum host frame is 4096 bytes; firmware uses a fixed 2048-byte output buffer. Boot ROM diagnostics may precede JSON. Non-JSON lines, wrong versions, missing fields, non-finite/out-of-range values and inconsistent probe counts are rejected and counted. Framing tolerates fragmented reads, bounds storage and discards an oversized line through its newline before resuming. No SSID, password, MAC address or endpoint address is serialized.

Required top-level fields:

| Fields | Meaning |
| --- | --- |
| `protocol_version`, `schema_version` | Both 1 for this implementation |
| `firmware_version`, `model_id` | Firmware release and 16-hex-digit model fingerprint |
| `source` | `esp32`, `host_cpp`, or `synthetic`; preserved on recording/export |
| `uptime_ms`, `sequence` | 64-bit monotonic device uptime, one sequence number per serial record |
| `state` | `connected`, `degraded`, `disconnected`, `recovering` |
| `features_valid`, `diagnostic` | Readiness and one of `ok`, `warming_up`, `stale_window`, `invalid_sample`, `invalid_features`, `config_error` |
| `features` | All seven named features below; JSON null for missing measurements |
| `prediction` | `Stable`, `Degrading`, `Unstable`; null for invalid/incomplete windows |
| `inference_us`, `extraction_us` | Actual ESP timer duration on hardware; simulation uses zero and explicit provenance |
| `probe_successes`, `probe_failures` | Ten-slot counts once valid; disconnected slots count as endpoint failures |
| `disconnects_total` | Driver station-disconnect event count since boot, including association failures |
| `reconnect_attempts`, `reconnect_successes`, `reconnect_failures` | Totals including initial association; success means IP connectivity, failure means 10-second association deadline expired |

The recorder adds `host_timestamp` (UTC ISO 8601), a random `session_id`, and `ingest_mode=live_serial` or `recorded_replay`. A live board reset starts another session. Replay retains original source/session metadata. `prediction_origin` marks synthetic Python reference or C++ simulation output. It is never relabeled as physical firmware inference.

| Ordered feature | Unit | Accepted measured range | Missing preprocessing |
| --- | --- | --- | --- |
| `rssi_mean_dbm` | dBm | -100 through 0 | null -> -127 |
| `rtt_mean_ms` | ms | 0 through 500 | null -> 1000 |
| `rtt_std_ms` | ms | 0 through 500 | null -> 500 |
| `probe_failure_rate` | fraction | 0 through 1 | missing invalid |
| `disconnect_count` | integer events/window | 0 through 65535, saturated | missing invalid |
| `success_age_ms` | ms | 0 through 60000, capped | null -> 60000 |
| `connection_uptime_s` | seconds | 0 through 86400, capped | missing invalid |

Every slot is scheduled at 1000 ms with no catch-up flood after a stall. The ten-slot buffer includes failures and disconnected slots. RSSI aggregates connected samples; RTT mean and population standard deviation aggregate only successful echoes, using Welford accumulation. One successful RTT has zero standard deviation. No RTT successes produce null mean/std. Success age is null before the first echo, then continues through outages. Connection uptime resets whenever IP connectivity is lost. All-null windows during warmup/invalid state carry no prediction.

The newest completed slot must be no older than 1750 ms, no adjacent samples may be farther apart than 1750 ms, and the oldest slot must lie within 10750 ms. The 750 ms margin accommodates a 500 ms probe timeout plus scheduler jitter. Gaps invalidate inference until ten consecutive timely slots replace them. Uptime uses `esp_timer_get_time`, avoiding 32-bit `millis()` rollover.

Measurements and missing substitution use IEEE float32 before inference in both languages. sklearn itself casts inputs to float32. Exported comparisons promote that float32 to float64 and compare against the exact trained float64 threshold. Telemetry uses nine significant digits to round-trip float32; no threshold rounding is introduced. The native equivalence test covers complete synthetic data, independent combinations, random vectors, nullable fields, and the neighboring float32 values at every model split.

UDP probe bytes are `TL1:bbbbbbbb:pppppppp` (boot nonce, monotonically incrementing probe ID, lowercase hexadecimal). ESP32 binds local port 3334 and sends to a configured LAN IPv4/port (default 3333), with one outstanding probe and a 500 ms deadline. A successful echo must match payload, source IPv4 and source port before the deadline. Late/foreign/duplicate datagrams do not count as successes. The receiver processes at most four datagrams per loop. This prevents accidental stale responses; it is not authenticated network security. Use a trusted LAN.
