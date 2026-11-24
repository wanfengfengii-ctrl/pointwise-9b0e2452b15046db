import sqlite3

from lake.intake.frozen_store import FrozenFact, load_frozen_facts
from lake.intake.provenance import require_identifier


class MemberSelectionError(ValueError):
    pass


def _fact_numbers(numbers: object) -> tuple[str, ...]:
    if not isinstance(numbers, (tuple, list)) or not numbers:
        raise MemberSelectionError('expected a nonempty ordered fact selection')
    try:
        return tuple(require_identifier(number, 'fact number') for number in numbers)
    except ValueError as exc:
        raise MemberSelectionError(str(exc)) from exc


def select_members(db: sqlite3.Connection, fact_ids: object) -> tuple[FrozenFact, ...]:
    fact_ids = _fact_numbers(fact_ids)
    if len(set(fact_ids)) != len(fact_ids):
        raise MemberSelectionError('duplicate selected fact')
    try:
        return load_frozen_facts(db, fact_ids)
    except KeyError as exc:
        raise MemberSelectionError(f'unknown frozen fact {exc.args[0]}') from exc


def arrange_members(members: tuple[FrozenFact, ...], parts: object) -> tuple[tuple[FrozenFact, ...], ...]:
    if not isinstance(parts, (list, tuple)) or not parts:
        raise MemberSelectionError('expected one or more ordered parts')
    remaining = {fact.fact_id: fact for fact in members}
    arranged = []
    for part in parts:
        ordered = []
        for number in _fact_numbers(part):
            fact = remaining.pop(number, None)
            if fact is None:
                raise MemberSelectionError(f'fact was repeated or was never selected: {number}')
            ordered.append(fact)
        arranged.append(tuple(ordered))
    if remaining:
        raise MemberSelectionError('the parts omit selected facts')
    return tuple(arranged)
