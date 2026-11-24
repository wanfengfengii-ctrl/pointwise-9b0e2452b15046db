import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import HistoryNotFound as HistoryNotFound
from lake.audit.receipts import Receipt, require_receipt
from lake.audit.trace import read_receipt_origins
from lake.book.adjustments import WithdrawalAdjustment, read_adjustment
from lake.intake.provenance import require_identifier
from lake.mirror.transactions import mirror_read
from lake.release.formats import Document
from lake.release.parts import read_original_parts
from lake.release.withdrawals import read_original_withdrawal


@dataclass(frozen=True)
class HistoryRecord:
    receipt: Receipt
    origins: dict[str, dict[str, str]]
    documents: tuple[Document, ...] = ()
    adjustment: WithdrawalAdjustment | None = None


def replay(db: sqlite3.Connection, number: str) -> HistoryRecord:
    number = require_identifier(number, 'historical number')
    with mirror_read(db):
        receipt = require_receipt(db, number)
        documents = ()
        adjustment = None
        if receipt.kind == 'issue':
            documents = read_original_parts(db, number)
        elif receipt.kind == 'withdraw_issue':
            documents = (read_original_withdrawal(db, number),)
        elif receipt.kind == 'withdraw':
            adjustment = read_adjustment(db, receipt.details['adjustment_id'])
            if adjustment is None:
                raise sqlite3.DatabaseError('withdrawal receipt lacks its adjustment')
        origins = read_receipt_origins(db, receipt, adjustment=adjustment)
        return HistoryRecord(receipt, origins, documents, adjustment)
