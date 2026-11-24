import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import Receipt, prepare_receipt_store, require_receipt, save_receipt
from lake.audit.requests import bind_request, canonical_content, check_request, prepare_request_store, write_request
from lake.audit.trace import snapshot_origins
from lake.intake.batches import BatchInput, batch_content, batch_identity, validate_batch
from lake.intake.frozen_store import FrozenFact, insert_frozen_batch, prepare_frozen_store, read_frozen_batch


@dataclass(frozen=True)
class FreezeResult:
    batch_id: str
    facts: tuple[FrozenFact, ...]
    receipt: Receipt


def initialize_freeze(db: sqlite3.Connection) -> None:
    with write_request(db):
        prepare_frozen_store(db)
        prepare_request_store(db)
        prepare_receipt_store(db)


def freeze(db: sqlite3.Connection, batch: BatchInput) -> FreezeResult:
    batch = validate_batch(batch)
    batch_id = batch_identity(batch.station, batch.name)
    content = canonical_content(batch_content(batch))
    with write_request(db):
        previous = check_request(db, 'freeze', batch_id, content)
        if previous is not None:
            return FreezeResult(batch_id, read_frozen_batch(db, batch_id), require_receipt(db, previous))
        facts = insert_frozen_batch(db, batch_id, batch)
        receipt = Receipt(
            batch_id, 'freeze',
            {'batch_id': batch_id, 'station': batch.station, 'fact_ids': [fact.fact_id for fact in facts]},
            snapshot_origins(facts),
        )
        save_receipt(db, receipt)
        bind_request(db, 'freeze', batch_id, content, receipt.receipt_id)
        return FreezeResult(batch_id, facts, receipt)
