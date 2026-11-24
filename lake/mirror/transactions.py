import sqlite3
from contextlib import contextmanager

from lake.audit.requests import write_request


class CommitInterrupted(RuntimeError):
    pass


@contextmanager
def mirror_write(db: sqlite3.Connection, *, fail_before_commit: bool = False):
    with write_request(db):
        yield
        if fail_before_commit:
            raise CommitInterrupted('mirror transaction interrupted before commit')


@contextmanager
def mirror_read(db: sqlite3.Connection):
    if db.in_transaction:
        raise ValueError('reading a snapshot requires an idle connection')
    db.execute('BEGIN')
    try:
        yield
    finally:
        db.rollback()
