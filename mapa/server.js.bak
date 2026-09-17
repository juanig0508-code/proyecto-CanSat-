
const express = require("express");
const path = require("path");
const Database = require("better-sqlite3");

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname)));

// ======================================================
// DATABASE
// ======================================================

const db = new Database("hermes.db");

db.prepare(`
  CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    counter INTEGER,
    time_ms INTEGER,
    mode INTEGER,

    lat REAL,
    lon REAL,
    alt REAL,
    speed REAL,
    sat INTEGER,

    temp REAL,
    humidity REAL,
    pressure REAL,
    gas_kohm REAL,

    accel_x REAL,
    accel_y REAL,
    accel_z REAL,
    accel_total REAL,

    espnow_rssi INTEGER,

    date TEXT,
    time TEXT,
    received_at TEXT
  )
`).run();


const insertTelemetry = db.prepare(`
  INSERT INTO telemetry (
    counter,
    time_ms,
    mode,

    lat,
    lon,
    alt,
    speed,
    sat,

    temp,
    humidity,
    pressure,
    gas_kohm,

    accel_x,
    accel_y,
    accel_z,
    accel_total,

    espnow_rssi,

    date,
    time,
    received_at
  )
  VALUES (
    @counter,
    @time_ms,
    @mode,

    @lat,
    @lon,
    @alt,
    @speed,
    @sat,

    @temp,
    @humidity,
    @pressure,
    @gas_kohm,

    @accel_x,
    @accel_y,
    @accel_z,
    @accel_total,

    @espnow_rssi,

    @date,
    @time,
    @received_at
  )
`);
// Avoid cached API responses while the dashboard is running live.
app.use((req, res, next) => {
  if (req.path.startsWith("/api/")) {
    res.set("Cache-Control", "no-store");
  }
  next();
});


// ======================================================
// TELEMETRY STORAGE
// ======================================================

// 2000 muestras a 750 ms por muestra son aproximadamente
// 25 minutos de telemetría.
const MAX_HISTORY = 2000;

let telemetryHistory = db.prepare(`
  SELECT *
  FROM telemetry
  ORDER BY id DESC
  LIMIT ?
`).all(MAX_HISTORY);

telemetryHistory.reverse();
// Long-poll clients waiting for the next telemetry packet.
// This lets the dashboard update as soon as a packet arrives instead of
// waiting for the next fixed polling interval.
const LATEST_WAIT_MS = 3000;
const MAX_PENDING_LATEST_CLIENTS = 20;
let pendingLatestClients = [];


// ======================================================
// HELPERS
// ======================================================

function numberOrNull(value) {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return null;
  }

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : null;
}

function getLatestTelemetry() {
  if (telemetryHistory.length === 0) {
    return null;
  }

  return telemetryHistory[telemetryHistory.length - 1];
}

function removePendingLatestClient(res) {
  pendingLatestClients = pendingLatestClients.filter(
    client => client.res !== res
  );
}

function waitForNextTelemetry(res) {
  if (pendingLatestClients.length >= MAX_PENDING_LATEST_CLIENTS) {
    return res.status(503).json({
      ok: false,
      error: "Too many pending latest requests"
    });
  }

  const timeout = setTimeout(() => {
    removePendingLatestClient(res);

    if (!res.headersSent) {
      // No new packet arrived during the wait window.
      // The frontend keeps showing the last known values.
      res.status(204).end();
    }
  }, LATEST_WAIT_MS);

  pendingLatestClients.push({ res, timeout });

  res.on("close", () => {
    clearTimeout(timeout);
    removePendingLatestClient(res);
  });
}

function notifyLatestClients(entry) {
  const clients = pendingLatestClients;
  pendingLatestClients = [];

  for (const client of clients) {
    clearTimeout(client.timeout);

    if (!client.res.headersSent) {
      client.res.json(entry);
    }
  }
}


// ======================================================
// GET TELEMETRY HISTORY
// ======================================================

app.get("/api/telemetry", (req, res) => {

  try {

    const rows = db.prepare(`
      SELECT *
      FROM telemetry
      ORDER BY id ASC
    `).all();

    res.json(rows);

  } catch (err) {

    console.error("Database read error:", err);

    res.status(500).json({
      ok: false,
      error: "Could not read telemetry database"
    });

  }

});


// ======================================================
// GET LATEST TELEMETRY SAMPLE
// ======================================================

app.get("/api/latest", (req, res) => {

  const latest = getLatestTelemetry();

  if (!latest) {
    return res.status(404).json({
      ok: false,
      message: "No telemetry received yet"
    });
  }

  // Optional long-poll mode:
  // /api/latest?after=123 means "only answer with a new packet
  // if the latest counter is different from 123".
  const after = numberOrNull(req.query.after);

  if (after !== null && latest.counter === after) {
    return waitForNextTelemetry(res);
  }

  res.json(latest);
});


// ======================================================
// POST TELEMETRY
// ======================================================

app.post("/api/telemetry", (req, res) => {

  const data = req.body;
  const now = new Date();
  const utcMinus3 = new Date(now.getTime() - 3 * 60 * 60 * 1000);


  const entry = {

    // ==================================================
    // Mission
    // ==================================================

    counter:
      numberOrNull(data.counter),

    time_ms:
      numberOrNull(data.time_ms),

    mode:
      numberOrNull(data.mode),


    // ==================================================
    // GPS
    // ==================================================

    lat:
      numberOrNull(data.lat),

    lon:
      numberOrNull(data.lon),

    alt:
      numberOrNull(data.alt),

    speed:
      numberOrNull(data.speed),

    sat:
      numberOrNull(data.sat),


    // ==================================================
    // BME680
    // ==================================================

    temp:
      numberOrNull(data.temp),

    humidity:
      numberOrNull(data.humidity),

    pressure:
      numberOrNull(data.pressure),

    gas_kohm:
      numberOrNull(data.gas_kohm),


    // ==================================================
    // MPU6050
    // Acceleration is received from the ground ESP32
    // already converted to m/s^2.
    // ==================================================

    accel_x:
      numberOrNull(data.accel_x),

    accel_y:
      numberOrNull(data.accel_y),

    accel_z:
      numberOrNull(data.accel_z),

    accel_total:
      numberOrNull(data.accel_total),


    // ==================================================
    // ESP-NOW link
    // ==================================================

    espnow_rssi:
      numberOrNull(data.espnow_rssi),


    // ==================================================
    // Server reception time
    // ==================================================

    date:
      utcMinus3.toISOString().split("T")[0],

    time:
      utcMinus3.toISOString().split("T")[1].split(".")[0],

    received_at:
      now.toISOString()
  };


  // ====================================================
  // Basic packet validation
  // ====================================================

  if (entry.counter === null) {

    return res.status(400).json({
      ok: false,
      error: "Missing or invalid counter"
    });

  }
  // Store permanently in SQLite
  try {

    insertTelemetry.run(entry);

  } catch (err) {

    console.error("Database error:", err);

    return res.status(500).json({
      ok: false,
      error: "Could not store telemetry in database"
    });

  }

  // ====================================================
  // Store telemetry
  // ====================================================

  telemetryHistory.push(entry);


  // Keep history bounded in RAM.
  if (telemetryHistory.length > MAX_HISTORY) {
    telemetryHistory.shift();
  }


  // ====================================================
  // Server console output
  // ====================================================

  // Wake any dashboard request waiting for the next packet.
  notifyLatestClients(entry);

  console.log(
    `Stored telemetry #${entry.counter} | ` +
    `mode=${entry.mode} | ` +
    `alt=${entry.alt} m | ` +
    `speed=${entry.speed} m/s | ` +
    `RSSI=${entry.espnow_rssi} dBm`
  );


  // ====================================================
  // Response to ground ESP32
  // ====================================================

  res.status(200).json({
    ok: true,
    counter: entry.counter,
    stored: telemetryHistory.length
  });

});


// ======================================================
// DOWNLOAD TELEMETRY CSV
// ======================================================

app.get("/api/download.csv", (req, res) => {

  try {

    const rows = db.prepare(`
      SELECT
        counter,
        time_ms,
        mode,

        lat,
        lon,
        alt,
        speed,
        sat,

        temp,
        humidity,
        pressure,
        gas_kohm,

        accel_x,
        accel_y,
        accel_z,
        accel_total,

        espnow_rssi,

        date,
        time,
        received_at

      FROM telemetry
      ORDER BY id ASC
    `).all();


    if (rows.length === 0) {

      return res.status(404).send(
        "No telemetry data available"
      );

    }


    function escapeCsv(value) {

      if (value === null || value === undefined) {
        return "";
      }

      const text = String(value);

      if (
        text.includes(",") ||
        text.includes('"') ||
        text.includes("\n")
      ) {

        return `"${text.replace(/"/g, '""')}"`;

      }

      return text;
    }


    const headers = Object.keys(rows[0]);

    const csv = [
      headers.join(","),

      ...rows.map(row =>
        headers
          .map(header => escapeCsv(row[header]))
          .join(",")
      )

    ].join("\n");


    const now = new Date();

    const fileDate =
      now.toISOString().split("T")[0];

    const fileName =
      `hermes_telemetry_${fileDate}.csv`;


    res.setHeader(
      "Content-Type",
      "text/csv; charset=utf-8"
    );

    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${fileName}"`
    );

    res.send(csv);

  } catch (err) {

    console.error("CSV export error:", err);

    res.status(500).json({
      ok: false,
      error: "Could not generate CSV"
    });

  }

});

// ======================================================
// ROOT PAGE
// ======================================================

app.get("/", (req, res) => {

  res.sendFile(
    path.join(
      __dirname,
      "mapa.html"
    )
  );

});


// ======================================================
// SERVER START
// ======================================================

const PORT =
  process.env.PORT || 3000;


app.listen(PORT, () => {

  console.log(
    "======================================"
  );

  console.log(
    "Hermes telemetry server running"
  );

  console.log(
    "Port:",
    PORT
  );

  console.log(
    "Max history:",
    MAX_HISTORY,
    "samples"
  );

  console.log(
    "======================================"
  );

});