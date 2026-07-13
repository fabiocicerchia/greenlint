"""Deliberately wasteful sample for `greenlint examples/basic/` to flag."""


def poll_forever():
    while True:
        check_queue()  # GL001: busy loop without sleep


def load_users(db):
    return db.query("SELECT * FROM users")  # GL005: SELECT * query
