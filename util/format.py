"""Shared display formatting helpers."""


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "---"
    return f"{seconds:.3f}s"


def fmt_speed(mph: float | None) -> str:
    if mph is None:
        return "---"
    return f"{mph:.1f} mph"
