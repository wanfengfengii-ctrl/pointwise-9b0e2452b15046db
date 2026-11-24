import json
import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import Receipt, prepare_receipt_store, require_receipt, save_receipt
from lake.audit.requests import RequestConflict, bind_request, canonical_content, check_request, prepare_request_store
from lake.audit.trace import snapshot_origins
from lake.book.adjustments import WithdrawalAdjustment, compute_adjustment, prepare_adjustment_store, read_adjustment, save_adjustment
from lake.book.facts import prepare_fact_book, read_current_facts, replace_current_facts
from lake.book.stations import prepare_station_register, register_station, seed_stations
from lake.intake.rows import litres_text
from lake.mirror.conflicts import DocumentConflict, classify_document, validate_fact_consistency
from lake.mirror.eligibility import is_publication_withdrawn, mark_publication_withdrawn, prepare_eligibility_store
from lake.mirror.evidence import (
    list_active_facts,
    prepare_evidence_store,
    read_received_part,
    read_station_part_rows,
    record_received_part,
    record_received_station_part,
    record_verified_original,
    verified_original_digest,
)
from lake.mirror.transactions import mirror_write
from lake.release.formats import Document, PublicationPart, WithdrawalNotice, decode_document
from lake.release.station_parts import (
    STATION_PART_KIND,
    StationPart,
    decode_station_part,
    original_digest,
    station_part_fields,
    station_part_payload,
)


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


def _check_whole_against_station_rows(db: sqlite3.Connection, part: PublicationPart) -> None:
    for ordinal, fact in read_station_part_rows(db, part.part_id):
        if ordinal >= len(part.facts) or part.facts[ordinal] != fact:
            raise DocumentConflict(f'whole part {part.part_id} does not match received station rows')


def _check_station_rows_against_whole(db: sqlite3.Connection, part: StationPart) -> None:
    evidence = read_received_part(db, part.part_id)
    if evidence is None:
        return
    whole = evidence.document
    for row in part.rows:
        if row.ordinal >= len(whole.facts) or whole.facts[row.ordinal] != row.fact:
            raise DocumentConflict(f'station part does not match received whole part {part.part_id}')


def _receive_part(db: sqlite3.Connection, part: PublicationPart) -> AcceptanceResult:
    validate_fact_consistency(db, part.facts)
    digest = original_digest(part)
    known = verified_original_digest(db, part.part_id)
    if known is not None and known != digest:
        raise DocumentConflict(f'whole part does not match the verified original {part.part_id}')
    _check_whole_against_station_rows(db, part)
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
    record_verified_original(db, part.part_id, part.publication_id, digest)
    replace_current_facts(db, list_active_facts(db))
    return AcceptanceResult('received', receipt)


def _receive_station_part(db: sqlite3.Connection, part: StationPart) -> AcceptanceResult:
    validate_fact_consistency(db, part.facts)
    if is_publication_withdrawn(db, part.publication_id):
        return AcceptanceResult('late')

    before = {fact.fact_id for fact in read_current_facts(db)}
    register_station(db, part.station)
    facts = part.facts
    receipt = Receipt(
        part.station_part_id, 'receive',
        {
            'part_id': part.part_id,
            'station': part.station,
            'ordinals': [row.ordinal for row in part.rows],
            'facts': [
                {'fact_id': fact.fact_id, 'station': fact.station, 'litres': litres_text(fact.litres)}
                for fact in facts
            ],
            'added_fact_ids': [fact.fact_id for fact in facts if fact.fact_id not in before],
        },
        snapshot_origins(facts),
    )
    save_receipt(db, receipt)
    record_received_station_part(db, part, receipt.receipt_id)
    record_verified_original(db, part.part_id, part.publication_id, part.original_sha256)
    replace_current_facts(db, list_active_facts(db))
    return AcceptanceResult('received', receipt)


def _accept_station_part(db: sqlite3.Connection, part: StationPart, verify) -> AcceptanceResult:
    content = canonical_content(station_part_fields(part))
    try:
        previous = check_request(db, 'delivery', part.station_part_id, content)
    except RequestConflict as exc:
        raise DocumentConflict(f'different content for document {part.station_part_id}') from exc
    if previous is not None:
        return _replay_acceptance(db, previous)
    if not callable(verify):
        raise ValueError('accepting a station part requires a verify callable')
    if not verify(station_part_payload(part), part.token):
        raise ValueError('station part proof failed verification')
    known = verified_original_digest(db, part.part_id)
    if known is not None and known != part.original_sha256:
        raise DocumentConflict(f'station part does not match the verified original {part.part_id}')
    _check_station_rows_against_whole(db, part)
    result = _receive_station_part(db, part)
    if result.receipt is not None:
        bind_request(db, 'delivery', part.station_part_id, content, result.receipt.receipt_id)
    return result


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


def _decode_delivery(document: Document | StationPart | str | bytes | dict):
    if isinstance(document, (str, bytes)):
        probe = json.loads(document)
        if type(probe) is dict and probe.get('kind') == STATION_PART_KIND:
            return decode_station_part(document)
        return decode_document(document)
    if type(document) is dict:
        return decode_station_part(document)
    return document


def accept(
    db: sqlite3.Connection, document: Document | StationPart | str | bytes | dict, *,
    verify=None, fail_before_commit: bool = False,
) -> AcceptanceResult:
    document = _decode_delivery(document)
    with mirror_write(db, fail_before_commit=fail_before_commit):
        if isinstance(document, StationPart):
            return _accept_station_part(db, document, verify)
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
