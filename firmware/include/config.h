#pragma once
#include <cstdint>
#if __has_include("secrets.h")
#include "secrets.h"
#else
// Reproducible credential-free build emits config_error until configured.
constexpr const char* WIFI_SSID = "";
constexpr const char* WIFI_PASSWORD = "";
constexpr uint8_t ENDPOINT_IP[4] = {0, 0, 0, 0};
constexpr unsigned ENDPOINT_PORT = 3333;
#endif
