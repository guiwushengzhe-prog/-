// Piano Light Studio, USB serial receiver. Configure these for your actual board/strip.
// Requires FastLED and ArduinoJson 7. Board is deliberately not hard-coded.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <FastLED.h>

#ifndef LED_DATA_PIN
#define LED_DATA_PIN 4
#endif
#ifndef LED_COUNT
#define LED_COUNT 144
#endif
static_assert(LED_COUNT > 0 && LED_COUNT <= 512, "LED_COUNT must be 1..512");
CRGB pixels[LED_COUNT];
String pending;
bool dropping = false;
uint32_t lastFrame = 0;
bool lit = false;

void clearLights() {
  fill_solid(pixels, LED_COUNT, CRGB::Black);
  FastLED.show();
  lit = false;
}

void applyLine(const String &line) {
  JsonDocument doc;
  if (deserializeJson(doc, line)) return;
  const char *type = doc["type"] | "";
  if (strcmp(type, "clear") == 0) {
    clearLights();
    lastFrame = millis();
    return;
  }
  if (strcmp(type, "frame") != 0 || !doc["pixels"].is<JsonArray>()) return;
  float brightness = doc["brightness"] | 0.15f;
  if (!isfinite(brightness) || brightness < 0 || brightness > 1) return;
  JsonArray values = doc["pixels"].as<JsonArray>();
  if (values.size() > LED_COUNT) return;
  // Validate complete frame before applying, so malformed input cannot leave a partial frame.
  for (JsonVariant value : values) {
    if (!value.is<JsonArray>() || value.size() != 4) return;
    for (int j = 0; j < 4; ++j) if (!value[j].is<int>()) return;
    int index = value[0];
    if (index < 0 || index >= LED_COUNT) return;
    for (int j = 1; j < 4; ++j) {
      int component = value[j];
      if (component < 0 || component > 255) return;
    }
  }
  fill_solid(pixels, LED_COUNT, CRGB::Black);
  for (JsonArray value : values) {
    int index = value[0];
    pixels[index] = CRGB(value[1].as<int>(), value[2].as<int>(), value[3].as<int>());
  }
  FastLED.setBrightness((uint8_t)(min(brightness, 0.35f) * 255));
  FastLED.show();
  lastFrame = millis();
  lit = !values.isNull() && values.size() > 0;
}

void setup() {
  Serial.begin(115200);
  pending.reserve(4096);
  FastLED.addLeds<WS2812B, LED_DATA_PIN, GRB>(pixels, LED_COUNT);
  FastLED.setBrightness(38);
  clearLights();
}

void loop() {
  // Work budget allows the disconnect watchdog to run even under a continuous input stream.
  for (int budget = 0; budget < 512 && Serial.available(); ++budget) {
    const char c = Serial.read();
    if (c == '\n') {
      if (!dropping) applyLine(pending);
      pending = "";
      dropping = false;
    } else if (c != '\r' && !dropping) {
      if (pending.length() < 16384) pending += c;
      else {
        pending = "";
        dropping = true;
      }
    }
  }
  if (lit && (uint32_t)(millis() - lastFrame) > 2000) clearLights();
  delay(1);
}
