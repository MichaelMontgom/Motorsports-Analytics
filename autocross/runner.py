"""Autocross timing mode: run laps against a saved course, and map new courses."""

from util.gps_reader import GPSReader
from util.format import fmt_time, fmt_speed
from autocross.course import load_course
from autocross.calculator import AutocrossCalculator
from autocross.session_logger import append_run
from autocross.mapper import map_course


def print_lap_result(result, run_number: int) -> None:
    print(f"\n\n{'='*50}")
    print(f"  LAP #{run_number} — {result.course_name}")
    print(f"{'='*50}")
    for i, split in enumerate(result.split_times_s, 1):
        print(f"  Split {i} (cum.)  : {fmt_time(split)}")
    print(f"  Total time     : {fmt_time(result.total_time_s)}")
    print(f"  Peak speed     : {fmt_speed(result.peak_speed_mph)}")
    print(f"  Distance       : {result.distance_ft:.0f} ft")
    print(f"{'='*50}\n")


def _print_live(calc: AutocrossCalculator) -> None:
    partial = calc.partial_result()
    n_splits = len(calc.course.splits)
    if partial is None:
        print("\r  [ARMED]  cross the START line to begin...                 ",
              end="", flush=True)
    else:
        print(
            f"\r  [RUNNING]  {partial.total_time_s:6.2f}s  |  "
            f"splits {len(partial.split_times_s)}/{n_splits}  |  "
            f"dist {partial.distance_ft:.0f} ft      ",
            end="", flush=True,
        )


def run_autocross(port: str, args, interrupted: list) -> None:
    """Run autocross timing against the course named in args.course."""
    course = load_course(args.course)
    calc = AutocrossCalculator(course)
    run_number = 0

    with GPSReader(port, update_hz=args.hz) as gps:
        print(f"Autocross — course '{course.name}'  ({len(course.splits)} split gates).")
        print("Waiting for fix. Cross the START line to begin timing. Ctrl+C to quit.\n")

        for point in gps.read_points():
            if interrupted[0]:
                break

            _print_live(calc)

            result = calc.feed(point)
            if result is not None:
                run_number += 1
                print_lap_result(result, run_number)
                path = append_run(course, result)
                print(f"  Saved run to {path}")
                print("  Cross the START line for the next lap...\n")


def run_map_course(port: str, args, interrupted: list) -> None:
    """Interactively map and save a new course."""
    course = map_course(port, args.hz, args.name, args.width, interrupted)
    if course is not None:
        print(f"Course '{course.name}' saved with {len(course.splits)} split(s).")
