"""Raw NMEA stream viewer for GPS diagnostics (mode-independent)."""

import time

import pynmea2

from util.gps_reader import GPSReader


SENTENCE_COLORS = {
    "RMC": "\033[92m",   # green  — position + speed
    "GGA": "\033[94m",   # blue   — fix quality + altitude
    "GSA": "\033[93m",   # yellow — satellite info
    "GSV": "\033[90m",   # grey   — satellites in view
    "VTG": "\033[96m",   # cyan   — course over ground
}
RESET = "\033[0m"
DIM   = "\033[2m"


def _sentence_label(line: str) -> str:
    """Return a short, coloured sentence-type label for display."""
    try:
        msg = pynmea2.parse(line)
        stype = getattr(msg, "sentence_type", None) or "???"
        color = SENTENCE_COLORS.get(stype, "\033[97m")
        return f"{color}{stype:<4}{RESET}"
    except Exception:
        return f"\033[91mRAW {RESET}"


def run_debug(port: str, hz: int, interrupted_flag: list) -> None:
    print(f"\n  [DEBUG] Raw NMEA stream from {port}  |  Ctrl+C to quit\n")
    print(f"  {'TYPE':<6} {'RAW SENTENCE'}")
    print("  " + "-" * 72)

    with GPSReader(port, update_hz=hz) as gps:
        for line in gps.read_raw_lines():
            if interrupted_flag[0]:
                break
            label = _sentence_label(line)
            ts = time.strftime("%H:%M:%S")
            print(f"  {DIM}{ts}{RESET}  {label}  {line}")
