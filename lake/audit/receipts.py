import json
import sqlite3
from dataclasses import dataclass

from lake.audit.requests import canonical_content


class HistoryNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    kind: str
    details: dict
    origins: dict[str, dict[str, str]]


def prepare_receipt_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
            details TEXT NOT NULL, origins TEXT NOT NULL
        )
    ''')


def save_receipt(db: sqlite3.Connection, receipt: Receipt) -> None:
    db.execute('INSERT INTO receipts VALUES (?, ?, ?, ?)',
               (receipt.receipt_id, receipt.kind, canonical_content(receipt.details), canonical_content(receipt.origins)))


def read_receipt(db: sqlite3.Connection, receipt_id: str) -> Receipt | None:
    row = db.execute('SELECT kind, details, origins FROM receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
    if row is None:
        return None
    return Receipt(receipt_id, row[0], json.loads(row[1]), json.loads(row[2]))


def require_receipt(db: sqlite3.Connection, receipt_id: str) -> Receipt:
    receipt = read_receipt(db, receipt_id)
    if receipt is None:
        raise HistoryNotFound(receipt_id)
    return receipt
