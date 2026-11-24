import json
import sqlite3
from dataclasses import dataclass

from lake.audit.requests import canonical_content
from lake.book.facts import CurrentFact
from lake.book.station_totals import sum_station_facts, totals_by_station
from lake.intake.provenance import Provenance
from lake.intake.rows import litres_text, parse_litres


@dataclass(frozen=True)
class StationDelta:
    station: str
    row_delta: int
    litres_delta: int


@dataclass(frozen=True)
class WithdrawalAdjustment:
    notice_id: str
    publication_id: str
    removed: tuple[CurrentFact, ...]
    row_delta: int
    litres_delta: int
    by_station: tuple[StationDelta, ...]


def prepare_adjustment_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_adjustments (
            notice_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            removed TEXT NOT NULL, row_delta INTEGER NOT NULL, litres_delta TEXT NOT NULL,
            by_station TEXT NOT NULL
        )
    ''')


def compute_adjustment(
    notice_id: str, publication_id: str, before: tuple[CurrentFact, ...], after: tuple[CurrentFact, ...],
) -> WithdrawalAdjustment:
    original = {fact.fact_id: fact for fact in before}
    remaining = {fact.fact_id: fact for fact in after}
    if any(original.get(number) != fact for number, fact in remaining.items()):
        raise ValueError('a withdrawal cannot add or modify current facts')
    removed = tuple(original[number] for number in sorted(original.keys() - remaining.keys()))
    total = sum_station_facts(removed)
    by_station = tuple(
        StationDelta(station, -subtotal.row_count, -subtotal.litres)
        for station, subtotal in totals_by_station(removed).items()
    )
    return WithdrawalAdjustment(notice_id, publication_id, removed, -total.row_count, -total.litres, by_station)


def save_adjustment(db: sqlite3.Connection, adjustment: WithdrawalAdjustment) -> None:
    removed = canonical_content([
        [fact.fact_id, fact.station, litres_text(fact.litres), fact.provenance.record, fact.provenance.line]
        for fact in adjustment.removed
    ])
    by_station = canonical_content([
        [delta.station, delta.row_delta, litres_text(delta.litres_delta)] for delta in adjustment.by_station
    ])
    db.execute('INSERT INTO withdrawal_adjustments VALUES (?, ?, ?, ?, ?, ?)',
               (adjustment.notice_id, adjustment.publication_id, removed,
                adjustment.row_delta, litres_text(adjustment.litres_delta), by_station))


def read_adjustment(db: sqlite3.Connection, notice_id: str) -> WithdrawalAdjustment | None:
    row = db.execute('''
        SELECT publication_id, removed, row_delta, litres_delta, by_station
        FROM withdrawal_adjustments WHERE notice_id = ?
    ''', (notice_id,)).fetchone()
    if row is None:
        return None
    publication_id, removed, row_delta, litres_delta, by_station = row
    return WithdrawalAdjustment(
        notice_id, publication_id,
        tuple(CurrentFact(number, station, parse_litres(litres), Provenance(record, line))
              for number, station, litres, record, line in json.loads(removed)),
        row_delta, parse_litres(litres_delta),
        tuple(StationDelta(station, count, parse_litres(litres))
              for station, count, litres in json.loads(by_station)),
    )
