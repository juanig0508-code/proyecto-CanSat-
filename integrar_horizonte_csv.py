#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent

FILES = {
    "server": ROOT / "mapa" / "server.js",
    "html": ROOT / "mapa" / "mapa.html",
    "flight": ROOT / "nrf24" / "transmisor_ultima_prueba_efectiva" / "modos_de_vuelo" / "modos_de_vuelo.ino",
    "receiver": ROOT / "transmisores" / "esp32_receiver_test" / "receiver" / "receiver.ino",
    "cam": ROOT / "esp32-cam" / "esp32_cam" / "esp32_cam.ino",
}

def read(key):
    p = FILES[key]
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    return p.read_text(encoding="utf-8")

def write(key, text):
    p = FILES[key]
    backup = p.with_suffix(p.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(p, backup)
    p.write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if new in text:
        print(f"[OK] {label}: ya estaba aplicado")
        return text
    if old not in text:
        raise RuntimeError(f"No encontre el bloque esperado para: {label}")
    return text.replace(old, new, 1)

# ============================================================
# 1) BACKEND: conservar SQLite + CSV y agregar roll/pitch
# ============================================================

s = read("server")

s = replace_once(
    s,
    '''    accel_z REAL,
    accel_total REAL,

    espnow_rssi INTEGER,''',
    '''    accel_z REAL,
    accel_total REAL,

    roll REAL,
    pitch REAL,

    espnow_rssi INTEGER,''',
    "server: columnas roll/pitch en CREATE TABLE"
)

migration_anchor = ''').run();


const insertTelemetry = db.prepare(`'''
migration_block = ''').run();

// Schema migration for databases created before roll/pitch existed.
const telemetryColumns = new Set(
  db.prepare("PRAGMA table_info(telemetry)")
    .all()
    .map(column => column.name)
);

if (!telemetryColumns.has("roll")) {
  db.prepare("ALTER TABLE telemetry ADD COLUMN roll REAL").run();
}

if (!telemetryColumns.has("pitch")) {
  db.prepare("ALTER TABLE telemetry ADD COLUMN pitch REAL").run();
}


const insertTelemetry = db.prepare(`'''
if "Schema migration for databases created before roll/pitch existed." not in s:
    if migration_anchor not in s:
        raise RuntimeError("No encontre el punto de migracion SQLite en server.js")
    s = s.replace(migration_anchor, migration_block, 1)
else:
    print("[OK] server: migracion SQLite ya estaba aplicada")

s = replace_once(
    s,
    '''    accel_z,
    accel_total,

    espnow_rssi,''',
    '''    accel_z,
    accel_total,

    roll,
    pitch,

    espnow_rssi,''',
    "server: columnas INSERT"
)

s = replace_once(
    s,
    '''    @accel_z,
    @accel_total,

    @espnow_rssi,''',
    '''    @accel_z,
    @accel_total,

    @roll,
    @pitch,

    @espnow_rssi,''',
    "server: valores INSERT"
)

s = replace_once(
    s,
    '''    accel_total:
      numberOrNull(data.accel_total),


    // ==================================================
    // ESP-NOW link''',
    '''    accel_total:
      numberOrNull(data.accel_total),

    // ==================================================
    // MPU6050 attitude
    // ==================================================

    roll:
      numberOrNull(data.roll),

    pitch:
      numberOrNull(data.pitch),


    // ==================================================
    // ESP-NOW link''',
    "server: recibir roll/pitch"
)

s = replace_once(
    s,
    '''        accel_z,
        accel_total,

        espnow_rssi,''',
    '''        accel_z,
        accel_total,

        roll,
        pitch,

        espnow_rssi,''',
    "server: exportar roll/pitch en CSV"
)

write("server", s)

# ============================================================
# 2) DASHBOARD: conservar DOWNLOAD CSV y agregar horizonte
# ============================================================

h = read("html")

h = replace_once(
    h,
    '''    #connection { color: #facc15; }

    .menu {''',
    '''    #connection { color: #facc15; }

    .horizon-wrap { display: flex; justify-content: center; margin-bottom: 8px; }
    #horizonCanvas { border-radius: 50%; border: 1px solid #333; background: #000; }

    .menu {''',
    "html: CSS horizonte"
)

h = replace_once(
    h,
    '''      <div class="section">
        <h4 class="title">GROUND RECEIPT TIME</h4>''',
    '''      <div class="section">
        <h4 class="title">ATTITUDE</h4>
        <div class="horizon-wrap">
          <canvas id="horizonCanvas" width="200" height="200"></canvas>
        </div>
        <div class="grid">
          <div class="card"><p>Roll (deg)</p><span id="roll">--</span></div>
          <div class="card"><p>Pitch (deg)</p><span id="pitch">--</span></div>
        </div>
      </div>

      <div class="section">
        <h4 class="title">GROUND RECEIPT TIME</h4>''',
    "html: panel ATTITUDE"
)

horizon_js = r'''
    // ==================================================
    // Artificial horizon (roll/pitch attitude widget)
    // ==================================================

    const horizonCanvas = document.getElementById("horizonCanvas");
    const horizonCtx = horizonCanvas ? horizonCanvas.getContext("2d") : null;
    const HORIZON_PX_PER_DEG = 3;

    function drawArtificialHorizon(rollDeg, pitchDeg) {
      if (!horizonCtx) return;

      const w = horizonCanvas.width;
      const h = horizonCanvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const radius = cx - 2;

      const roll = Number.isFinite(Number(rollDeg)) ? Number(rollDeg) : 0;
      const pitch = Number.isFinite(Number(pitchDeg)) ? Number(pitchDeg) : 0;
      const pitchOffsetPx = Math.max(
        -radius,
        Math.min(radius, pitch * HORIZON_PX_PER_DEG)
      );

      horizonCtx.clearRect(0, 0, w, h);

      horizonCtx.save();
      horizonCtx.beginPath();
      horizonCtx.arc(cx, cy, radius, 0, Math.PI * 2);
      horizonCtx.clip();

      horizonCtx.translate(cx, cy);
      horizonCtx.rotate(-roll * Math.PI / 180);
      horizonCtx.translate(0, pitchOffsetPx);

      const bigSize = (w + h) * 2;

      horizonCtx.fillStyle = "#4a90d9";
      horizonCtx.fillRect(-bigSize / 2, -bigSize, bigSize, bigSize);

      horizonCtx.fillStyle = "#8b5a2b";
      horizonCtx.fillRect(-bigSize / 2, 0, bigSize, bigSize);

      horizonCtx.strokeStyle = "#ffffff";
      horizonCtx.lineWidth = 2;
      horizonCtx.beginPath();
      horizonCtx.moveTo(-bigSize / 2, 0);
      horizonCtx.lineTo(bigSize / 2, 0);
      horizonCtx.stroke();

      horizonCtx.restore();

      horizonCtx.strokeStyle = "#ffcc00";
      horizonCtx.fillStyle = "#ffcc00";
      horizonCtx.lineWidth = 3;

      horizonCtx.beginPath();
      horizonCtx.moveTo(cx - 45, cy);
      horizonCtx.lineTo(cx - 12, cy);
      horizonCtx.moveTo(cx + 12, cy);
      horizonCtx.lineTo(cx + 45, cy);
      horizonCtx.moveTo(cx, cy);
      horizonCtx.lineTo(cx, cy - 10);
      horizonCtx.stroke();

      horizonCtx.beginPath();
      horizonCtx.arc(cx, cy, 4, 0, Math.PI * 2);
      horizonCtx.fill();

      horizonCtx.strokeStyle = "#222";
      horizonCtx.lineWidth = 3;
      horizonCtx.beginPath();
      horizonCtx.arc(cx, cy, radius, 0, Math.PI * 2);
      horizonCtx.stroke();
    }

'''
if "function drawArtificialHorizon" not in h:
    marker = '''    function validGps(lat, lon) {'''
    if marker not in h:
        raise RuntimeError("No encontre validGps() en mapa.html")
    h = h.replace(marker, horizon_js + marker, 1)
else:
    print("[OK] html: JS horizonte ya estaba aplicado")

h = replace_once(
    h,
    '''      setText("accel_z", data.accel_z, 2);
      setText("accel_total", data.accel_total, 2);

      setText("date", data.date);''',
    '''      setText("accel_z", data.accel_z, 2);
      setText("accel_total", data.accel_total, 2);

      setText("roll", data.roll, 2);
      setText("pitch", data.pitch, 2);
      drawArtificialHorizon(data.roll, data.pitch);

      setText("date", data.date);''',
    "html: actualizar horizonte con telemetria"
)

if "drawArtificialHorizon(0, 0);" not in h:
    marker = '''    loadHistory().then(startLatestLoop);'''
    if marker not in h:
        raise RuntimeError("No encontre el arranque del dashboard")
    h = h.replace(marker, '    drawArtificialHorizon(0, 0);\n' + marker, 1)
else:
    print("[OK] html: inicializacion horizonte ya aplicada")

write("html", h)

# ============================================================
# 3) TRANSMISOR PRINCIPAL: paquete 50 -> 54 bytes + roll/pitch
# ============================================================

f = read("flight")

f = replace_once(
    f,
    '''  int16_t accel_z_cms2;
  int16_t accel_total_cms2;

  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 50,
  "TelemetryPacket must be exactly 50 bytes"
);''',
    '''  int16_t accel_z_cms2;
  int16_t accel_total_cms2;

  int16_t roll_deg_x100;   // roll angle [deg] x100
  int16_t pitch_deg_x100;  // pitch angle [deg] x100

  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 54,
  "TelemetryPacket must be exactly 54 bytes"
);''',
    "flight: ampliar TelemetryPacket"
)

f = replace_once(
    f,
    '''int16_t accelToCms2(float accel_ms2);

size_t sendFramedUartPacket''',
    '''int16_t accelToCms2(float accel_ms2);
int16_t angleToDeg100(float angleDeg);

size_t sendFramedUartPacket''',
    "flight: declarar angleToDeg100"
)

angle_fn = r'''
// ======================================================
// Angle conversion
// deg -> deg x100
// -32768 is reserved as invalid.
// ======================================================

int16_t angleToDeg100(float angleDeg) {
  if (!isfinite(angleDeg)) {
    return -32768;
  }

  float scaled = angleDeg * 100.0f;

  if (scaled > 32767.0f) {
    scaled = 32767.0f;
  }

  if (scaled < -32767.0f) {
    scaled = -32767.0f;
  }

  return (int16_t)lroundf(scaled);
}

'''
if "int16_t angleToDeg100(float angleDeg) {" not in f:
    marker = '''// ======================================================
// UART frame writer'''
    if marker not in f:
        raise RuntimeError("No encontre UART frame writer en modos_de_vuelo.ino")
    f = f.replace(marker, angle_fn + marker, 1)
else:
    print("[OK] flight: angleToDeg100 ya estaba aplicado")

f = replace_once(
    f,
    '''  packet.accel_z_cms2 = accelToCms2(az);
  packet.accel_total_cms2 = accelToCms2(accelTotal);

  packet.mode = (uint8_t)currentMode;''',
    '''  packet.accel_z_cms2 = accelToCms2(az);
  packet.accel_total_cms2 = accelToCms2(accelTotal);

  packet.roll_deg_x100 = angleToDeg100(rollDeg);
  packet.pitch_deg_x100 = angleToDeg100(pitchDeg);

  packet.mode = (uint8_t)currentMode;''',
    "flight: cargar roll/pitch en paquete"
)

f = replace_once(
    f,
    '''  Serial.print("Accel total cm/s^2: ");
  Serial.println(packet.accel_total_cms2);

  Serial.print("Mission mode: ");''',
    '''  Serial.print("Accel total cm/s^2: ");
  Serial.println(packet.accel_total_cms2);

  Serial.print("Roll deg x100: ");
  Serial.println(packet.roll_deg_x100);

  Serial.print("Pitch deg x100: ");
  Serial.println(packet.pitch_deg_x100);

  Serial.print("Mission mode: ");''',
    "flight: debug roll/pitch"
)

write("flight", f)

# ============================================================
# 4) GROUND RECEIVER: paquete 54 + JSON roll/pitch
# ============================================================

r = read("receiver")

r = replace_once(
    r,
    '''  int16_t accel_z_cms2;       // cm/s^2
  int16_t accel_total_cms2;   // cm/s^2

  // Mission state
  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 50,
  "TelemetryPacket must be exactly 50 bytes"
);''',
    '''  int16_t accel_z_cms2;       // cm/s^2
  int16_t accel_total_cms2;   // cm/s^2

  // MPU6050 attitude
  int16_t roll_deg_x100;      // deg x100
  int16_t pitch_deg_x100;     // deg x100

  // Mission state
  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 54,
  "TelemetryPacket must be exactly 54 bytes"
);''',
    "receiver: ampliar TelemetryPacket"
)

r = replace_once(
    r,
    '''  Serial.print(
    "Mission mode: "
  );''',
    '''  Serial.print("Roll deg: ");
  Serial.println(packet.roll_deg_x100 / 100.0f, 2);

  Serial.print("Pitch deg: ");
  Serial.println(packet.pitch_deg_x100 / 100.0f, 2);

  Serial.print(
    "Mission mode: "
  );''',
    "receiver: debug roll/pitch"
)

r = replace_once(
    r,
    '''  json +=
    "\\"mode\\":" +
    String(packet.mode) +''',
    '''  json +=
    "\\"roll\\":" +
    String(packet.roll_deg_x100 / 100.0f, 2) +
    ",";

  json +=
    "\\"pitch\\":" +
    String(packet.pitch_deg_x100 / 100.0f, 2) +
    ",";

  json +=
    "\\"mode\\":" +
    String(packet.mode) +''',
    "receiver: JSON roll/pitch"
)

write("receiver", r)

# ============================================================
# 5) ESP32-CAM: paquete 54 + CSV onboard con roll/pitch
# ============================================================

c = read("cam")

c = replace_once(
    c,
    '''  int16_t accel_z_cms2;
  int16_t accel_total_cms2;

  // Mission state
  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 50,
  "TelemetryPacket must be exactly 50 bytes"
);''',
    '''  int16_t accel_z_cms2;
  int16_t accel_total_cms2;

  // MPU6050 attitude
  int16_t roll_deg_x100;
  int16_t pitch_deg_x100;

  // Mission state
  uint8_t mode;
};

static_assert(
  sizeof(TelemetryPacket) == 54,
  "TelemetryPacket must be exactly 54 bytes"
);''',
    "cam: ampliar TelemetryPacket"
)

c = replace_once(
    c,
    '''  file.println(p.mode);''',
    '''  file.print(p.roll_deg_x100 / 100.0f, 2);
  file.print(",");

  file.print(p.pitch_deg_x100 / 100.0f, 2);
  file.print(",");

  file.println(p.mode);''',
    "cam: guardar roll/pitch en CSV"
)

c = replace_once(
    c,
    '''        "accel_x_ms2,accel_y_ms2,accel_z_ms2,"
        "accel_total_ms2,mode"''',
    '''        "accel_x_ms2,accel_y_ms2,accel_z_ms2,"
        "accel_total_ms2,roll_deg,pitch_deg,mode"''',
    "cam: cabecera CSV roll/pitch"
)

c = replace_once(
    c,
    '''  Serial.print("Mode: ");
  Serial.println(
    telemetryPacket.mode
  );''',
    '''  Serial.print("Roll deg: ");
  Serial.println(telemetryPacket.roll_deg_x100 / 100.0f, 2);

  Serial.print("Pitch deg: ");
  Serial.println(telemetryPacket.pitch_deg_x100 / 100.0f, 2);

  Serial.print("Mode: ");
  Serial.println(
    telemetryPacket.mode
  );''',
    "cam: debug roll/pitch"
)

write("cam", c)

print()
print("Integracion terminada.")
print("Se crearon backups .bak junto a cada archivo modificado.")
print("Verifica con: git diff")
print("Luego compila los sketches y ejecuta: cd mapa && npm install && node server.js")
