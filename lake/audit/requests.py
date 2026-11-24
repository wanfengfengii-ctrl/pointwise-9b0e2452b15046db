import hashlib
import json
import sqlite3
from contextlib import contextmanager


class RequestConflict(ValueError):
    pass


def canonical_content(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def fixed_number(category: str, value: object) -> str:
    return f'{category}:{_fingerprint(canonical_content(value))}'


def prepare_request_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS request_bindings (
            namespace TEXT NOT NULL, request_id TEXT NOT NULL, content_digest TEXT NOT NULL,
            receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            PRIMARY KEY(namespace, request_id)
        )
    ''')


def check_request(db: sqlite3.Connection, namespace: str, request_id: str, content: str) -> str | None:
    row = db.execute('''
        SELECT content_digest, receipt_id FROM request_bindings WHERE namespace = ? AND request_id = ?
    ''', (namespace, request_id)).fetchone()
    if row is None:
        return None
    if row[0] != _fingerprint(content):
        raise RequestConflict(f'different content for {namespace} request {request_id}')
    return row[1]


def bind_request(db: sqlite3.Connection, namespace: str, request_id: str, content: str, receipt_id: str) -> None:
    db.execute('INSERT INTO request_bindings VALUES (?, ?, ?, ?)',
               (namespace, request_id, _fingerprint(content), receipt_id))


@contextmanager
def write_request(db: sqlite3.Connection):
    if db.in_transaction:
        raise ValueError('a write operation requires an idle connection')
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
