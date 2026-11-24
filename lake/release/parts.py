import sqlite3

from lake.intake.frozen_store import FrozenFact
from lake.release.formats import PartFact, PublicationPart, decode_document, encode_document, part_number


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
