#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_timer.h>
#include <esp_system.h>
#include <atomic>
#include "config.h"
#include "core.h"
#include "model_generated.h"

using namespace tinylink;
namespace {
Window window;
Connection connection;
WiFiUDP udp;
std::atomic<uint32_t> disconnect_events{0};
bool configured = false, socket_ready = false, pending = false, previous_link = false;
uint64_t next_sample = 0, probe_start_us = 0, sequence = 0, next_socket_try = 0;
uint32_t disconnects_previous = 0;
float slot_rssi = NAN;
char expected[48], output[2048];
uint32_t nonce = 0, probe_id = 0;
IPAddress endpoint;

uint64_t nowMs() { return static_cast<uint64_t>(esp_timer_get_time()) / 1000; }

void finish(float rtt) {
  uint64_t now = nowMs();
  uint32_t disconnects = disconnect_events.load(std::memory_order_relaxed);
  window.add({now, slot_rssi, rtt, disconnects - disconnects_previous});
  disconnects_previous = disconnects;
  uint64_t start = esp_timer_get_time();
  bool linked = WiFi.status() == WL_CONNECTED;
  Features features = window.extract(now, linked, connection.connected_since);
  uint32_t extraction_us = static_cast<uint32_t>(esp_timer_get_time() - start);
  if (!configured) { features.valid = false; features.diagnostic = "config_error"; }
  int prediction = -1;
  uint32_t inference_us = 0;
  if (features.valid) {
    start = esp_timer_get_time();
    prediction = modelPredict(features.x);
    inference_us = static_cast<uint32_t>(esp_timer_get_time() - start);
  }
  LinkState state = connection.state;
  if (linked && prediction > 0) state = LinkState::Degraded;
  Telemetry t;
  t.uptime_ms = now; t.sequence = sequence++; t.state = state;
  t.disconnects = disconnects; t.attempts = connection.attempts;
  t.reconnect_successes = connection.successes; t.reconnect_failures = connection.failures;
  t.features = features; t.prediction = prediction;
  t.inference_us = inference_us; t.extraction_us = extraction_us;
  if (serialize(t, kModelId, output, sizeof(output))) Serial.println(output);
  pending = false;
}
}  // namespace

void setup() {
  Serial.begin(115200);
  configured = validConfig(WIFI_SSID, WIFI_PASSWORD, ENDPOINT_IP, ENDPOINT_PORT);
  endpoint = IPAddress(ENDPOINT_IP);
  nonce = esp_random();
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);  // single owner for retries
  WiFi.onEvent([](WiFiEvent_t event) {
    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
      disconnect_events.fetch_add(1, std::memory_order_relaxed);
  });
}

void loop() {
  uint64_t now = nowMs();
  bool linked = WiFi.status() == WL_CONNECTED;
  if (connection.update(now, linked, configured)) {
    WiFi.disconnect(false, false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  if (linked != previous_link) {
    udp.stop(); socket_ready = false;
    next_socket_try = now;
    previous_link = linked;
  }
  if (linked && !socket_ready && now >= next_socket_try) {
    socket_ready = udp.begin(3334) == 1;
    next_socket_try = now + 1000;
  }
  if (pending) {
    // Bound packet processing even under unrelated LAN traffic.
    for (unsigned i = 0; i < 4; ++i) {
      int size = udp.parsePacket();
      if (size <= 0) break;
      char response[48]{};
      int n = udp.read(reinterpret_cast<uint8_t*>(response), sizeof(response) - 1);
      udp.clear();
      if (size == static_cast<int>(strlen(expected)) && n == size &&
          udp.remoteIP() == endpoint && udp.remotePort() == ENDPOINT_PORT &&
          memcmp(response, expected, n) == 0) {
        uint64_t elapsed = esp_timer_get_time() - probe_start_us;
        if (elapsed <= kTimeoutMs * 1000ULL) finish(static_cast<float>(elapsed) / 1000.0f);
        break;
      }
    }
    if (pending && (!linked || static_cast<uint64_t>(esp_timer_get_time()) - probe_start_us >= kTimeoutMs * 1000ULL)) finish(NAN);
  }
  if (!pending && now >= next_sample) {
    next_sample = now + kSampleMs;  // no catch-up flood after a scheduling stall
    slot_rssi = linked ? static_cast<float>(WiFi.RSSI()) : NAN;
    if (!linked || !socket_ready) finish(NAN);
    else {
      // Boot nonce + monotonic ID rejects delayed echoes from previous probes/boots.
      snprintf(expected, sizeof(expected), "TL1:%08lx:%08lx", static_cast<unsigned long>(nonce), static_cast<unsigned long>(++probe_id));
      probe_start_us = esp_timer_get_time();
      pending = true;
      bool sent = udp.beginPacket(endpoint, ENDPOINT_PORT) == 1;
      if (sent) sent = udp.write(reinterpret_cast<const uint8_t*>(expected), strlen(expected)) == strlen(expected);
      if (sent) sent = udp.endPacket() == 1;
      if (!sent) finish(NAN);
    }
  }
  delay(1);  // yield to the RTOS, never wait for association or probe completion
}
