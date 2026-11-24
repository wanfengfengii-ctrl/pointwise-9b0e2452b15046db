import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import Receipt, prepare_receipt_store, require_receipt, save_receipt
from lake.audit.requests import bind_request, canonical_content, check_request, fixed_number, prepare_request_store, write_request
from lake.audit.trace import snapshot_origins
from lake.intake.provenance import require_identifier
from lake.release.formats import PublicationPart
from lake.release.membership import arrange_members, select_members
from lake.release.parts import assemble_parts, prepare_part_store, read_original_parts, store_original_parts


@dataclass(frozen=True)
class IssuedPublication:
    publication_id: str
    parts: tuple[PublicationPart, ...]
    receipt: Receipt


def initialize_release(db: sqlite3.Connection) -> None:
    with write_request(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                publication_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE
            )
        ''')
        prepare_part_store(db)
        prepare_request_store(db)
        prepare_receipt_store(db)


def find_publication(db: sqlite3.Connection, publication_id: str) -> IssuedPublication | None:
    row = db.execute('SELECT 1 FROM publications WHERE publication_id = ?', (publication_id,)).fetchone()
    if row is None:
        return None
    return IssuedPublication(
        publication_id, read_original_parts(db, publication_id), require_receipt(db, publication_id),
    )


def issue(db: sqlite3.Connection, request_id: str, fact_ids: object, parts: object) -> IssuedPublication:
    request_id = require_identifier(request_id, 'issuance request')
    with write_request(db):
        members = select_members(db, fact_ids)
        arranged = arrange_members(members, parts)
        selection = [fact.fact_id for fact in members]
        layout = [[fact.fact_id for fact in part] for part in arranged]
        content = canonical_content({'selection': selection, 'parts': layout})
        previous = check_request(db, 'issue', request_id, content)
        if previous is not None:
            original = find_publication(db, previous)
            if original is None:
                raise sqlite3.DatabaseError('issuance binding lacks its publication')
            return original

        publication_id = fixed_number('publication', [request_id, selection, layout])
        fixed_parts = assemble_parts(publication_id, arranged)
        db.execute('INSERT INTO publications VALUES (?, ?)', (publication_id, request_id))
        store_original_parts(db, fixed_parts)
        receipt = Receipt(
            publication_id, 'issue',
            {'publication_id': publication_id, 'fact_ids': selection,
             'part_ids': [part.part_id for part in fixed_parts]},
            snapshot_origins(members),
        )
        save_receipt(db, receipt)
        bind_request(db, 'issue', request_id, content, receipt.receipt_id)
        return IssuedPublication(publication_id, fixed_parts, receipt)
