#include "core.h"
#include "model_generated.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <limits>
#ifdef NDEBUG
#error "Portable firmware tests require active assertions"
#endif

using namespace tinylink;
int main() {
  // Warmup, Welford mean/std, ring wrap and stale/gap rejection.
  Window w;
  assert(!w.extract(0, false, 0).valid);
  for (unsigned i = 0; i < 10; ++i) w.add({i*1000ULL, -50.0f, static_cast<float>(i), i == 3 ? 1U : 0U});
  Features f = w.extract(9000, true, 0);
  assert(f.valid && f.successes == 10 && f.failures == 0);
  assert(f.raw[0] == -50 && f.raw[1] == 4.5f);
  assert(std::fabs(f.raw[2] - std::sqrt(8.25f)) < 1e-5);
  assert(f.raw[4] == 1 && f.raw[5] == 0 && f.raw[6] == 9);
  assert(!w.extract(11000, true, 0).valid);
  w.add({10000, -60, NAN, 0});
  f = w.extract(10000, true, 0);
  assert(f.valid && f.failures == 1 && std::fabs(f.raw[3] - 0.1f) < 1e-6 && f.raw[5] == 1000);
  w.add({20000, -50, 1, 0});
  assert(!w.extract(20000, true, 0).valid);
  Window outage;
  for (unsigned i=0; i<10; ++i) outage.add({i*1000ULL, NAN, NAN, 0});
  f = outage.extract(9000, false, 0);
  assert(f.valid && f.x[0] == -127 && f.x[1] == 1000 && f.x[2] == 500 && f.x[5] == 60000);
  assert(f.raw[3] == 1 && f.raw[6] == 0 && modelPredict(f.x) == 2);
  Window invalid;
  for (unsigned i=0; i<10; ++i) invalid.add({i*1000ULL, i == 5 ? -101.0f : -50.0f, 10, 0});
  assert(!invalid.extract(9000, true, 0).valid);
  Window invalid_rtt;
  for (unsigned i=0; i<10; ++i) invalid_rtt.add({i*1000ULL, -50, i == 5 ? 501.0f : 10.0f, 0});
  assert(!invalid_rtt.extract(9000, true, 0).valid);
  f.raw[3] = NAN; assert(!validate(f));
  f.raw[3] = 0; f.raw[0] = -100; assert(validate(f));
  f.raw[0] = -101; assert(!validate(f));
  f.raw[0] = std::numeric_limits<float>::infinity(); assert(!validate(f));
  f.raw[0] = -50; f.raw[4] = 0.5f; assert(!validate(f));
  assert(std::strcmp(kLabels[0], "Stable") == 0 && std::strcmp(kLabels[1], "Degrading") == 0 && std::strcmp(kLabels[2], "Unstable") == 0);
  // Initial retry, timeout, backoff, connection, disconnection and recovery.
  Connection c;
  assert(!c.update(0, false, false));
  assert(c.update(0, false) && c.state == LinkState::Recovering);
  assert(!c.update(9999, false));
  assert(!c.update(10000, false) && c.failures == 1);
  assert(!c.update(10999, false));
  assert(c.update(11000, false));
  assert(!c.update(12000, true) && c.successes == 1 && c.connected_since == 12000);
  assert(c.update(13000, false));
  assert(!c.update(14000, true) && c.successes == 2 && c.connected_since == 14000);
  Connection burst;
  uint64_t time = 0;
  for (unsigned i = 0; i < 6; ++i) {
    assert(burst.update(time, false));
    assert(!burst.update(time + 10000, false));
    time += 10000 + (i < 5 ? (1000ULL << i) : 60000);
  }
  assert(!burst.update(time - 1, false));
  assert(burst.update(time, false) && burst.attempts == 7);
  // Configuration validation and bounded telemetry serialization.
  const uint8_t ip[4] = {192,168,1,2}, zero[4] = {0,0,0,0};
  assert(validConfig("network", "12345678", ip, 3333));
  assert(validConfig("network", "", ip, 3333));
  assert(!validConfig("", "12345678", ip, 3333));
  assert(!validConfig("network", "short", ip, 3333));
  assert(!validConfig("network", "12345678", zero, 3333));
  assert(!validConfig("network", "12345678", ip, 0));
  assert(!validConfig("network", "12345678", ip, 65536));
  assert(!validConfig("123456789012345678901234567890123", "", ip, 3333));
  Telemetry t; t.features = outage.extract(9000, false, 0); t.prediction = modelPredict(t.features.x);
  char output[2048], tiny[8];
  assert(serialize(t, kModelId, output, sizeof(output)));
  assert(std::strstr(output, "\"rssi_mean_dbm\":null"));
  assert(std::strstr(output, "\"prediction\":\"Unstable\""));
  assert(!serialize(t, kModelId, tiny, sizeof(tiny)));
  t.features.valid = false;
  assert(serialize(t, kModelId, output, sizeof(output)) && std::strstr(output, "\"prediction\":null"));
  std::cout << "Portable C++ feature, connection, configuration, inference and serialization assertions passed\n";
}
