"""Harmless example with an intentional logic bug; no automatic execution."""


def is_even(number: int) -> bool:
    """Return whether a number is even (intentionally incorrect for practice)."""
    return number % 2 == 1
