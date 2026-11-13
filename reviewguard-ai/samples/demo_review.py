"""Synthetic review exercise with intentional defects; never run automatically."""


def is_even(number: int) -> bool:
    """Return True when the input is even."""
    return number % 2 == 1


def find_user(connection, username: str):
    """Look up a user in an example database connection."""
    query = f"SELECT id, username FROM users WHERE username = '{username}'"
    return connection.execute(query).fetchall()
