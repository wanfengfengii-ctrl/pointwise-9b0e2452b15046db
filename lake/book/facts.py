import sqlite3
from dataclasses import dataclass
from typing import Iterable

from lake.intake.provenance import Provenance
from lake.intake.rows import litres_text, parse_litres
from lake.release.formats import PartFact


@dataclass(frozen=True)
class CurrentFact:
    fact_id: str
    station: str
    litres: int
    provenance: Provenance


def prepare_fact_book(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS current_facts (
            fact_id TEXT PRIMARY KEY, station TEXT NOT NULL REFERENCES stations(station),
            litres TEXT NOT NULL, origin_record TEXT NOT NULL, origin_line TEXT NOT NULL
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS current_facts_by_station ON current_facts(station, fact_id)')


def replace_current_facts(db: sqlite3.Connection, evidence: Iterable[PartFact]) -> tuple[CurrentFact, ...]:
    unique = {}
    for fact in evidence:
        current = CurrentFact(fact.fact_id, fact.station, fact.litres, fact.provenance)
        if unique.setdefault(current.fact_id, current) != current:
            raise ValueError(f'inconsistent projection for fact {current.fact_id}')
    facts = tuple(unique[number] for number in sorted(unique))
    db.execute('DELETE FROM current_facts')
    db.executemany(
        'INSERT INTO current_facts VALUES (?, ?, ?, ?, ?)',
        ((fact.fact_id, fact.station, litres_text(fact.litres), fact.provenance.record, fact.provenance.line)
         for fact in facts),
    )
    return facts


def read_current_facts(db: sqlite3.Connection, station: str | None = None) -> tuple[CurrentFact, ...]:
    if station is None:
        rows = db.execute('SELECT * FROM current_facts ORDER BY fact_id')
    else:
        rows = db.execute('SELECT * FROM current_facts WHERE station = ? ORDER BY fact_id', (station,))
    return tuple(
        CurrentFact(fact_id, name, parse_litres(litres), Provenance(record, line))
        for fact_id, name, litres, record, line in rows
    )
