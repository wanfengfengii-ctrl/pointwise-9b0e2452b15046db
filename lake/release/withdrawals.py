import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import HistoryNotFound, Receipt, prepare_receipt_store, require_receipt, save_receipt
from lake.audit.requests import bind_request, canonical_content, check_request, fixed_number, prepare_request_store, write_request
from lake.intake.provenance import require_identifier
from lake.release.formats import WithdrawalNotice, decode_document, encode_document


@dataclass(frozen=True)
class IssuedWithdrawal:
    notice: WithdrawalNotice
    receipt: Receipt


def initialize_withdrawals(db: sqlite3.Connection) -> None:
    with write_request(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS original_withdrawals (
                publication_id TEXT PRIMARY KEY REFERENCES publications(publication_id),
                notice_id TEXT NOT NULL UNIQUE, document TEXT NOT NULL
            )
        ''')
        prepare_request_store(db)
        prepare_receipt_store(db)


def read_original_withdrawal(db: sqlite3.Connection, notice_id: str) -> WithdrawalNotice:
    row = db.execute('SELECT document FROM original_withdrawals WHERE notice_id = ?', (notice_id,)).fetchone()
    if row is None:
        raise HistoryNotFound(notice_id)
    notice = decode_document(row[0])
    if not isinstance(notice, WithdrawalNotice):
        raise ValueError('stored withdrawal has the wrong document kind')
    return notice


def _original_result(db: sqlite3.Connection, notice_id: str) -> IssuedWithdrawal:
    return IssuedWithdrawal(read_original_withdrawal(db, notice_id), require_receipt(db, notice_id))


def withdraw_issue(db: sqlite3.Connection, request_id: str, publication_id: str) -> IssuedWithdrawal:
    request_id = require_identifier(request_id, 'withdrawal request')
    publication_id = require_identifier(publication_id, 'publication number')
    content = canonical_content({'publication_id': publication_id})
    with write_request(db):
        previous = check_request(db, 'withdraw_issue', request_id, content)
        if previous is not None:
            return _original_result(db, previous)
        if db.execute('SELECT 1 FROM publications WHERE publication_id = ?', (publication_id,)).fetchone() is None:
            raise HistoryNotFound(publication_id)
        existing = db.execute(
            'SELECT notice_id FROM original_withdrawals WHERE publication_id = ?', (publication_id,),
        ).fetchone()
        if existing is not None:
            bind_request(db, 'withdraw_issue', request_id, content, existing[0])
            return _original_result(db, existing[0])

        notice = WithdrawalNotice(fixed_number('withdrawal', request_id), publication_id)
        db.execute(
            'INSERT INTO original_withdrawals VALUES (?, ?, ?)',
            (publication_id, notice.notice_id, encode_document(notice)),
        )
        receipt = Receipt(notice.notice_id, 'withdraw_issue', {'publication_id': publication_id}, {})
        save_receipt(db, receipt)
        bind_request(db, 'withdraw_issue', request_id, content, receipt.receipt_id)
        return IssuedWithdrawal(notice, receipt)
