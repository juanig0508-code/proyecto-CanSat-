#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include <esp_idf_version.h>

// ============================================================
// Offline ground station.
//
// No WiFi access point and no internet connection are used.
// The WiFi radio is only switched on, in station mode, to fix
// its channel for ESP-NOW (same trick the ESP32-CAM already
// uses) -- it never associates to a network. Telemetry is
// printed over USB serial for a local PC app to read.
// ============================================================

// ============================================================
// ESP-NOW
//
// Must match the ESP32-CAM channel.
// ============================================================

#define ESPNOW_CHANNEL 1


// ============================================================
// Unified Hermes telemetry protocol
//
// MUST match the onboard ESP32 and ESP32-CAM exactly.
// ============================================================

struct __attribute__((packed)) TelemetryPacket {
  // Mission
  uint32_t counter;
  uint32_t time_ms;

  // GPS
  float lat;
  float lon;
  float alt;
  float speed;          // km/h
  uint8_t sat;

  // BME680
  float temp;           // deg C
  float humidity;       // %
  float pressure;       // hPa
  float gas_kohm;       // kOhm

  // MPU6050 acceleration
  int16_t accel_x_cms2;       // cm/s^2
  int16_t accel_y_cms2;       // cm/s^2
  int16_t accel_z_cms2;       // cm/s^2
  int16_t accel_total_cms2;   // cm/s^2

  // MPU6050 attitude (complementary filter)
  int16_t roll_deg_x100;      // deg x100
  int16_t pitch_deg_x100;     // deg x100

  // Mission state
  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 54,
  "TelemetryPacket must be exactly 54 bytes"
);


// ============================================================
// ESP-NOW RX queue
//
// The ESP-NOW callback only copies data into the queue.
// HTTPS POST is done later from loop(), never from the callback.
// ============================================================

constexpr size_t MAX_PACKET_SIZE =
  sizeof(TelemetryPacket);

constexpr uint8_t RX_QUEUE_LENGTH = 32;

struct ReceivedFrame {
  uint8_t sourceMac[6];
  int8_t rssi;
  uint8_t length;
  uint8_t data[MAX_PACKET_SIZE];
};

QueueHandle_t rxQueue = nullptr;


// ============================================================
// Statistics
// ============================================================

volatile uint32_t queueDrops = 0;

uint32_t telemetryReceived = 0;
uint32_t invalidReceived = 0;

uint32_t serialSent = 0;

uint32_t missingPackets = 0;
uint32_t duplicatePackets = 0;
uint32_t outOfOrderPackets = 0;

uint32_t lastCounter = 0;
bool hasLastCounter = false;


// ============================================================
// Function declarations
// ============================================================

void initRadioChannel();
bool initEspNow();

void processReceivedFrame(
  const ReceivedFrame &frame
);

void sendTelemetryToSerial(
  const TelemetryPacket &packet,
  int8_t espNowRssi
);

const char* missionModeName(
  uint8_t mode
);

void printMac(
  const uint8_t *mac
);

void updatePacketLossStats(
  uint32_t counter
);


// ============================================================
// Helpers
// ============================================================

void printMac(
  const uint8_t *mac
) {
  if (mac == nullptr) {
    Serial.print("--:--:--:--:--:--");
    return;
  }

  for (int i = 0; i < 6; i++) {
    if (i > 0) {
      Serial.print(":");
    }

    if (mac[i] < 0x10) {
      Serial.print("0");
    }

    Serial.print(
      mac[i],
      HEX
    );
  }
}


const char* missionModeName(
  uint8_t mode
) {
  switch (mode) {
    case 0:
      return "PRELAUNCH";

    case 1:
      return "DESCENT";

    case 2:
      return "POST_IMPACT";

    default:
      return "UNKNOWN";
  }
}


// ============================================================
// Packet loss / counter statistics
// ============================================================

void updatePacketLossStats(
  uint32_t counter
) {
  if (!hasLastCounter) {
    lastCounter = counter;
    hasLastCounter = true;
    return;
  }

  if (counter == lastCounter) {
    duplicatePackets++;
    return;
  }

  if (counter > lastCounter) {
    uint32_t difference =
      counter - lastCounter;

    if (difference > 1) {
      missingPackets +=
        difference - 1;
    }

    lastCounter = counter;
    return;
  }

  // Counter went backwards.
  // This can happen after a transmitter reboot or due to
  // an out-of-order packet.
  outOfOrderPackets++;
  lastCounter = counter;
}


// ============================================================
// ESP-NOW callback compatibility
// ============================================================

#if ESP_IDF_VERSION_MAJOR > 5 || \
    (ESP_IDF_VERSION_MAJOR == 5 && ESP_IDF_VERSION_MINOR >= 1)

void onDataReceived(
  const esp_now_recv_info_t *info,
  const uint8_t *data,
  int len
) {
  if (
    data == nullptr ||
    len != (int)sizeof(TelemetryPacket)
  ) {
    invalidReceived++;
    return;
  }

  ReceivedFrame frame = {};

  frame.length =
    (uint8_t)len;

  memcpy(
    frame.data,
    data,
    len
  );

  if (info != nullptr) {
    if (info->src_addr != nullptr) {
      memcpy(
        frame.sourceMac,
        info->src_addr,
        6
      );
    }

    if (info->rx_ctrl != nullptr) {
      frame.rssi =
        info->rx_ctrl->rssi;
    }
  }

  if (
    xQueueSend(
      rxQueue,
      &frame,
      0
    ) != pdTRUE
  ) {
    queueDrops++;
  }
}

#else

void onDataReceived(
  const uint8_t *mac,
  const uint8_t *data,
  int len
) {
  if (
    data == nullptr ||
    len != (int)sizeof(TelemetryPacket)
  ) {
    invalidReceived++;
    return;
  }

  ReceivedFrame frame = {};

  frame.length =
    (uint8_t)len;

  frame.rssi = 0;

  memcpy(
    frame.data,
    data,
    len
  );

  if (mac != nullptr) {
    memcpy(
      frame.sourceMac,
      mac,
      6
    );
  }

  if (
    xQueueSend(
      rxQueue,
      &frame,
      0
    ) != pdTRUE
  ) {
    queueDrops++;
  }
}

#endif


// ============================================================
// Setup
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println(
    "=========================================="
  );
  Serial.println(
    "Hermes ground station"
  );
  Serial.println(
    "ESP-NOW unified telemetry -> USB serial (offline, no WiFi)"
  );
  Serial.println(
    "=========================================="
  );

  rxQueue =
    xQueueCreate(
      RX_QUEUE_LENGTH,
      sizeof(ReceivedFrame)
    );

  if (rxQueue == nullptr) {
    Serial.println(
      "ERROR: could not create ESP-NOW RX queue"
    );

    while (true) {
      delay(1000);
    }
  }

  initRadioChannel();

  if (!initEspNow()) {
    Serial.println(
      "ERROR: ESP-NOW initialization failed"
    );

    while (true) {
      delay(1000);
    }
  }

  Serial.print("Ground MAC: ");
  Serial.println(
    WiFi.macAddress()
  );

  Serial.print(
    "Telemetry packet size: "
  );
  Serial.print(
    sizeof(TelemetryPacket)
  );
  Serial.println(" bytes");

  Serial.println(
    "Waiting for telemetry..."
  );
}


// ============================================================
// Main loop
// ============================================================

void loop() {
  ReceivedFrame frame;

  while (
    xQueueReceive(
      rxQueue,
      &frame,
      0
    ) == pdTRUE
  ) {
    processReceivedFrame(
      frame
    );
  }

  static uint32_t lastStatsMs = 0;

  if (
    millis() - lastStatsMs >= 5000
  ) {
    lastStatsMs = millis();

    Serial.println();
    Serial.println(
      "---------------- GROUND STATS ----------------"
    );

    Serial.print(
      "Telemetry received:  "
    );
    Serial.println(
      telemetryReceived
    );

    Serial.print(
      "Invalid frames:      "
    );
    Serial.println(
      invalidReceived
    );

    Serial.print(
      "RX queue drops:      "
    );
    Serial.println(
      queueDrops
    );

    Serial.print(
      "Missing packets:     "
    );
    Serial.println(
      missingPackets
    );

    Serial.print(
      "Duplicate packets:   "
    );
    Serial.println(
      duplicatePackets
    );

    Serial.print(
      "Out-of-order:        "
    );
    Serial.println(
      outOfOrderPackets
    );

    Serial.print(
      "Serial TLM sent:     "
    );
    Serial.println(
      serialSent
    );

    Serial.print(
      "ESP-NOW channel:     "
    );
    Serial.println(
      WiFi.channel()
    );

    Serial.println(
      "----------------------------------------------"
    );
  }

  delay(1);
}


// ============================================================
// Radio channel
//
// No access point involved: the WiFi radio is switched to
// station mode only so its channel can be pinned directly,
// exactly like the ESP32-CAM does on its side.
// ============================================================

void initRadioChannel() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  esp_err_t result =
    esp_wifi_set_channel(
      ESPNOW_CHANNEL,
      WIFI_SECOND_CHAN_NONE
    );

  if (result != ESP_OK) {
    Serial.print(
      "Failed to set ESP-NOW channel: "
    );
    Serial.println(result);
  }

  Serial.print(
    "ESP-NOW channel set to "
  );
  Serial.println(
    WiFi.channel()
  );
}


// ============================================================
// ESP-NOW initialization
// ============================================================

bool initEspNow() {
  if (
    esp_now_init() != ESP_OK
  ) {
    Serial.println(
      "ERROR initializing ESP-NOW"
    );
    return false;
  }

  if (
    esp_now_register_recv_cb(
      onDataReceived
    ) != ESP_OK
  ) {
    Serial.println(
      "ERROR registering ESP-NOW receive callback"
    );
    return false;
  }

  Serial.println(
    "ESP-NOW RX initialized"
  );

  return true;
}


// ============================================================
// Process unified telemetry packet
// ============================================================

void processReceivedFrame(
  const ReceivedFrame &frame
) {
  if (
    frame.length !=
    sizeof(TelemetryPacket)
  ) {
    invalidReceived++;

    Serial.print(
      "Telemetry wrong size: "
    );
    Serial.print(
      frame.length
    );

    Serial.print(
      " expected "
    );
    Serial.println(
      sizeof(TelemetryPacket)
    );

    return;
  }

  TelemetryPacket packet;

  memcpy(
    &packet,
    frame.data,
    sizeof(packet)
  );

  // Simple protocol sanity check.
  if (packet.mode > 2) {
    invalidReceived++;

    Serial.print(
      "Invalid mission mode: "
    );
    Serial.println(
      packet.mode
    );

    return;
  }

  telemetryReceived++;

  updatePacketLossStats(
    packet.counter
  );

  Serial.println();
  Serial.println(
    "===== TELEMETRY RX ====="
  );

  Serial.print(
    "Source MAC: "
  );
  printMac(
    frame.sourceMac
  );
  Serial.println();

  Serial.print(
    "RSSI: "
  );
  Serial.print(
    frame.rssi
  );
  Serial.println(" dBm");

  Serial.print(
    "Counter: "
  );
  Serial.println(
    packet.counter
  );

  Serial.print(
    "Mission time ms: "
  );
  Serial.println(
    packet.time_ms
  );

  Serial.print(
    "GPS: "
  );
  Serial.print(
    packet.lat,
    6
  );
  Serial.print(", ");
  Serial.println(
    packet.lon,
    6
  );

  Serial.print(
    "Altitude m: "
  );
  Serial.println(
    packet.alt,
    2
  );

  Serial.print(
    "Speed km/h: "
  );
  Serial.println(
    packet.speed,
    2
  );

  Serial.print(
    "Satellites: "
  );
  Serial.println(
    packet.sat
  );

  Serial.print(
    "Temperature C: "
  );
  Serial.println(
    packet.temp,
    2
  );

  Serial.print(
    "Humidity %: "
  );
  Serial.println(
    packet.humidity,
    2
  );

  Serial.print(
    "Pressure hPa: "
  );
  Serial.println(
    packet.pressure,
    2
  );

  Serial.print(
    "Gas kOhm: "
  );
  Serial.println(
    packet.gas_kohm,
    2
  );

  Serial.print(
    "Accel X m/s2: "
  );
  Serial.println(
    packet.accel_x_cms2 /
    100.0f,
    2
  );

  Serial.print(
    "Accel Y m/s2: "
  );
  Serial.println(
    packet.accel_y_cms2 /
    100.0f,
    2
  );

  Serial.print(
    "Accel Z m/s2: "
  );
  Serial.println(
    packet.accel_z_cms2 /
    100.0f,
    2
  );

  Serial.print(
    "Accel total m/s2: "
  );
  Serial.println(
    packet.accel_total_cms2 /
    100.0f,
    2
  );

  Serial.print(
    "Roll deg: "
  );
  Serial.println(
    packet.roll_deg_x100 /
    100.0f,
    2
  );

  Serial.print(
    "Pitch deg: "
  );
  Serial.println(
    packet.pitch_deg_x100 /
    100.0f,
    2
  );

  Serial.print(
    "Mission mode: "
  );
  Serial.print(
    packet.mode
  );
  Serial.print(" (");
  Serial.print(
    missionModeName(
      packet.mode
    )
  );
  Serial.println(")");

  sendTelemetryToSerial(
    packet,
    frame.rssi
  );

  serialSent++;
}


// ============================================================
// USB serial telemetry line
//
// Binary telemetry uses compact acceleration values in cm/s^2.
// JSON converts them back to m/s^2 for easier local-app
// interpretation. Each line is prefixed with "TLM:" so the PC
// app can tell it apart from the human-readable debug prints
// above sharing the same serial port.
// ============================================================

void sendTelemetryToSerial(
  const TelemetryPacket &packet,
  int8_t espNowRssi
) {
  String json;
  json.reserve(512);

  json = "{";

  json +=
    "\"counter\":" +
    String(packet.counter) +
    ",";

  json +=
    "\"time_ms\":" +
    String(packet.time_ms) +
    ",";

  json +=
    "\"lat\":" +
    String(packet.lat, 6) +
    ",";

  json +=
    "\"lon\":" +
    String(packet.lon, 6) +
    ",";

  json +=
    "\"alt\":" +
    String(packet.alt, 2) +
    ",";

  json +=
    "\"speed\":" +
    String(packet.speed, 2) +
    ",";

  json +=
    "\"sat\":" +
    String(packet.sat) +
    ",";

  json +=
    "\"temp\":" +
    String(packet.temp, 2) +
    ",";

  json +=
    "\"humidity\":" +
    String(packet.humidity, 2) +
    ",";

  json +=
    "\"pressure\":" +
    String(packet.pressure, 2) +
    ",";

  json +=
    "\"gas_kohm\":" +
    String(packet.gas_kohm, 2) +
    ",";

  json +=
    "\"accel_x\":" +
    String(
      packet.accel_x_cms2 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"accel_y\":" +
    String(
      packet.accel_y_cms2 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"accel_z\":" +
    String(
      packet.accel_z_cms2 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"accel_total\":" +
    String(
      packet.accel_total_cms2 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"roll\":" +
    String(
      packet.roll_deg_x100 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"pitch\":" +
    String(
      packet.pitch_deg_x100 /
      100.0f,
      2
    ) +
    ",";

  json +=
    "\"mode\":" +
    String(packet.mode) +
    ",";

  json +=
    "\"espnow_rssi\":" +
    String(espNowRssi);

  json += "}";

  Serial.print("TLM:");
  Serial.println(json);
}