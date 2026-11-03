"""A small, well-structured example; importing it performs no work."""


def calculate_average(values: list[float]) -> float:
    """Return the arithmetic mean, rejecting an empty input."""
    if not values:
        raise ValueError("At least one value is required.")
    return sum(values) / len(values)
