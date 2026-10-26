#pragma once
#include "schema_generated.h"
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <algorithm>

namespace tinylink {
struct Features {
  float raw[kFeatureCount]{};
  float x[kFeatureCount]{};
  bool valid = false;
  const char* diagnostic = "warming_up";
  unsigned successes = 0, failures = 0;
};

inline bool validate(Features& f) {
  for (size_t i = 0; i < kFeatureCount; ++i) {
    float v = f.raw[i];
    if (std::isnan(v) && kNullable[i]) v = kMissing[i];
    else if (!std::isfinite(v) || v < kMin[i] || v > kMax[i]) return false;
    if (i == 4 && std::floor(v) != v) return false;
    f.x[i] = v;
  }
  return true;
}

struct Sample {
  uint64_t ms = 0;
  float rssi = NAN, rtt = NAN;
  uint32_t disconnects = 0;
};

class Window {
  Sample samples_[kWindow]{};
  size_t next_ = 0, count_ = 0;
  bool ever_success_ = false;
  uint64_t last_success_ = 0;
 public:
  void add(const Sample& s) {
    samples_[next_] = s;
    next_ = (next_ + 1) % kWindow;
    if (count_ < kWindow) ++count_;
    if (std::isfinite(s.rtt) && s.rtt >= 0 && s.rtt <= kTimeoutMs) {
      ever_success_ = true;
      last_success_ = s.ms;
    }
  }
  Features extract(uint64_t now, bool connected, uint64_t connected_since) const {
    Features f;
    if (count_ < kWindow) return f;
    double rssi = 0, mean = 0, m2 = 0;
    unsigned nrssi = 0, n = 0;
    uint64_t disconnects = 0, previous = 0;
    for (size_t j = 0; j < kWindow; ++j) {
      const Sample& s = samples_[(next_ + j) % kWindow];
      if (s.ms > now || now - s.ms > (kWindow - 1) * kSampleMs + kMaxSampleAgeMs ||
          (j && (s.ms <= previous || s.ms - previous > kMaxSampleAgeMs))) {
        f.diagnostic = "stale_window";
        return f;
      }
      previous = s.ms;
      if (!std::isnan(s.rssi)) {
        if (!std::isfinite(s.rssi) || s.rssi < -100 || s.rssi > 0) {
          f.diagnostic = "invalid_sample"; return f;
        }
        rssi += s.rssi; ++nrssi;
      }
      if (!std::isnan(s.rtt)) {
        if (!std::isfinite(s.rtt) || s.rtt < 0 || s.rtt > kTimeoutMs) {
          f.diagnostic = "invalid_sample"; return f;
        }
        ++n;
        double delta = s.rtt - mean;
        mean += delta / n;
        m2 += delta * (s.rtt - mean);
      }
      disconnects += s.disconnects;
    }
    if (now - previous > kMaxSampleAgeMs) { f.diagnostic = "stale_window"; return f; }
    f.raw[0] = nrssi ? static_cast<float>(rssi / nrssi) : NAN;
    f.raw[1] = n ? static_cast<float>(mean) : NAN;
    f.raw[2] = n ? static_cast<float>(std::sqrt(std::max(0.0, m2 / n))) : NAN;
    f.raw[3] = static_cast<float>(kWindow - n) / kWindow;
    f.raw[4] = static_cast<float>(std::min<uint64_t>(65535, disconnects));
    f.raw[5] = ever_success_ ? static_cast<float>(std::min<uint64_t>(60000, now - last_success_)) : NAN;
    f.raw[6] = connected && connected_since <= now ?
        std::min(86400.0f, static_cast<float>(now - connected_since) / 1000.0f) : 0;
    f.successes = n; f.failures = kWindow - n;
    f.valid = validate(f);
    f.diagnostic = f.valid ? "ok" : "invalid_features";
    return f;
  }
};

enum class LinkState { Disconnected, Recovering, Connected, Degraded };
inline const char* stateName(LinkState s) {
  switch(s) {
    case LinkState::Recovering: return "recovering";
    case LinkState::Connected: return "connected";
    case LinkState::Degraded: return "degraded";
    default: return "disconnected";
  }
}

// Six bounded association attempts per burst, then a minute cooldown; repeat forever.
class Connection {
  bool linked_ = false, attempting_ = false;
  unsigned burst_ = 0;
  uint64_t started_ = 0, next_ = 0;
 public:
  LinkState state = LinkState::Disconnected;
  uint64_t connected_since = 0;
  uint32_t attempts = 0, successes = 0, failures = 0;
  bool update(uint64_t now, bool link, bool configured = true) {
    if (link) {
      if (!linked_) { connected_since = now; ++successes; }
      linked_ = true; attempting_ = false; burst_ = 0;
      state = LinkState::Connected;
      return false;
    }
    if (linked_) { linked_ = false; next_ = now; burst_ = 0; }
    state = attempting_ ? LinkState::Recovering : LinkState::Disconnected;
    if (!configured) { attempting_ = false; state = LinkState::Disconnected; return false; }
    if (attempting_) {
      if (now - started_ < 10000) return false;
      attempting_ = false; ++failures;
      if (burst_ >= 6) { next_ = now + 60000; burst_ = 0; }
      else next_ = now + (1000ULL << (burst_ - 1));
      state = LinkState::Disconnected;
      return false;
    }
    if (now < next_) return false;
    started_ = now; attempting_ = true; ++burst_; ++attempts;
    state = LinkState::Recovering;
    return true;
  }
};

inline bool validConfig(const char* ssid, const char* password, const uint8_t ip[4], unsigned port) {
  if (!ssid || !password || !ip || port == 0 || port > 65535) return false;
  size_t ns = 0, np = 0;
  while (ssid[ns] && ns <= 32) ++ns;
  while (password[np] && np <= 63) ++np;
  // Empty password permits an open network. Never print configuration values.
  return ns > 0 && ns <= 32 && (np == 0 || (np >= 8 && np <= 63)) &&
         ip[0] > 0 && ip[0] < 224 && ip[0] != 127 && ip[3] != 255;
}

class JsonWriter {
  char* out_; size_t capacity_, used_ = 0; bool ok_ = true;
 public:
  JsonWriter(char* out, size_t n) : out_(out), capacity_(n) { if (n) out[0] = 0; }
  void append(const char* format, ...) {
    if (!ok_ || used_ >= capacity_) { ok_ = false; return; }
    va_list args; va_start(args, format);
    int n = vsnprintf(out_ + used_, capacity_ - used_, format, args);
    va_end(args);
    if (n < 0 || static_cast<size_t>(n) >= capacity_ - used_) { ok_ = false; return; }
    used_ += static_cast<size_t>(n);
  }
  bool ok() const { return ok_; }
};

struct Telemetry {
  uint64_t uptime_ms = 0, sequence = 0;
  LinkState state = LinkState::Disconnected;
  uint32_t disconnects = 0, attempts = 0, reconnect_successes = 0, reconnect_failures = 0;
  uint32_t inference_us = 0, extraction_us = 0;
  int prediction = -1;
  Features features;
};

inline bool serialize(const Telemetry& t, const char* model_id, char* out, size_t n, bool host_simulation = false) {
  JsonWriter w(out, n);
  // All string arguments are internal constants or generated hex IDs, never user input.
  w.append("{\"protocol_version\":%u,\"schema_version\":%u,\"firmware_version\":\"1.0.0\","
           "\"source\":\"%s\",\"model_id\":\"%s\",\"uptime_ms\":%llu,\"sequence\":%llu,"
           "\"state\":\"%s\",\"features_valid\":%s,\"diagnostic\":\"%s\",\"features\":{",
           kProtocolVersion, kSchemaVersion, host_simulation ? "host_cpp" : "esp32", model_id,
           static_cast<unsigned long long>(t.uptime_ms), static_cast<unsigned long long>(t.sequence),
           stateName(t.state), t.features.valid ? "true" : "false", t.features.diagnostic);
  for (size_t i = 0; i < kFeatureCount; ++i) {
    w.append("%s\"%s\":", i ? "," : "", kFeatureNames[i]);
    if (!t.features.valid || !std::isfinite(t.features.raw[i])) w.append("null");
    else w.append("%.9g", static_cast<double>(t.features.raw[i]));
  }
  w.append("},\"prediction\":");
  if (t.features.valid && t.prediction >= 0 && t.prediction < 3) w.append("\"%s\"", kLabels[t.prediction]);
  else w.append("null");
  w.append(",\"inference_us\":%u,\"extraction_us\":%u,\"probe_successes\":%u,\"probe_failures\":%u,"
           "\"disconnects_total\":%u,\"reconnect_attempts\":%u,\"reconnect_successes\":%u,"
           "\"reconnect_failures\":%u}", t.inference_us, t.extraction_us, t.features.successes,
           t.features.failures, t.disconnects, t.attempts, t.reconnect_successes, t.reconnect_failures);
  return w.ok();
}
}  // namespace tinylink
