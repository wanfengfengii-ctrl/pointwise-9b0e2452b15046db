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
        )
        ORDER BY f.fact_id
    ''')
    return tuple(_part_fact(row) for row in rows)
