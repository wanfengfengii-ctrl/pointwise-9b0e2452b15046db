import sqlite3
from dataclasses import dataclass

from lake.intake.provenance import Provenance
from lake.intake.rows import litres_text, parse_litres
from lake.release.formats import PartFact, PublicationPart


@dataclass(frozen=True)
class PartEvidence:
    document: PublicationPart
    receipt_id: str


def prepare_evidence_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS received_parts (
            part_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            position INTEGER NOT NULL, receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            UNIQUE(publication_id, position)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS received_facts (
            fact_id TEXT PRIMARY KEY, station TEXT NOT NULL, litres TEXT NOT NULL,
            origin_record TEXT NOT NULL, origin_line TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS part_facts (
            part_id TEXT NOT NULL REFERENCES received_parts(part_id),
            ordinal INTEGER NOT NULL, fact_id TEXT NOT NULL REFERENCES received_facts(fact_id),
            PRIMARY KEY(part_id, ordinal), UNIQUE(part_id, fact_id)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS part_facts_by_fact ON part_facts(fact_id)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS received_station_parts (
            station_part_id TEXT PRIMARY KEY, part_id TEXT NOT NULL,
            publication_id TEXT NOT NULL, position INTEGER NOT NULL, station TEXT NOT NULL,
            original_sha256 TEXT NOT NULL,
            receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            UNIQUE(part_id, station)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_part_facts (
            station_part_id TEXT NOT NULL REFERENCES received_station_parts(station_part_id),
            ordinal INTEGER NOT NULL, fact_id TEXT NOT NULL REFERENCES received_facts(fact_id),
            PRIMARY KEY(station_part_id, ordinal), UNIQUE(station_part_id, fact_id)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS station_part_facts_by_fact ON station_part_facts(fact_id)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS verified_originals (
            part_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL, original_sha256 TEXT NOT NULL
        )
    ''')


def record_received_part(db: sqlite3.Connection, part: PublicationPart, receipt_id: str) -> None:
    db.execute('INSERT INTO received_parts VALUES (?, ?, ?, ?)',
               (part.part_id, part.publication_id, part.position, receipt_id))
    db.executemany(
        'INSERT INTO received_facts VALUES (?, ?, ?, ?, ?) ON CONFLICT(fact_id) DO NOTHING',
        ((fact.fact_id, fact.station, litres_text(fact.litres), fact.provenance.record, fact.provenance.line)
         for fact in part.facts),
    )
    db.executemany('INSERT INTO part_facts VALUES (?, ?, ?)',
                   ((part.part_id, ordinal, fact.fact_id) for ordinal, fact in enumerate(part.facts)))


def record_received_station_part(db: sqlite3.Connection, part, receipt_id: str) -> None:
    db.execute('INSERT INTO received_station_parts VALUES (?, ?, ?, ?, ?, ?, ?)',
               (part.station_part_id, part.part_id, part.publication_id, part.position,
                part.station, part.original_sha256, receipt_id))
    db.executemany(
        'INSERT INTO received_facts VALUES (?, ?, ?, ?, ?) ON CONFLICT(fact_id) DO NOTHING',
        ((fact.fact_id, fact.station, litres_text(fact.litres), fact.provenance.record, fact.provenance.line)
         for fact in part.facts),
    )
    db.executemany('INSERT INTO station_part_facts VALUES (?, ?, ?)',
                   ((part.station_part_id, row.ordinal, row.fact.fact_id) for row in part.rows))


def read_station_part_rows(db: sqlite3.Connection, part_id: str) -> tuple[tuple[int, PartFact], ...]:
    rows = db.execute('''
        SELECT sf.ordinal, f.* FROM station_part_facts AS sf
        JOIN received_station_parts AS sp USING (station_part_id)
        JOIN received_facts AS f USING (fact_id)
        WHERE sp.part_id = ? ORDER BY sf.ordinal
    ''', (part_id,))
    return tuple((row[0], _part_fact(row[1:])) for row in rows)


def verified_original_digest(db: sqlite3.Connection, part_id: str) -> str | None:
    row = db.execute(
        'SELECT original_sha256 FROM verified_originals WHERE part_id = ?', (part_id,),
    ).fetchone()
    return None if row is None else row[0]


def record_verified_original(db: sqlite3.Connection, part_id: str, publication_id: str, original_sha256: str) -> None:
    db.execute('INSERT INTO verified_originals VALUES (?, ?, ?) ON CONFLICT(part_id) DO NOTHING',
               (part_id, publication_id, original_sha256))


def _part_fact(row) -> PartFact:
    return PartFact(row[0], row[1], parse_litres(row[2]), Provenance(row[3], row[4]))


def read_known_fact(db: sqlite3.Connection, fact_id: str) -> PartFact | None:
    row = db.execute('SELECT * FROM received_facts WHERE fact_id = ?', (fact_id,)).fetchone()
    return None if row is None else _part_fact(row)


def read_received_part(db: sqlite3.Connection, part_id: str) -> PartEvidence | None:
    row = db.execute('''
        SELECT publication_id, position, receipt_id FROM received_parts WHERE part_id = ?
    ''', (part_id,)).fetchone()
    if row is None:
        return None
    publication_id, position, receipt_id = row
    facts = db.execute('''
        SELECT f.* FROM part_facts AS pf JOIN received_facts AS f USING (fact_id)
        WHERE pf.part_id = ? ORDER BY pf.ordinal
    ''', (part_id,))
    part = PublicationPart(part_id, publication_id, position, tuple(_part_fact(fact) for fact in facts))
    return PartEvidence(part, receipt_id)


def list_active_facts(db: sqlite3.Connection) -> tuple[PartFact, ...]:
    rows = db.execute('''
        SELECT f.* FROM received_facts AS f
        WHERE EXISTS (
            SELECT 1 FROM part_facts AS pf JOIN received_parts AS p USING (part_id)
            LEFT JOIN withdrawn_publications AS w ON w.publication_id = p.publication_id
            WHERE pf.fact_id = f.fact_id AND w.publication_id IS NULL
        ) OR EXISTS (
            SELECT 1 FROM station_part_facts AS sf
            JOIN received_station_parts AS sp USING (station_part_id)
            LEFT JOIN withdrawn_publications AS w ON w.publication_id = sp.publication_id
            WHERE sf.fact_id = f.fact_id AND w.publication_id IS NULL
        )
        ORDER BY f.fact_id
    ''')
    return tuple(_part_fact(row) for row in rows)
