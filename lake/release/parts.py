import sqlite3
from dataclasses import replace

from lake.audit.receipts import HistoryNotFound
from lake.intake.frozen_store import FrozenFact
from lake.intake.provenance import require_identifier
from lake.release.formats import PartFact, PublicationPart, decode_document, encode_document, part_number
from lake.release.station_parts import (
    StationPart,
    StationPartRow,
    original_digest,
    station_part_fields,
    station_part_number,
    station_part_payload,
)


def prepare_part_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS original_parts (
            part_id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL REFERENCES publications(publication_id),
            position INTEGER NOT NULL, document TEXT NOT NULL,
            UNIQUE(publication_id, position)
        )
    ''')


def assemble_parts(
    publication_id: str, arranged: tuple[tuple[FrozenFact, ...], ...],
) -> tuple[PublicationPart, ...]:
    return tuple(
        PublicationPart(
            part_number(publication_id, position), publication_id, position,
            tuple(PartFact(fact.fact_id, fact.station, fact.litres, fact.provenance) for fact in facts),
        )
        for position, facts in enumerate(arranged)
    )


def store_original_parts(db: sqlite3.Connection, parts: tuple[PublicationPart, ...]) -> None:
    db.executemany(
        'INSERT INTO original_parts VALUES (?, ?, ?, ?)',
        ((part.part_id, part.publication_id, part.position, encode_document(part)) for part in parts),
    )


def read_original_parts(db: sqlite3.Connection, publication_id: str) -> tuple[PublicationPart, ...]:
    rows = db.execute(
        'SELECT document FROM original_parts WHERE publication_id = ? ORDER BY position',
        (publication_id,),
    )
    parts = []
    for (document,) in rows:
        part = decode_document(document)
        if not isinstance(part, PublicationPart):
            raise ValueError('stored part has the wrong document kind')
        parts.append(part)
    return tuple(parts)


def read_original_part(db: sqlite3.Connection, part_id: str) -> PublicationPart | None:
    row = db.execute('SELECT document FROM original_parts WHERE part_id = ?', (part_id,)).fetchone()
    if row is None:
        return None
    part = decode_document(row[0])
    if not isinstance(part, PublicationPart):
        raise ValueError('stored part has the wrong document kind')
    return part


def export_station_part(db: sqlite3.Connection, part_id: object, station: object, *, attest) -> dict:
    if not callable(attest):
        raise ValueError('expected an attest callable')
    part_id = require_identifier(part_id, 'part number')
    station = require_identifier(station, 'station')
    part = read_original_part(db, part_id)
    if part is None:
        raise HistoryNotFound(part_id)
    rows = tuple(
        StationPartRow(ordinal, fact)
        for ordinal, fact in enumerate(part.facts)
        if fact.station == station
    )
    if not rows:
        raise ValueError(f'part {part_id} has no rows for station {station}')
    draft = StationPart(
        station_part_number(part.part_id, station), part.part_id, part.publication_id,
        part.position, station, rows, original_digest(part), '',
    )
    token = attest(station_part_payload(draft))
    if type(token) is not str or not token:
        raise ValueError('attest must return a nonempty token')
    return station_part_fields(replace(draft, token=token))
