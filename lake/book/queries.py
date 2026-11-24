import sqlite3
from dataclasses import dataclass

from lake.audit.receipts import HistoryNotFound
from lake.book.adjustments import WithdrawalAdjustment, read_adjustment
from lake.book.facts import CurrentFact, read_current_facts
from lake.book.station_totals import sum_station_facts
from lake.book.stations import require_station
from lake.mirror.transactions import mirror_read


@dataclass(frozen=True)
class StationBook:
    station: str
    facts: tuple[CurrentFact, ...]
    row_count: int
    litres: int


def station_book(db: sqlite3.Connection, station: str) -> StationBook:
    with mirror_read(db):
        require_station(db, station)
        facts = read_current_facts(db, station)
        total = sum_station_facts(facts)
        return StationBook(station, facts, total.row_count, total.litres)


def withdrawal_adjustment(db: sqlite3.Connection, notice_id: str) -> WithdrawalAdjustment:
    with mirror_read(db):
        adjustment = read_adjustment(db, notice_id)
        if adjustment is None:
            raise HistoryNotFound(notice_id)
        return adjustment
