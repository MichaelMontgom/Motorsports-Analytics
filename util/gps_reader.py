import serial
import serial.tools.list_ports
import pynmea2
import time
from dataclasses import dataclass
from typing import Optional, Iterator


KNOTS_TO_MPH = 1.15078


@dataclass
class GPSPoint:
    timestamp: float       # Unix time (time.time())
    speed_mph: float
    latitude: float
    longitude: float
    gps_time: str          # Raw NMEA time string
    heading_deg: Optional[float] = None   # true course over ground, degrees


PMTK_SET_NMEA_UPDATE_10HZ = b"$PMTK220,100*2F\r\n"
PMTK_SET_NMEA_UPDATE_5HZ  = b"$PMTK220,200*2C\r\n"
PMTK_SET_NMEA_UPDATE_1HZ  = b"$PMTK220,1000*1F\r\n"
PMTK_SET_BAUD_9600        = b"$PMTK251,9600*17\r\n"


def find_gps_port() -> Optional[str]:
    """Auto-detect the Adafruit Ultimate GPS USB port."""
    candidates = serial.tools.list_ports.comports()
    for port in candidates:
        desc = (port.description or "").lower()
        mfr  = (port.manufacturer or "").lower()
        if any(k in desc or k in mfr for k in ("cp210", "cp2104", "adafruit", "gps", "uart")):
            return port.device
    # Fallback: return first USB serial port
    for port in candidates:
        if "usb" in (port.device or "").lower() or "usbserial" in (port.device or "").lower():
            return port.device
    return None


class GPSReader:
    """
    Reads NMEA sentences from the Adafruit Ultimate GPS USB module and
    yields GPSPoint objects containing speed and position data.
    """

    def __init__(self, port: str, baudrate: int = 9600, update_hz: int = 10):
        self.port = port
        self.baudrate = baudrate
        self.update_hz = update_hz
        self._serial: Optional[serial.Serial] = None

    def open(self) -> None:
        self._serial = serial.Serial(self.port, self.baudrate, timeout=1)
        time.sleep(0.5)
        self._set_update_rate()

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            # Restore 1 Hz before closing so the module is left in a clean state
            self._serial.write(PMTK_SET_NMEA_UPDATE_1HZ)
            self._serial.close()

    def _set_update_rate(self) -> None:
        if self._serial is None:
            return
        if self.update_hz >= 10:
            self._serial.write(PMTK_SET_NMEA_UPDATE_10HZ)
        elif self.update_hz >= 5:
            self._serial.write(PMTK_SET_NMEA_UPDATE_5HZ)
        else:
            self._serial.write(PMTK_SET_NMEA_UPDATE_1HZ)
        time.sleep(0.1)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def read_raw_lines(self) -> Iterator[str]:
        """Yield every raw NMEA line as a string (no filtering)."""
        if self._serial is None:
            raise RuntimeError("GPSReader not opened. Use 'with GPSReader(...)' or call open().")

        while True:
            try:
                raw = self._serial.readline()
                line = raw.decode("ascii", errors="replace").strip()
            except serial.SerialException:
                break
            if line:
                yield line

    def read_points(self) -> Iterator[GPSPoint]:
        """Yield GPSPoint objects as valid RMC sentences arrive."""
        for line in self.read_raw_lines():
            if not line.startswith("$"):
                continue

            try:
                msg = pynmea2.parse(line)
            except pynmea2.ParseError:
                continue

            # GPRMC / GNRMC carry speed over ground in knots
            if getattr(msg, "sentence_type", None) != "RMC":
                continue
            if not getattr(msg, "status", None) == "A":  # A = active fix
                continue

            speed_mph = float(msg.spd_over_grnd or 0) * KNOTS_TO_MPH
            lat = msg.latitude
            lon = msg.longitude
            heading = float(msg.true_course) if msg.true_course else None

            yield GPSPoint(
                timestamp=time.time(),
                speed_mph=speed_mph,
                latitude=lat,
                longitude=lon,
                gps_time=str(msg.timestamp),
                heading_deg=heading,
            )
