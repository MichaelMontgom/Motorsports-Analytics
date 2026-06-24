## Overview

This is a single-box GPS telemetry system that ingests 10 Hz GPS fixes from an Adafruit Ultimate GPS module, parses the raw NMEA stream, derives motorsports-relevant channels (speed, heading, position), and logs them to disk for post-session analysis — with optional live streaming to a UI client.

The whole pipeline is intended to run on a Raspberry Pi 5. 

## Hardware

| Component | Spec / Notes |
|---|---|
| Compute | Raspberry Pi 5, 8 GB RAM |
| GPS | Adafruit Ultimate GPS GNSS with USB (MTK3339 chipset, configured to **10 Hz**) |

The Adafruit Ultimate GPS plugs in over USB and presents a standard serial port — no GPIO UART wiring required for the prototype.

## How it works

```
┌──────────────┐   NMEA @ 10 Hz    ┌─────────────────────────────┐
│ Adafruit GPS │ ───────────────▶  │  Python daemon (Pi 5)       │
│  (USB/UART)  │   /dev/ttyUSB0    │                             │
└──────────────┘                   │  • serial read              │
                                   │  • NMEA parse (GGA/RMC/VTG) │
                                   │  • channel derivation       │
                                   │  • session logging ─────────┼──▶ session files (CSV)
                                   │  • WebSocket server (local) ┼──▶ UI client (live)
                                   └─────────────────────────────┘
```

- **Ingest** — reads the raw NMEA sentence stream from the serial port at 9600 baud (module default), with the module configured to emit fixes at 10 Hz.
- **Parse** — extracts position, time, and motion channels from the standard NMEA sentences (`GGA`, `RMC`, `VTG`).
- **Speed** — taken from the receiver's **Doppler-derived velocity** in the `RMC`/`VTG` sentences, *not* computed by differencing successive position fixes. Doppler speed is lower-latency and far less noisy than position-derived speed.
- **Timestamping** — uses the GPS fix time as the authoritative clock rather than the host wall clock, to avoid scheduler/GC jitter polluting the sample timeline.
- **Log** — each session is written to a flat file on disk for later analysis.
- **Stream** — a local WebSocket server pushes live JSON telemetry frames to a connected UI client over `127.0.0.1`.

