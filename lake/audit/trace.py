import sqlite3
from typing import Iterable, Protocol

from lake.audit.receipts import Receipt
from lake.book.adjustments import WithdrawalAdjustment, read_adjustment
from lake.intake.provenance import Provenance, provenance_fields


class FactOrigin(Protocol):
    fact_id: str
    provenance: Provenance


def snapshot_origins(facts: Iterable[FactOrigin]) -> dict[str, dict[str, str]]:
    return {fact.fact_id: provenance_fields(fact.provenance) for fact in facts}


def read_receipt_origins(
    db: sqlite3.Connection, receipt: Receipt, *, adjustment: WithdrawalAdjustment | None = None,
) -> dict[str, dict[str, str]]:
    if receipt.kind != 'withdraw':
        return receipt.origins
    if adjustment is None:
        adjustment = read_adjustment(db, receipt.details['adjustment_id'])
    if adjustment is None:
        raise sqlite3.DatabaseError('withdrawal receipt lacks its adjustment')
    return snapshot_origins(adjustment.removed)
