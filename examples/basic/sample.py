"""Deliberately wasteful sample for `greenlint examples/basic/` to flag."""


def poll_forever() -> None:
    while True:
        check_queue()  # GL001: busy loop without sleep


def load_users(db: object) -> object:
    return db.query("SELECT * FROM users")  # GL005: SELECT * query


def check_queue() -> None:
    """Stand-in for real work, so the sample is valid code."""
