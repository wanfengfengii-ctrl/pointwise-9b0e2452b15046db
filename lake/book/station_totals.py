from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from lake.book.facts import CurrentFact


@dataclass(frozen=True)
class StationTotal:
    row_count: int
    litres: int


def sum_station_facts(facts: Iterable[CurrentFact]) -> StationTotal:
    row_count = 0
    litres = 0
    for fact in facts:
        row_count += 1
        litres += fact.litres
    return StationTotal(row_count, litres)


def totals_by_station(facts: Iterable[CurrentFact]) -> dict[str, StationTotal]:
    grouped = defaultdict(list)
    for fact in facts:
        grouped[fact.station].append(fact)
    return {station: sum_station_facts(grouped[station]) for station in sorted(grouped)}
