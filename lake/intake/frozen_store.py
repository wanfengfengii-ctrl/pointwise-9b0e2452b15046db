import sqlite3
from dataclasses import dataclass
from typing import Iterable

from lake.intake.batches import BatchInput
from lake.intake.provenance import Provenance
from lake.intake.rows import litres_text, parse_litres


@dataclass(frozen=True)
class FrozenFact:
    fact_id: str
    batch_id: str
    ordinal: int
    row_id: str
    station: str
    litres: int
    provenance: Provenance


def prepare_frozen_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS frozen_batches (
            batch_id TEXT PRIMARY KEY, station TEXT NOT NULL, name TEXT NOT NULL,
            UNIQUE(station, name)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS frozen_facts (
            fact_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
            ordinal INTEGER NOT NULL, row_id TEXT NOT NULL, litres TEXT NOT NULL,
            origin_record TEXT NOT NULL, origin_line TEXT NOT NULL,
            UNIQUE(batch_id, ordinal), UNIQUE(batch_id, row_id)
        )
    ''')


def insert_frozen_batch(db: sqlite3.Connection, batch_id: str, batch: BatchInput) -> tuple[FrozenFact, ...]:
    db.execute('INSERT INTO frozen_batches VALUES (?, ?, ?)', (batch_id, batch.station, batch.name))
    facts = tuple(
        FrozenFact(f'{batch_id}/{ordinal:012d}', batch_id, ordinal, row.row_id,
                   batch.station, row.litres, row.provenance)
        for ordinal, row in enumerate(batch.rows, start=1)
    )
    db.executemany(
        'INSERT INTO frozen_facts VALUES (?, ?, ?, ?, ?, ?, ?)',
        ((fact.fact_id, fact.batch_id, fact.ordinal, fact.row_id, litres_text(fact.litres),
          fact.provenance.record, fact.provenance.line) for fact in facts),
    )
    return facts


_FACT_SELECT = '''
    SELECT f.fact_id, f.batch_id, f.ordinal, f.row_id, b.station, f.litres,
           f.origin_record, f.origin_line
    FROM frozen_facts AS f JOIN frozen_batches AS b USING (batch_id)
'''


def _fact(row) -> FrozenFact:
    return FrozenFact(*row[:5], parse_litres(row[5]), Provenance(row[6], row[7]))


def read_frozen_batch(db: sqlite3.Connection, batch_id: str) -> tuple[FrozenFact, ...]:
    rows = db.execute(_FACT_SELECT + ' WHERE f.batch_id = ? ORDER BY f.ordinal', (batch_id,))
    return tuple(_fact(row) for row in rows)


def load_frozen_facts(db: sqlite3.Connection, fact_ids: Iterable[str]) -> tuple[FrozenFact, ...]:
    facts = []
    for fact_id in fact_ids:
        row = db.execute(_FACT_SELECT + ' WHERE f.fact_id = ?', (fact_id,)).fetchone()
        if row is None:
            raise KeyError(fact_id)
        facts.append(_fact(row))
    return tuple(facts)
