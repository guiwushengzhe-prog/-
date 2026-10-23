// Piano Light Studio: protocol 2, with legacy frame/clear compatibility.
// Requires FastLED and ArduinoJson 7. Compile LED_COUNT for the actual strip.
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
constexpr const char *FIRMWARE_VERSION = "2.0.0";
constexpr size_t MAX_LINE = LED_COUNT * 24 + 512;
CRGB pixels[LED_COUNT];
char pending[MAX_LINE];
size_t pendingLength = 0;
bool dropping = false;
uint32_t lastContact = 0, lastByte = 0, lastSequence = 0;
bool lit = false;

void sendReply(JsonDocument &doc) {
  char output[320];
  const size_t size = serializeJson(doc, output, sizeof(output));
  Serial.write(reinterpret_cast<const uint8_t *>(output), size);
  Serial.write('\n');
}

void identify(const char *type, uint32_t sequence) {
  JsonDocument reply;
  reply["type"] = type;
  reply["seq"] = sequence;
  reply["protocol"] = 2;
  reply["firmware"] = FIRMWARE_VERSION;
  reply["led_count"] = LED_COUNT;
  reply["data_pin"] = LED_DATA_PIN;
  reply["color_order"] = "GRB";
  sendReply(reply);
}

void errorReply(uint32_t sequence, const char *code) {
  if (!sequence) return;
  JsonDocument reply;
  reply["type"] = "error";
  reply["seq"] = sequence;
  reply["code"] = code;
  sendReply(reply);
}

void acknowledge(uint32_t sequence, const char *command) {
  if (!sequence) return;
  JsonDocument reply;
  reply["type"] = "ack";
  reply["seq"] = sequence;
  reply["command"] = command;
  reply["lit"] = lit;
  sendReply(reply);
}

void clearLights() {
  if (lit) {
    fill_solid(pixels, LED_COUNT, CRGB::Black);
    FastLED.show();
  }
  lit = false;
}

void applyLine(char *line, size_t length) {
  JsonDocument doc;
  if (deserializeJson(doc, line, length)) return;
  const uint32_t sequence = doc["seq"] | 0U;
  const char *type = doc["type"] | "";
  if (strcmp(type, "hello") == 0) {
    clearLights();
    lastSequence = sequence;
    lastContact = millis();
    identify("hello", sequence);
    return;
  }
  if (sequence && sequence <= lastSequence) {
    errorReply(sequence, "sequence");
    return;
  }
  if (strcmp(type, "clear") == 0 || strcmp(type, "ping") == 0) {
    if (strcmp(type, "clear") == 0) clearLights();
    lastContact = millis();
    if (sequence) lastSequence = sequence;
    acknowledge(sequence, type);
    return;
  }
  if (strcmp(type, "frame") != 0) {
    errorReply(sequence, "command");
    return;
  }
  float brightness = doc["brightness"] | 0.15f;
  if (!isfinite(brightness) || brightness < 0 || brightness > 1) {
    errorReply(sequence, "brightness");
    return;
  }
  if (!doc["pixels"].is<JsonArray>()) {
    errorReply(sequence, "pixels");
    return;
  }
  JsonArray values = doc["pixels"].as<JsonArray>();
  if (values.size() > LED_COUNT) {
    errorReply(sequence, "pixels");
    return;
  }
  // Validate the complete frame before changing any LED.
  for (JsonVariant value : values) {
    if (!value.is<JsonArray>() || value.size() != 4) {
      errorReply(sequence, "pixels");
      return;
    }
    for (int j = 0; j < 4; ++j) {
      if (!value[j].is<int>()) {
        errorReply(sequence, "pixels");
        return;
      }
      const int component = value[j];
      if (component < 0 || component > (j == 0 ? LED_COUNT - 1 : 255)) {
        errorReply(sequence, "pixels");
        return;
      }
    }
  }
  fill_solid(pixels, LED_COUNT, CRGB::Black);
  lit = false;
  for (JsonArray value : values) {
    const int index = value[0];
    pixels[index] = CRGB(value[1].as<int>(), value[2].as<int>(), value[3].as<int>());
    if (pixels[index] != CRGB::Black) lit = true;
  }
  FastLED.setBrightness(static_cast<uint8_t>(brightness * 255));
  FastLED.show();
  lastContact = millis();
  if (sequence) lastSequence = sequence;
  acknowledge(sequence, "frame");
}

void setup() {
  Serial.begin(115200);
  FastLED.addLeds<WS2812B, LED_DATA_PIN, GRB>(pixels, LED_COUNT);
  FastLED.setBrightness(38);
  fill_solid(pixels, LED_COUNT, CRGB::Black);
  FastLED.show();
  identify("ready", 0);
}

void loop() {
  // Bounded work keeps the watchdog active, even under continuous input.
  for (int budget = 0; budget < 1024 && Serial.available(); ++budget) {
    const char c = Serial.read();
    lastByte = millis();
    if (c == '\n') {
      if (!dropping && pendingLength) applyLine(pending, pendingLength);
      pendingLength = 0;
      dropping = false;
    } else if (c != '\r' && !dropping) {
      if (pendingLength < sizeof(pending)) pending[pendingLength++] = c;
      else { pendingLength = 0; dropping = true; }
    }
  }
  if ((pendingLength || dropping) && static_cast<uint32_t>(millis() - lastByte) > 500) {
    pendingLength = 0;
    dropping = false;
  }
  if (lit && static_cast<uint32_t>(millis() - lastContact) > 2000) clearLights();
  delay(1);
}
