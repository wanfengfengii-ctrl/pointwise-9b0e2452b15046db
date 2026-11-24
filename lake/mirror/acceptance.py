import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import Receipt, prepare_receipt_store, require_receipt, save_receipt
from lake.audit.requests import bind_request, prepare_request_store
from lake.audit.trace import snapshot_origins
from lake.book.adjustments import WithdrawalAdjustment, compute_adjustment, prepare_adjustment_store, read_adjustment, save_adjustment
from lake.book.facts import prepare_fact_book, read_current_facts, replace_current_facts
from lake.book.stations import prepare_station_register, register_station, seed_stations
from lake.intake.rows import litres_text
from lake.mirror.conflicts import DocumentConflict, classify_document, validate_fact_consistency
from lake.mirror.eligibility import is_publication_withdrawn, mark_publication_withdrawn, prepare_eligibility_store
from lake.mirror.evidence import list_active_facts, prepare_evidence_store, record_received_part
from lake.mirror.transactions import mirror_write
from lake.release.formats import Document, PublicationPart, WithdrawalNotice, decode_document


@dataclass(frozen=True)
class AcceptanceResult:
    status: str
    receipt: Receipt | None = None
    adjustment: WithdrawalAdjustment | None = None


def initialize_mirror(db: sqlite3.Connection, stations=()) -> None:
    with mirror_write(db):
        prepare_request_store(db)
        prepare_receipt_store(db)
        prepare_station_register(db)
        prepare_eligibility_store(db)
        prepare_evidence_store(db)
        prepare_fact_book(db)
        prepare_adjustment_store(db)
        seed_stations(db, stations)


def _replay_acceptance(db: sqlite3.Connection, receipt_id: str) -> AcceptanceResult:
    receipt = require_receipt(db, receipt_id)
    if receipt.kind == 'receive':
        return AcceptanceResult('received', receipt)
    adjustment = read_adjustment(db, receipt_id)
    if adjustment is None:
        raise sqlite3.DatabaseError('withdrawal receipt lacks its settlement')
    return AcceptanceResult('withdrawn', receipt, adjustment)


def _receive_part(db: sqlite3.Connection, part: PublicationPart) -> AcceptanceResult:
    validate_fact_consistency(db, part)
    if is_publication_withdrawn(db, part.publication_id):
        return AcceptanceResult('late')

    before = {fact.fact_id for fact in read_current_facts(db)}
    for station in sorted({fact.station for fact in part.facts}):
        register_station(db, station)
    receipt = Receipt(
        part.part_id, 'receive',
        {
            'facts': [
                {'fact_id': fact.fact_id, 'station': fact.station, 'litres': litres_text(fact.litres)}
                for fact in part.facts
            ],
            'added_fact_ids': [fact.fact_id for fact in part.facts if fact.fact_id not in before],
        },
        snapshot_origins(part.facts),
    )
    save_receipt(db, receipt)
    record_received_part(db, part, receipt.receipt_id)
    replace_current_facts(db, list_active_facts(db))
    return AcceptanceResult('received', receipt)


def _settle_withdrawal(db: sqlite3.Connection, notice: WithdrawalNotice) -> AcceptanceResult:
    before = read_current_facts(db)
    recorded = mark_publication_withdrawn(db, notice.publication_id, notice.notice_id)
    if recorded != notice.notice_id:
        raise DocumentConflict(f'publication already has withdrawal {recorded}')
    after = replace_current_facts(db, list_active_facts(db))
    adjustment = compute_adjustment(notice.notice_id, notice.publication_id, before, after)
    save_adjustment(db, adjustment)
    receipt = Receipt(
        notice.notice_id, 'withdraw', {'adjustment_id': adjustment.notice_id}, {},
    )
    save_receipt(db, receipt)
    return AcceptanceResult('withdrawn', receipt, adjustment)


def accept(
    db: sqlite3.Connection, document: Document | str | bytes, *, fail_before_commit: bool = False,
) -> AcceptanceResult:
    if isinstance(document, (str, bytes)):
        document = decode_document(document)
    with mirror_write(db, fail_before_commit=fail_before_commit):
        content, previous = classify_document(db, document)
        if previous is not None:
            return _replay_acceptance(db, previous)
        if isinstance(document, PublicationPart):
            result = _receive_part(db, document)
        else:
            result = _settle_withdrawal(db, document)
        if result.receipt is not None:
            bind_request(db, 'delivery', document.number, content, result.receipt.receipt_id)
        return result
