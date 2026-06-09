#!/usr/bin/env python3
"""
GPS performance timer. Launch a timing mode with --mode.

Usage:
    python main.py --mode drag                          # 0-60 mph and 1/4 mile timer
    python main.py --mode drag --port /dev/ttyUSB0
    python main.py --mode drag --hz 5                   # GPS update rate (1, 5, or 10 Hz)
    python main.py --mode map-course --name "Course"    # map an autocross course
    python main.py --mode autocross --course "Course"   # time laps on a saved course
    python main.py --list-courses                       # show saved autocross courses
    python main.py --list-ports                         # show available serial ports
    python main.py --debug                              # print every raw NMEA sentence
"""

import argparse
import sys
import signal

import serial.tools.list_ports

from util.gps_reader import find_gps_port
from util.nmea_debug import run_debug
from drag.runner import run_drag
from autocross.runner import run_autocross, run_map_course
from autocross.course import list_courses


MODES = {
    "drag": run_drag,
    "autocross": run_autocross,
    "map-course": run_map_course,
}


def list_ports() -> None:
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    print(f"{'Port':<20} {'Description'}")
    print("-" * 60)
    for p in ports:
        print(f"{p.device:<20} {p.description}")


def show_courses() -> None:
    names = list_courses()
    if not names:
        print("No saved courses. Map one with: python main.py --mode map-course --name \"...\"")
        return
    print("Saved courses:")
    for name in names:
        print(f"  - {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GPS Performance Timer")
    parser.add_argument("--mode", choices=sorted(MODES),
                        help="Timing mode to launch")
    parser.add_argument("--port", help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    parser.add_argument("--hz", type=int, default=10, choices=[1, 5, 10],
                        help="GPS update rate in Hz (default: 10)")
    parser.add_argument("--course", help="Course name (for --mode autocross)")
    parser.add_argument("--name", help="Course name to create (for --mode map-course)")
    parser.add_argument("--width", type=float, default=50.0,
                        help="Gate width in feet for mapping (default: 50)")
    parser.add_argument("--list-ports", action="store_true",
                        help="List available serial ports and exit")
    parser.add_argument("--list-courses", action="store_true",
                        help="List saved autocross courses and exit")
    parser.add_argument("--debug", action="store_true",
                        help="Print every raw NMEA sentence from the module")
    args = parser.parse_args()

    # Utility flags that need no GPS connection.
    if args.list_ports:
        list_ports()
        return
    if args.list_courses:
        show_courses()
        return

    if not args.mode and not args.debug:
        parser.error("--mode is required (choices: " + ", ".join(sorted(MODES)) + ")")

    # Mode-specific argument validation.
    if args.mode == "autocross" and not args.course:
        parser.error("--mode autocross requires --course \"<name>\"")
    if args.mode == "map-course" and not args.name:
        parser.error("--mode map-course requires --name \"<name>\"")

    port = args.port or find_gps_port()
    if not port:
        print("ERROR: Could not auto-detect GPS port.")
        print("Run with --list-ports to see available ports, then use --port <port>.")
        sys.exit(1)

    interrupted = [False]  # list so nested closures can mutate it

    def _handle_sigint(sig, frame):
        interrupted[0] = True

    signal.signal(signal.SIGINT, _handle_sigint)

    print(f"Connecting to GPS on {port} at {args.hz} Hz...")

    try:
        if args.debug:
            run_debug(port, args.hz, interrupted)
        else:
            MODES[args.mode](port, args, interrupted)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    print("\nGoodbye.")


if __name__ == "__main__":
    main()
