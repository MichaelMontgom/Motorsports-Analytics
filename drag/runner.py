"""Drag-strip timing mode: measures 0-60 mph and quarter-mile times."""

from util.gps_reader import GPSReader
from util.format import fmt_time, fmt_speed
from drag.performance_calculator import PerformanceCalculator


def print_live(speed_mph: float, calc: PerformanceCalculator) -> None:
    partial = calc.partial_result()
    sixty  = fmt_time(partial.zero_to_sixty_s)
    dist   = f"{partial.distance_ft:.0f} ft"
    status = "RUNNING" if calc.in_run else "WAITING"
    print(
        f"\r  [{status}]  Speed: {speed_mph:5.1f} mph  |  "
        f"0-60: {sixty}  |  Dist: {dist}      ",
        end="",
        flush=True,
    )


def print_result(result, run_number: int) -> None:
    print(f"\n\n{'='*50}")
    print(f"  RUN #{run_number} RESULTS")
    print(f"{'='*50}")
    print(f"  0-60 mph         : {fmt_time(result.zero_to_sixty_s)}")
    print(f"  1/4 mile ET      : {fmt_time(result.quarter_mile_s)}")
    print(f"  1/4 mile trap    : {fmt_speed(result.quarter_mile_trap_mph)}")
    print(f"  Peak speed       : {fmt_speed(result.peak_speed_mph)}")
    print(f"  Distance covered : {result.distance_ft:.0f} ft")
    print(f"{'='*50}\n")


def run_drag(port: str, args, interrupted: list) -> None:
    """Run the drag-strip timer until interrupted."""
    calc = PerformanceCalculator()
    run_number = 0

    with GPSReader(port, update_hz=args.hz) as gps:
        print("GPS connected. Waiting for fix...")
        print("  Tip: the LED on the module blinks every second when searching,")
        print("       and every 15 seconds once it has a fix.\n")
        print("HOW TO USE:")
        print("  1. Come to a complete stop — the timer arms automatically.")
        print("  2. Accelerate hard. Timing begins when the car moves.")
        print("  3. Results print after you pass the 1/4 mile mark.")
        print("  Press Ctrl+C to quit.\n")

        for point in gps.read_points():
            if interrupted[0]:
                break

            print_live(point.speed_mph, calc)

            result = calc.feed(point)
            if result is not None:
                run_number += 1
                print_result(result, run_number)
                print("  Stopped. Come to a stop for the next run...\n")

    if calc.in_run:
        partial = calc.partial_result()
        if partial.distance_ft > 0:
            run_number += 1
            print(f"\n  Run #{run_number} interrupted — partial results:")
            print_result(partial, run_number)
