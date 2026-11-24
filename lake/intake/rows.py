import re
from dataclasses import dataclass
from decimal import Decimal

from lake.intake.provenance import Provenance, require_identifier, validate_provenance


@dataclass(frozen=True)
class SourceRow:
    row_id: str
    litres: int
    provenance: Provenance


def litres_text(value: int) -> str:
    if type(value) is not int:
        raise ValueError('litres must be an integer')
    return str(Decimal(value))


def parse_litres(value: object) -> int:
    if type(value) is not str or re.fullmatch(r'0|-?[1-9][0-9]*', value) is None:
        raise ValueError('invalid canonical litres')
    return int(Decimal(value))


def validate_rows(rows: object) -> tuple[SourceRow, ...]:
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError('a batch needs ordered rows')
    seen = set()
    for row in rows:
        if not isinstance(row, SourceRow):
            raise ValueError('invalid source row')
        row_id = require_identifier(row.row_id, 'source row identifier')
        if row_id in seen:
            raise ValueError(f'duplicate source row {row_id}')
        if type(row.litres) is not int:
            raise ValueError(f'litres must be an integer on row {row_id}')
        validate_provenance(row.provenance)
        seen.add(row_id)
    return tuple(rows)
