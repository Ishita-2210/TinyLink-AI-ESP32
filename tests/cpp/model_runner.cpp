#include "core.h"
#include "model_generated.h"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  bool telemetry = argc == 2 && std::strcmp(argv[1], "--telemetry") == 0;
  uint64_t sequence = 0;
  while (true) {
    tinylink::Features f;
    for (size_t i = 0; i < tinylink::kFeatureCount; ++i) {
      std::string token;
      if (!(std::cin >> token)) return i == 0 ? 0 : 2;
      char* end = nullptr;
      f.raw[i] = std::strtof(token.c_str(), &end);
      if (!end || *end || end == token.c_str()) return 2;
    }
    f.valid = tinylink::validate(f);
    f.diagnostic = f.valid ? "ok" : "invalid_features";
    int prediction = f.valid ? tinylink::modelPredict(f.x) : -1;
    if (!telemetry) std::cout << prediction << '\n';
    else {
      tinylink::Telemetry t;
      t.features = f; t.prediction = prediction; t.sequence = sequence++;
      t.uptime_ms = 10000 + t.sequence * 1000;
      if (f.valid) {
        t.features.failures = static_cast<unsigned>(std::round(f.x[3] * 10));
        t.features.successes = 10 - t.features.failures;
      }
      char output[2048];
      if (!tinylink::serialize(t, tinylink::kModelId, output, sizeof(output), true)) return 3;
      std::cout << output << '\n';
    }
  }
}
